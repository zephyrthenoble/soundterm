from sqlmodel import SQLModel, Field
from typing import Optional, Literal
from datetime import datetime
from pathlib import Path
import pydantic
from uuid import uuid4
from os import PathLike

from soundterm.utils import try_multiple_keys
from soundterm.utils import SmartParser
from soundterm.settings import Settings


type Tag = str
type Fingerprint = str

type TrackMetadataType = (
    str | int | float | list[float] | list[str] | list[Tag] | datetime | None
)


# For simple scalar fields, we can choose to keep either self or other when there is a conflict, or raise an error
type TrackMetadataValueConflictStrategy = Literal["self", "other", "update", "raise"]

# merge: for list fields, combine unique values from both (e.g. union of artists or tags)
# update: for list fields, replace blank or None with non-empty values from the other
# raise: for list fields, if both have non-empty values that differ, raise an error instead of merging
type TrackMetadataListConflictStrategy = Literal["merge", "update", "raise"]

type TrackMetadataCombineFingerprintsStrategy = Literal["self", "other", "raise"]
type TrackMetadataCombinePathStrategy = Literal["self", "other", "raise"]


class HashableIDMixin(SQLModel):
    id: Optional[int] = Field(default_factory=lambda: int(uuid4()), primary_key=True)

    def __hash__(self):
        return self.id

    def __eq__(self, other):
        if isinstance(other, HashableIDMixin):
            return self.id == other.id
        return False

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


class Song(HashableIDMixin, SQLModel):
    # id: Optional[UUID] = Field(default=None, primary_key=True)
    track_metadata: "TrackMetadata"
    fingerprint: str = Field(default=None, unique=True)
    file_paths: set[PathLike] = Field(sa_column_kwargs={"type_": "TEXT"})
    created_at: datetime = Field(default_factory=datetime.now)
    album_metadata_id: Optional[int] = None

    _selected_path = None

    @property
    def path(self) -> Optional[PathLike]:
        if self.file_paths:
            if self._selected_path and self._selected_path in self.file_paths:
                return self._selected_path
            else:
                return next(iter(self.file_paths))
        return None

    @path.setter
    def path(self, value: PathLike) -> None:
        if value in self.file_paths:
            self._selected_path = value
        else:
            raise ValueError(
                f"Path {value} is not in the set of file paths for this song."
            )

    def pretty_print(self) -> None:
        print(f"Song ID: {self.id}")
        print(f"File Paths: {self.file_paths}")
        print(f"Fingerprint: {self.fingerprint[:10]}... (truncated)")
        print("Track Metadata:")
        for key, value in self.track_metadata.model_dump().items():
            if key in ["fingerprint", "id", "file_paths"]:
                continue
            print(f"  {key}: {value}")

    def query_acoustid(self, score_threshold: float | None) -> None:
        """@brief Query the AcoustID API for metadata based on the song's fingerprint and duration.
        Updates the song's metadata with the best matching result that meets the score threshold.
        """
        from soundterm.models import AcoustIDLookupResults

        settings = Settings()  # type: ignore
        if score_threshold is None:
            score_threshold = settings.score_threshold

        if not self.fingerprint or not self.track_metadata.duration:
            raise ValueError(
                "Song must have a fingerprint and duration to query AcoustID."
            )
        results = AcoustIDLookupResults.trackmetadata_from_fingerprint_results(
            self.fingerprint, self.track_metadata.duration, score_threshold
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


class CollectionAlbumMetadata(HashableIDMixin, SQLModel):
    # id: str = Field(default_factory=uuid4, primary_key=True)
    path: str
    title: str
    artists: list[str] = Field(default_factory=list)
    songs: set["Song"] = Field(default_factory=set)
    filename_metadata_pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    default_order: str | None = None

    @property
    def parser(self) -> SmartParser:
        if not hasattr(self, "_parser"):
            self._parser = SmartParser()
        return self._parser

    @property
    def song_paths(self) -> set[PathLike]:
        paths = set()
        for song in self.songs:
            paths.update(song.file_paths)
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
        self: "CollectionAlbumMetadata", filename: PathLike
    ) -> "TrackMetadata":
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


class TrackMetadata(SQLModel):
    path: PathLike | None = None
    track_number: Optional[int] = None
    title: Optional[str] = None
    artists: Optional[str] = ""
    releases: list[str] = Field(default_factory=list, alias="albums")
    tags: list[Tag] = Field(default_factory=list)
    duration: Optional[float] = None
    fingerprint: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tempo: Optional[float] = None
    brightness: Optional[float] = None
    mfcc_mean: Optional[list[float]] = None
    key: Optional[str] = None
    energy: Optional[float] = None
    dynamic_range: Optional[float] = None
    zcr: Optional[float] = None
    valence: Optional[float] = None
    sample_rate: Optional[int | float] = None
    parsed_title: Optional[str] = None
    parsed_track: Optional[int] = None

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
