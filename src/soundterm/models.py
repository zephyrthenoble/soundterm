from __future__ import annotations
from turtle import back
from markdown_it.rules_block import table
from sqlmodel import (
    SQLModel,
    Field,
    Relationship,
    Session,
    select,
    col,
    String,
    Column,
    JSON,
)
from typing import Optional, Literal, Sequence
from datetime import datetime
from pathlib import Path
import pydantic
from os import PathLike
from uuid import uuid4

from sqlalchemy.ext.mutable import MutableList

from soundterm.utils import try_multiple_keys
from soundterm.utils import SmartParser
from soundterm.settings import get_settings
from soundterm.utils import random_color
from soundterm.acoustid import AcoustIDLookupResults


type Fingerprint = str

type TrackMetadataType = (
    str | int | float | list[float] | set[PathLike] | set[Tag] | datetime | None
)


# For simple scalar fields, we can choose to keep either self or other when there is a conflict, or raise an error
type TrackMetadataValueConflictStrategy = Literal["self", "other", "update", "raise"]

# merge: for list fields, combine unique values from both (e.g. union of artists or tags)
# update: for list fields, replace blank or None with non-empty values from the other
# raise: for list fields, if both have non-empty values that differ, raise an error instead of merging
type TrackMetadataListConflictStrategy = Literal["merge", "update", "raise"]

type TrackMetadataCombineFingerprintsStrategy = Literal["self", "other", "raise"]
type TrackMetadataCombinePathStrategy = Literal["self", "other", "raise"]

# Link tables for many-to-many relationships


class TrackReleaseLink(SQLModel, table=True):
    track_id: int = Field(foreign_key="trackmetadata.id", primary_key=True)
    release: str = Field(primary_key=True)


class ParentTagLink(SQLModel, table=True):
    parent_tag_id: int = Field(foreign_key="tag.id", primary_key=True)
    child_tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class GroupTagLink(SQLModel, table=True):
    group_id: int = Field(foreign_key="taggroup.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class SongTagLink(SQLModel, table=True):
    song_id: int = Field(foreign_key="song.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


SingleSearchValues = Literal["exact", "like"]
ListSearchValues = Literal["any", "all", "only"]


def get_songs_by_path(
    session: Session, path: PathLike, searchType: SingleSearchValues = "exact"
) -> Sequence[Song]:
    if searchType == "exact":
        statement = select(Song).where(path in col(Song.paths))
    elif searchType == "like":
        statement = select(Song).where(col(Song.paths).like(f"%{path}%"))
    else:
        raise ValueError(f"Invalid searchType: {searchType}. Use {SingleSearchValues}.")
    results = session.exec(statement).all()
    return results


def get_songs_with_tags(
    session: Session, tags: set[str], searchType: ListSearchValues = "all"
) -> Sequence[Song]:
    if searchType == "all":
        statement = select(Song).where(col(Song.tags).contains(tags))
    elif searchType == "any":
        statement = select(Song).where(
            col(Song.tags).like(f"%{tags}%")
        )  # does like work on sequences
    elif searchType == "only":
        statement = select(Song).where(col(Song.tags) == tags)
    else:
        raise ValueError(f"Invalid searchType: {searchType}. Use {ListSearchValues}.")
    results = session.exec(statement).all()
    return results


def select_songs_with_tags(
    songs: Sequence[Song], tags: set[str], searchType: ListSearchValues = "all"
) -> Sequence[Song]:
    if searchType == "all":
        filtered_songs = [
            song for song in songs if tags.issubset({tag.name for tag in song.tags})
        ]
    elif searchType == "any":
        filtered_songs = [
            song for song in songs if any(tag.name in tags for tag in song.tags)
        ]
    elif searchType == "only":
        filtered_songs = [
            song for song in songs if set(tag.name for tag in song.tags) == tags
        ]
    else:
        raise ValueError(f"Invalid searchType: {searchType}. Use {ListSearchValues}.")
    return filtered_songs


class HashableIDMixin(SQLModel):
    id: int | None = Field(None, primary_key=True, index=True, unique=True)

    @pydantic.field_validator("id", mode="before")
    @classmethod
    def string_to_int_id(cls, v):
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return int(uuid4())
        else:
            return v


# class TrackMetadata(HashableIDMixin, SQLModel, table=True):
class TrackMetadata(SQLModel, table=True):
    id: int | None = Field(None, primary_key=True, index=True, unique=True)
    path: PathLike | None = Field(sa_column=Column(String, primary_key=True))
    associated_song: Optional[Song] = Relationship(back_populates="associated_tracks")
    track_number: Optional[int] = None
    title: Optional[str] = None
    artists: Optional[str] = ""
    releases: list[str] = Relationship(link_model=TrackReleaseLink)
    duration: Optional[float] = None
    fingerprint: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tempo: Optional[float] = None
    brightness: Optional[float] = None
    mfcc_mean: Optional[list[float]] = Field(
        sa_column=Column(MutableList.as_mutable(JSON)), default_factory=list
    )
    key: Optional[str] = None
    energy: Optional[float] = None
    dynamic_range: Optional[float] = None
    zcr: Optional[float] = None
    valence: Optional[float] = None
    sample_rate: Optional[float] = None
    parsed_title: Optional[str] = None
    parsed_track: Optional[int] = None
    album: set[LocalAlbumMetadata] = Relationship(back_populates="tracks")

    def filter_attributes(
        self, include: set[str] | None = None, exclude: set[str] | None = None
    ) -> dict[str, TrackMetadataType]:
        """@brief Get a dict of the TrackMetadata attributes excluding specified fields.

        @param exclude Set of attribute names to exclude from the result.
        @return Dict of attribute names and values, excluding the specified fields.
        """
        included_fields = set(self.__fields__.keys()) if include is None else include
        excluded_fields = set() if exclude is None else exclude
        fields_to_include = included_fields - excluded_fields
        return {field: getattr(self, field) for field in fields_to_include}

    def __add__(
        self,
        other: object,
        conflict_strategy: TrackMetadataValueConflictStrategy = "self",
        list_merge_strategy: TrackMetadataListConflictStrategy = "merge",
        combine_fingerprints: TrackMetadataCombineFingerprintsStrategy = "raise",
    ) -> "TrackMetadata":
        if not isinstance(other, TrackMetadata):
            return NotImplemented

        if self.path != other.path:
            raise ValueError(
                f"Cannot merge TrackMetadata with different paths: {self.path} vs {other.path}"
            )

        if (
            self.fingerprint and other.fingerprint
        ) and self.fingerprint != other.fingerprint:
            raise ValueError(
                f"Cannot merge TrackMetadata with different fingerprints: {self.fingerprint} vs {other.fingerprint}"
            )

        matched_fields = ["path", "fingerprint", "created_at", "updated_at"]
        list_fields = ["artists", "tags", "albums", "releases"]
        attrs: dict[str, TrackMetadataType] = {}
        for field in self.__fields__:
            self_value = getattr(self, field)
            other_value = getattr(other, field)

            if field in matched_fields:
                # These fields must match exactly, so we can skip conflict resolution
                attrs[field] = self_value or other_value
                continue

            if field in list_fields:
                if field == "artists":
                    # Special case for artists string field
                    self_artists = (
                        [a.strip() for a in self_value.split(",")] if self_value else []
                    )
                    other_artists = (
                        [a.strip() for a in other_value.split(",")]
                        if other_value
                        else []
                    )
                    merged_artists = list(set(self_artists + other_artists))
                    attrs[field] = ", ".join(merged_artists)
                    continue
                # For list fields, we can merge them and remove duplicates
                # optionally we can raise an error if there is a conflict instead of merging
                # If self or other, treat like normal
                if list_merge_strategy == "merge" or list_merge_strategy == "update":
                    merged_list = list(set((self_value or []) + (other_value or [])))
                    attrs[field] = merged_list
                    continue

                elif list_merge_strategy == "raise":
                    raise ValueError(
                        f"List conflict for '{field}': '{self_value}' vs '{other_value}'"
                    )
                    continue

            if (
                self_value is not None
                and other_value is not None
                and self_value != other_value
            ):
                if conflict_strategy == "self" or conflict_strategy == "update":
                    print(
                        f"Conflict for '{field}': '{self_value}' vs '{other_value}' - keeping '{self_value}'"
                    )
                    attrs[field] = self_value
                elif conflict_strategy == "other":
                    print(
                        f"Conflict for '{field}': '{self_value}' vs '{other_value}' - keeping '{other_value}'"
                    )
                    attrs[field] = other_value
                elif conflict_strategy == "raise":
                    raise ValueError(
                        f"Conflict for '{field}': '{self_value}' vs '{other_value}'"
                    )
            else:
                attrs[field] = self_value if self_value is not None else other_value
        attrs["updated_at"] = (
            datetime.now()
        )  # Update the timestamp for the merged object
        return TrackMetadata(**attrs)


class TrackSongLink(SQLModel, table=True):
    track_id: int = Field(foreign_key="trackmetadata.id", primary_key=True)
    song_id: int = Field(foreign_key="song.id", primary_key=True)


class Song(HashableIDMixin, SQLModel, table=True):
    """Abstract representation of a song, which can be linked to multiple file paths and metadata sources."""

    # one-to-one with TrackMetadata, this is the primary track metadata for the song, used for display and editing
    track: "TrackMetadata" | None = Relationship(
        back_populates="associated_tracks",
        sa_relationship_kwargs={
            "uselist": False
        },  # TODO look up sa_relationship_kwargs
    )  # Does this update associated_tracks when track is updated?
    # one-to-many with TrackMetadata, songs could have multiple tracks
    associated_tracks: set[TrackMetadata] = Relationship(
        back_populates="associated_song", link_model=TrackSongLink
    )
    fingerprint: str = Field(
        default=None, unique=True
    )  # Can we have a song with no fingerprint?
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(
        default_factory=datetime.now
    )  # can we update this automatically?
    albums: set[LocalAlbumMetadata] = Relationship(
        back_populates="songs",
    )
    tags: set[Tag] = Relationship(link_model=SongTagLink)

    @property
    def duration(self) -> Optional[float]:
        if self.track and self.track.duration:
            return self.track.duration
        else:
            return None

    @property
    def releases(self) -> dict[str, set[str]]:
        release_types: dict[str, set[str]] = {}
        releases = set()
        for track in self.associated_tracks:
            releases.update(self.releases)

        release_types["release"] = releases
        albums = set()
        for album in self.albums:
            if album.title:
                albums.add(album.title)
        release_types["album"] = albums
        return release_types

    @property
    def paths(self) -> set[PathLike]:
        return {
            track.path for track in self.associated_tracks if track.path is not None
        }

    @property
    def path(self) -> Optional[PathLike]:
        if self.track and self.track.path:
            return self.track.path
        else:
            return None

    def track_info(self) -> None:
        print(f"Song ID: {self.id}")
        print(f"Fingerprint: {self.fingerprint[:10]}... (truncated)")
        if not self.track:
            print("No track metadata available")
            return
        print("Track Metadata:")
        for key, value in self.track.model_dump().items():
            if key in ["fingerprint", "id", "file_paths"]:
                continue
            print(f"  {key}: {value}")

    def query_acoustid(self, score_threshold: float | None) -> None:
        """@brief Query the AcoustID API for metadata based on the song's fingerprint and duration.
        Updates the song's metadata with the best matching result that meets the score threshold.
        """

        settings = get_settings()
        if score_threshold is None:
            score_threshold = settings.score_threshold

        if not self.fingerprint or not self.duration:
            raise ValueError(
                "Song must have a fingerprint and duration to query AcoustID."
            )
        results = AcoustIDLookupResults.trackmetadata_from_fingerprint_results(
            self.fingerprint, self.duration, score_threshold
        )
        if results:
            for idx, result in enumerate(results, start=1):
                print(f"Result {idx}:")
                for key, value in result.model_dump().items():
                    if key == "fingerprint":
                        print(f"  {key}: {value[:10]}... (truncated)")
                    else:
                        print(f"  {key}: {value}")
                print()


class LocalAlbumMetadata(HashableIDMixin, SQLModel, table=True):
    path: str = Field(unique=True)
    title: str
    artists: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tracks: set[TrackMetadata] = Relationship(back_populates="album")
    default_order: Optional[str] = None
    filename_metadata_pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    def find_track_by_path(self, path: PathLike) -> Optional[TrackMetadata]:
        for track in self.tracks:
            if track.path == path:
                return track
        return None

    @property
    def parser(self) -> SmartParser:
        if not hasattr(self, "_parser"):
            self._parser = SmartParser()
        return self._parser

    @property
    def track_paths(self) -> set[PathLike]:
        paths = set()
        for track in self.tracks:
            if track.path:
                paths.add(track.path)
        return paths

    def save(self) -> None:
        """@TODO get rid of this"""
        album_meta_path = Path(self.path) / "album_meta.json"
        try:
            album_meta_path.write_text(self.model_dump_json(indent=4))
        except TypeError:
            print(
                f"Error saving album metadata to {album_meta_path}. Ensure all fields are JSON serializable."
            )
            if album_meta_path.exists():
                album_meta_path.unlink()  # Remove the file if it was partially written

    def parse_song_filename(
        self: LocalAlbumMetadata, filename: PathLike
    ) -> TrackMetadata:
        if self.filename_metadata_pattern is None:
            raise ValueError("filename_metadata_pattern is not set for this album")
        parsed_data = self.parser.parse(self.filename_metadata_pattern, filename)
        print("Album parsed from filename")
        releases = [self.title] if self.title else []
        if not releases:
            album_from_filename = try_multiple_keys(parsed_data, "album", "release")
            if album_from_filename:
                releases.append(album_from_filename)
        print(releases)
        if parsed_data:
            track_metadata = TrackMetadata(
                path=filename,
                track_number=try_multiple_keys(parsed_data, "track", "trackno"),
                title=try_multiple_keys(parsed_data, "title"),
                artists=try_multiple_keys(
                    parsed_data, "artist", "artists", "artistname", "artistnames"
                ),
                releases=releases,
            )
            print("Parsed track metadata from filename:")
            print(track_metadata)
            print(track_metadata.releases)
            track_metadata.releases = releases
            print(track_metadata.releases)
            return track_metadata
        else:
            print(
                f"Could not parse filename '{filename}' with pattern '{self.filename_metadata_pattern}'"
            )
            return TrackMetadata(path=filename)


class Tag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    path: PathLike | None = Field(sa_column=Column(String))
    name: str = Field(
        default=None,
        sa_column=Column(String(collation="NOCASE"), unique=True),
        description="The name of the tag (case-insensitive unique)",
    )
    parent_tags: set["Tag"] = Relationship(
        back_populates="child_tags", link_model=ParentTagLink
    )
    child_tags: set["Tag"] = Relationship(
        back_populates="parent_tags", link_model=ParentTagLink
    )
    group: "TagGroup" = Relationship(back_populates="tags", link_model=GroupTagLink)
    songs: set[Song] = Relationship(back_populates="tags")

    def get_all_child_tags(
        self: "Tag", child_tags: set["Tag"] | None = None
    ) -> set["Tag"]:
        if child_tags is None:
            child_tags: set[Tag] = set()
        for child_tag in self.child_tags:
            child_tags.add(child_tag)
            child_tags.update(child_tag.get_all_child_tags(child_tags))
        return child_tags

    def get_all_parent_tags(
        self: "Tag", parent_tags: set["Tag"] | None = None
    ) -> set["Tag"]:
        if parent_tags is None:
            parent_tags: set[Tag] = set()
        for parent_tag in self.parent_tags:
            parent_tags.add(parent_tag)
            parent_tags.update(parent_tag.get_all_parent_tags(parent_tags))
        return parent_tags


class TagGroup(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    color: str = Field(default_factory=random_color)
    tags: set[Tag] = Relationship(back_populates="group", link_model=GroupTagLink)
