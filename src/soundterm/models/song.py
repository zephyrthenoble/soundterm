from sqlmodel import SQLModel, Field
from typing import Optional
import musicbrainzngs
from pprint import pprint
from uuid import uuid4, UUID
import json
from datetime import datetime
from soundterm.utils.filename_parser import SmartParser
from pathlib import Path
from os import PathLike

from soundterm.models.track import TrackMetadata
from acoustid import (
    fingerprint_file,
    FingerprintGenerationError,
    lookup,
)


filepath_to_song_cache: dict[PathLike, "Song"] = {}

fingerprint_to_song_cache: dict[str, "Song"] = {}

SCORE_THRESHOLD = 0.7
DEFAULT_TIMEOUT = 30
API_KEY = "iRDSOogTx3"  # Replace with your actual AcoustID API key


def use_musicbrainz() -> None:
    musicbrainzngs.set_useragent("SoundTerm", "0.1", "zephyrthenoble@gmail.com")
    username = "zephyrthenoble"
    password = "%sU^hN7)u!N=gaR"
    musicbrainzngs.auth(username, password)


parser = SmartParser()


# Common track number patterns at the beginning of filename
track_patterns: list[tuple[str, str]] = [
    (
        r"^(?P<artist>.+)\s+-\s+(?P<album>.+)\s+-\s+(?P<track>\d{1,3})\s+-\s+(?P<title>.+)$",
        "Artist - Album - 01 - Title",
    ),
    (
        r"^(?P<artist>.+)\s+(?P<album>.+)\s+(?P<track>\d{1,3})\s+[-._\s]*(?P<title>.+)$",
        "Artist Album 01 Title",
    ),
    (r"^Track\s*(?P<track>\d{1,3})\s*[-._\s]*(?P<title>.+)$", "Track 01 - Title"),
    (r"^(?P<track>\d{1,3})\s*[-._\s]+(?P<title>.+)$", "01 - Title"),
    (r"^(?P<track>\d{1,3})\s*\.?\s*(?P<title>.+)$", "01 Title"),
]


type UUIDType = str


class CollectionAlbumMetadata(SQLModel):
    id: str = Field(default_factory=uuid4, primary_key=True)
    path: str
    title: str
    artists: list[str] = Field(default_factory=list)
    songs: list[str] = Field(default_factory=list)
    filename_metadata_pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @staticmethod
    def from_file_path(file_path: PathLike) -> "CollectionAlbumMetadata":
        fpath = Path(file_path)
        album_name = fpath.parent.name
        album_meta_path = fpath.parent / "album_meta.json"
        if not album_meta_path.exists():
            print(f"No album metadata found for {album_name} at {album_meta_path}")
            print(
                f"Enter album name, or press enter to use folder name '{album_name}':"
            )
            album_name_input = input()
            if album_name_input.strip():
                album_name = album_name_input.strip()
            else:
                print(f"Using folder name '{album_name}' as album name.")

            print(
                "Enter comma separated list of artists for this album, or press enter to skip:"
            )
            artists = []
            artists_input = input()
            if artists_input.strip():
                artists = [artist.strip() for artist in artists_input.split(",")]
            print("Available track patterns:")
            for idx, (pattern, description) in enumerate(track_patterns, start=1):
                print(f"  {idx}. {description}: {pattern}")
            print(
                "Enter a number to select a track pattern, or enter a custom regex pattern with named groups (e.g. (?P<artist>.+) - (?P<album>.+) - (?P<track>\d{1,3}) - (?P<title>.+))"
            )
            filename_metadata_pattern = input()
            if filename_metadata_pattern.isdigit():
                pattern_idx = int(filename_metadata_pattern) - 1
                if 0 <= pattern_idx < len(track_patterns):
                    filename_metadata_pattern = track_patterns[pattern_idx][0]
                else:
                    raise ValueError("Invalid selection, defaulting to no pattern")

            else:
                # validate custom regex pattern by trying to parse the file name
                test_result = parser.parse(filename_metadata_pattern, fpath.name)
                if test_result is None:
                    print(
                        "Warning: The provided regex pattern did not match the file name. Please double-check your pattern and try again."
                    )
            album_meta = CollectionAlbumMetadata(
                id=str(uuid4()),
                title=album_name,
                artists=artists,
                songs=[],
                filename_metadata_pattern=filename_metadata_pattern,
                path=str(fpath.parent),
            )
            album_meta.save()

        else:
            with open(album_meta_path, "r") as f:
                album_meta_data = json.load(f)
                jsonstring = json.dumps(album_meta_data)
                print(f"Loaded album metadata for {album_name} from {album_meta_path}")
                album_meta = CollectionAlbumMetadata.model_validate_json(jsonstring)
        return album_meta

    def save(self) -> None:
        album_meta_path = Path(self.path) / "album_meta.json"
        try:
            album_meta_path.write_text(self.model_dump_json(indent=4))
        except TypeError:
            print(
                f"Error saving album metadata to {album_meta_path}. Ensure all fields are JSON serializable."
            )
            if album_meta_path.exists():
                album_meta_path.unlink()  # Remove the file if it was partially written

    def parse_song_filename(self, filename: PathLike) -> TrackMetadata:
        if self.filename_metadata_pattern is None:
            raise ValueError("filename_metadata_pattern is not set for this album")
        parsed_data = parser.parse(self.filename_metadata_pattern, filename)
        if parsed_data:
            return TrackMetadata(
                path=filename,
                track_number=parsed_data.get("track", parsed_data.get("trackno")),
                title=parsed_data.get("title"),
                album=parsed_data.get("album"),
            )
        else:
            print(
                f"Could not parse filename '{filename}' with pattern '{self.filename_metadata_pattern}'"
            )
            return TrackMetadata(path=filename)


class Song(SQLModel):
    id: Optional[UUID] = Field(default=None, primary_key=True)
    metadata: TrackMetadata
    fingerprint: str = Field(default=None, unique=True)
    file_paths: set[PathLike] = Field(sa_column_kwargs={"type_": "TEXT"})
    created_at: datetime = Field(default_factory=datetime.now)
    album_metadata: Optional[CollectionAlbumMetadata] = None

    @staticmethod
    def from_file_path(file_path: PathLike) -> "Song":
        # Placeholder implementation: In a real application, you would extract metadata from the file

        duration, fingerprint = fingerprint_file(file_path)

        song = None
        if fingerprint is None:
            raise FingerprintGenerationError(
                f"Could not generate fingerprint for file: {file_path}"
            )

        album_meta = CollectionAlbumMetadata.from_file_path(file_path)
        album_track_metadata = album_meta.parse_song_filename(file_path)
        album_track_metadata.duration = duration
        album_track_metadata.fingerprint = fingerprint

        extracted_track_metadata = TrackMetadata(path=file_path)

        extracted_track_metadata.extract_metadata()

        combined_track_metadata = extracted_track_metadata + album_track_metadata

        print(f"Combined track metadata: {combined_track_metadata}")

        if fingerprint in fingerprint_to_song_cache:
            song = fingerprint_to_song_cache[fingerprint]
            song.file_paths.add(file_path)
        else:
            recording_response: dict = lookup(
                API_KEY,
                fingerprint,
                duration,
                [  # "recordings",
                    "recordings",
                    "releasegroups",
                    "compress",
                ],
                DEFAULT_TIMEOUT,
            )
            pprint(recording_response)

            print("Existing Metadata:")
            print(file_path)
            for key, value in combined_track_metadata.model_dump().items():
                print(f"  {key}: {value}")
            count = 1
            count_to_recording = {}
            for result in recording_response.get("results", []):
                score = result.get("score", 0)
                if score < SCORE_THRESHOLD:
                    continue
                print(f"Score: {score}")
                for recording in result.get("recordings", []):
                    recording_id = recording.get("id")
                    count_to_recording[count] = recording
                    releases = recording.get("releasegroups", [])
                    release_titles = [release.get("title") for release in releases]
                    print(f"- Recording {count}: {recording_id}")
                    print(f"  - Title: {recording.get('title')}")
                    print(
                        f"  - Artists: {[artist.get('name') for artist in recording.get('artists', [])]}"
                    )
                    print(f"  - Releases: {release_titles}")
                    print()
                    count += 1
            print(
                "Please enter the recording number that best matches the song, or press enter to skip:"
            )
            recording_selection = input()
            if recording_selection.isdigit():
                selected_count = int(recording_selection)
                selected_recording = count_to_recording.get(selected_count)
            else:
                selected_recording = None

            artist_list = (
                [x["name"] for x in selected_recording.get("artists", [])]
                if selected_recording
                else []
            )
            if selected_recording:
                releases = selected_recording.get("releasegroups", [])
                release_titles = [release.get("title") for release in releases]
                found_track_metadata = TrackMetadata(
                    path=file_path,
                    title=selected_recording.get("title"),
                    artists=",".join(artist_list),
                    album=release_titles[0] if release_titles else None,
                )
                combined_track_metadata = combined_track_metadata + found_track_metadata
            print(combined_track_metadata)
            song = Song(
                id=uuid4(),
                file_paths={file_path},
                fingerprint=fingerprint,
                metadata=combined_track_metadata,
                album_metadata=album_meta,
            )
            if (
                song.album_metadata
                and song.id
                and str(song.id) not in song.album_metadata.songs
            ):
                song.album_metadata.songs.append(str(song.id))
                song.album_metadata.save()
        if song is None:
            raise ValueError(f"Could not create song from file: {file_path}")
        fingerprint_to_song_cache[fingerprint] = song
        filepath_to_song_cache[file_path] = song
        return song
