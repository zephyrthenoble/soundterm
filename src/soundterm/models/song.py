import pydantic
import ffmpeg
import os
from sqlmodel import SQLModel, Field
from typing import Optional
import musicbrainzngs
from uuid import uuid4, UUID
import json
from datetime import datetime
from soundterm.utils.filename_parser import SmartParser
from pathlib import Path
from os import PathLike
from pprint import pprint

from soundterm.models.track import TrackMetadata
from soundterm.settings import Settings
from acoustid import (
    fingerprint_file,
    FingerprintGenerationError,
)


def try_multiple_keys(data: dict, *keys):
    for key in keys:
        if key in data:
            return data[key]
    return None


filepath_to_albums = {}

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
    (
        r"^(?P<track>\d{1,3})\s*\.?\s*(?P<artist>.+)\s*-\s*(?P<title>.+)$",
        "01 Artist - Title",
    ),
]


type UUIDType = str


class CollectionAlbumMetadata(SQLModel):
    id: str = Field(default_factory=uuid4, primary_key=True)
    path: str
    title: str
    artists: list[str] = Field(default_factory=list)
    songs: list["Song"] = Field(default_factory=list)
    filename_metadata_pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    default_order: str | None = None

    @property
    def song_paths(self) -> set[PathLike]:
        paths = set()
        for song in self.songs:
            paths.update(song.file_paths)
        return paths

    @staticmethod
    def from_file_path(
        file_path: PathLike, force: bool = False, continue_on_success: bool = False
    ) -> "CollectionAlbumMetadata":
        fpath = Path(file_path)
        album_name = fpath.parent.name
        album_meta_path = fpath.parent / "album_meta.json"
        if not album_meta_path.exists() or force:
            if force:
                print(
                    f"Forcing update of album metadata for {album_name} at {album_meta_path}"
                )
            else:
                print(f"No album metadata found for {album_name} at {album_meta_path}")
            album_name_input = input(
                f"Enter album name, or press enter to use folder name '{album_name}': "
            )
            if album_name_input.strip():
                album_name = album_name_input.strip()
            else:
                print(f"Using folder name '{album_name}' as album name.")

            artists_input = input(
                "Enter comma separated list of artists for this album, or press enter to skip: "
            )
            artists = []
            if artists_input.strip():
                artists = [artist.strip() for artist in artists_input.split(",")]
            while True:
                print("Available track patterns:")
                for idx, (pattern, description) in enumerate(track_patterns, start=1):
                    print(f"  {idx}. {description}: {pattern}")

                print(f"Current song: {fpath.name}")
                filename_metadata_pattern = input(
                    "Enter a number to select a track pattern, or enter a custom regex pattern with named groups\n (e.g. (?P<artist>.+) - (?P<album>.+) - (?P<track>\\d{1,3}) - (?P<title>.+))\n"
                )
                if filename_metadata_pattern.isdigit():
                    pattern_idx = int(filename_metadata_pattern) - 1
                    if 0 <= pattern_idx < len(track_patterns):
                        filename_metadata_pattern = track_patterns[pattern_idx][0]
                    else:
                        raise ValueError("Invalid selection, defaulting to no pattern")

                # validate custom regex pattern by trying to parse the file name
                test_result = parser.parse(filename_metadata_pattern, fpath.name)
                print(
                    f"Test parsing filename '{fpath.name}' with pattern '{filename_metadata_pattern}':"
                )
                pprint(test_result)
                if test_result is None:
                    print(
                        "Warning: The provided regex pattern did not match the file name. Please double-check your pattern and try again."
                    )
                    to_continue = input(
                        "Press enter to continue anyway, 'q' to quit, or another key to re-enter the pattern: "
                    )
                    if to_continue.strip().lower() == "q":
                        raise ValueError("Aborting due to invalid regex pattern.")
                    elif to_continue.strip():
                        continue
                    else:
                        print(
                            "Continuing with invalid regex pattern. This may cause issues with metadata extraction."
                        )
                        break
                else:
                    if continue_on_success:
                        break
                    else:
                        to_continue = input(
                            "Pattern looks good. Press enter to continue, 'q' to quit, or another key to re-enter the pattern: "
                        )
                        if to_continue.strip().lower() == "q":
                            raise ValueError("Aborting by user request.")
                        elif to_continue.strip():
                            continue
                        else:
                            print("Continuing with selected regex pattern.")
                            break
            album_meta = CollectionAlbumMetadata(
                id=str(uuid4()),
                title=album_name,
                artists=artists,
                songs=[],
                filename_metadata_pattern=filename_metadata_pattern,
                path=str(fpath.parent),
            )
            album_meta.save()
            filepath_to_albums[fpath.parent] = album_meta

        else:
            if filepath_to_albums.get(fpath.parent) and not force:
                print(
                    f"Album metadata for {album_name} already loaded in memory. Using cached version."
                )
                album_meta = filepath_to_albums[fpath.parent]
            else:
                with open(album_meta_path, "r") as f:
                    try:
                        album_meta_data = json.load(f)
                        jsonstring = json.dumps(album_meta_data)
                        print(
                            f"Loaded album metadata for {album_name} from {album_meta_path}"
                        )
                        album_meta = CollectionAlbumMetadata.model_validate_json(
                            jsonstring
                        )
                        for song in album_meta.songs:
                            if (
                                song.fingerprint
                                and song.fingerprint not in fingerprint_to_song_cache
                            ):
                                fingerprint_to_song_cache[song.fingerprint] = song
                    except (json.JSONDecodeError, pydantic.ValidationError) as e:
                        if isinstance(e, json.JSONDecodeError):
                            print(
                                f"Error decoding JSON from {album_meta_path}. The file may be corrupted. Please fix or delete the file and try again."
                            )
                        else:
                            print(
                                f"Error validating album metadata from {album_meta_path}: {e}. The file may be corrupted or in an old format. Please fix or delete the file and try again."
                            )
                        retry_input = input(
                            "Press enter to manually enter data, 'd' to delete the file and enter manually, or 'q' to quit: "
                        )
                        retry_case = retry_input.strip().lower()
                        if retry_case == "q":
                            raise ValueError("Aborting due to invalid album metadata.")
                        if retry_case == "d":
                            if album_meta_path.exists():
                                album_meta_path.unlink()  # Delete the file
                                print(
                                    "File deleted. Continuing with manual data entry."
                                )
                            else:
                                print(
                                    "File does not exist. Continuing with manual data entry."
                                )
                        print("Continuing with manual data entry.")
                        album_meta = CollectionAlbumMetadata.from_file_path(
                            file_path, force=True
                        )

        return album_meta

    def save(self) -> None:
        for song in self.songs:
            if song.fingerprint and song.fingerprint not in fingerprint_to_song_cache:
                fingerprint_to_song_cache[song.fingerprint] = song
        filepath_to_albums[Path(self.path)] = self
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
    ) -> TrackMetadata:
        if self.filename_metadata_pattern is None:
            raise ValueError("filename_metadata_pattern is not set for this album")
        parsed_data = parser.parse(self.filename_metadata_pattern, filename)
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


def is_audio_file_valid_probe(filename: PathLike) -> bool:
    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return False

    try:
        # Run ffprobe to get stream information
        # Use select_streams='a' to only look for audio streams
        probe_result = ffmpeg.probe(filename, select_streams="a")

        # If streams are found, it's likely a valid audio file
        if probe_result["streams"]:
            print(f"'{filename}' is a valid audio file.")
            return True
        else:
            print(f"'{filename}' does not contain an audio stream.")
            return False
    except ffmpeg.Error as e:
        print(f"'{filename}' is invalid or corrupted.")
        # FFmpeg error output is typically in stderr
        print(e.stderr.decode("utf8"))
        return False


def track_lookup(apikey, track_id: str, meta: list[str] | None = None, timeout=None):
    """Look up a fingerprint with the Acoustid Web service. Returns the
    Python object reflecting the response JSON data. To get more data
    back, ``meta`` can be a list of keywords from this list: recordings,
    recordingids, releases, releaseids, releasegroups, releasegroupids,
    tracks, compress, usermeta, sources.
    """
    params = {
        "format": "json",
        "client": apikey,
        "trackid": track_id,
        "meta": meta,
    }
    from acoustid import _api_request, _get_lookup_url

    return _api_request(_get_lookup_url(), params, timeout)


class Song(SQLModel):
    id: Optional[UUID] = Field(default=None, primary_key=True)
    track_metadata: TrackMetadata
    fingerprint: str = Field(default=None, unique=True)
    file_paths: set[PathLike] = Field(sa_column_kwargs={"type_": "TEXT"})
    created_at: datetime = Field(default_factory=datetime.now)
    album_metadata_id: Optional[str] = None

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

    @staticmethod
    def from_file_path(file_path: PathLike) -> Optional["Song"]:

        song: Optional["Song"] = None

        # Check if we've already processed this file path directory before and have album metadata cached
        album_meta = CollectionAlbumMetadata.from_file_path(file_path)
        if file_path in album_meta.song_paths:
            print(
                f"Song for {file_path} already exists in album metadata. Using cached version."
            )
            return next(
                song for song in album_meta.songs if file_path in song.file_paths
            )

        # validate file exists and is not empty before trying to generate fingerprint
        fpath = Path(file_path)
        file_size = fpath.stat().st_size
        if file_size == 0:
            print(f"File {file_path} is empty. Skipping empty files.")
            return None

        # attempt to generate fingerprint and duration using pyacoustid
        try:
            print(f"Generating fingerprint for {file_path}...")
            duration, fingerprint = fingerprint_file(file_path, force_fpcalc=True)
            if fingerprint is None:
                raise FingerprintGenerationError(
                    f"Could not generate fingerprint for file: {file_path}"
                )
            if duration is None:
                raise FingerprintGenerationError(
                    f"Could not determine duration for file: {file_path}"
                )
        except FingerprintGenerationError as e:
            # if fingerprinting fails, check if the file is a valid audio file using ffmpeg
            print(f"Error generating fingerprint for {file_path}: {e}")
            is_valid = is_audio_file_valid_probe(file_path)
            if not is_valid:
                print(f"File {file_path} is invalid. Skipping.")
                return None
            else:
                # if the file appears to be valid but fingerprint generation fails, this may indicate an issue with the fingerprinting process or an edge case with the file
                print(
                    f"File {file_path} appears to be a valid audio file. Please investigate the fingerprint generation"
                )
                raise

        track_metadata = TrackMetadata(
            path=file_path, duration=duration, fingerprint=fingerprint
        )
        album_track_metadata = album_meta.parse_song_filename(file_path)

        extracted_track_metadata = TrackMetadata(path=file_path)

        extracted_track_metadata.extract_metadata()

        if album_meta.default_order:
            selection = album_meta.default_order
        else:
            print(
                f"Album track metadata: {album_track_metadata.filter_attributes({'releases', 'artists', 'title', 'track_number'})}"
            )
            print(
                f"Extracted track metadata: {extracted_track_metadata.filter_attributes({'releases', 'artists', 'title', 'track_number'})}"
            )
            selection = (
                input(
                    f"Select default metadata source priority for {file_path}\n\t* a for just album\n\t* e for just extracted\n\t* ae for album then extracted\n\t* ea for extracted then album: (default: ae)\n"
                )
                .strip()
                .lower()
            )
        if selection == "a":
            combined_track_metadata = album_track_metadata
        elif selection == "e":
            combined_track_metadata = extracted_track_metadata
        elif selection == "ae":
            combined_track_metadata = album_track_metadata + extracted_track_metadata
        elif selection == "ea":
            combined_track_metadata = extracted_track_metadata + album_track_metadata
        else:
            print("Invalid selection, defaulting to album then extracted metadata")
            combined_track_metadata = album_track_metadata + extracted_track_metadata
            selection = "ae"

        combined_track_metadata = track_metadata + combined_track_metadata
        if not album_meta.default_order:
            set_as_default = (
                input(
                    f"Use selection '{selection}' as default for this album? (y/n, default: n): "
                )
                .strip()
                .lower()
            )
            if set_as_default == "y":
                album_meta.default_order = selection
                album_meta.save()

        print(file_path)
        settings = Settings()  # type: ignore
        if settings.analyze_song:
            combined_track_metadata.analyze_song()
        print(f"Combined track metadata: {combined_track_metadata}")
        if fingerprint in fingerprint_to_song_cache:
            song = fingerprint_to_song_cache[fingerprint]
            song.file_paths.add(file_path)
        else:
            song = Song(
                id=uuid4(),
                file_paths={file_path},
                fingerprint=fingerprint,
                track_metadata=combined_track_metadata,
                album_metadata_id=album_meta.id,
            )
            song.pretty_print()
            if (
                album_meta
                and song.id
                and str(song.id) not in [str(song.id) for song in album_meta.songs]
            ):
                album_meta.songs.append(song)
                album_meta.save()
        if song is None:
            raise ValueError(f"Could not create song from file: {file_path}")
        fingerprint_to_song_cache[fingerprint] = song
        filepath_to_song_cache[file_path] = song
        return song

    def pretty_print(self) -> None:
        print(f"Song ID: {self.id}")
        print(f"File Paths: {self.file_paths}")
        print(f"Fingerprint: {self.fingerprint[:10]}... (truncated)")
        print("Track Metadata:")
        for key, value in self.track_metadata.model_dump().items():
            if key in ["fingerprint", "id", "file_paths"]:
                continue
            print(f"  {key}: {value}")

    def query_acoustid(self, score_threshold: float = SCORE_THRESHOLD) -> None:
        """@brief Query the AcoustID API for metadata based on the song's fingerprint and duration.
        Updates the song's metadata with the best matching result that meets the score threshold.
        """
        from soundterm.models.acoustid import AcoustIDLookupResults

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
