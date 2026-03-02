from __future__ import annotations
from pathlib import Path
from os import PathLike
from pprint import pprint
from typing import Optional
from traceback import format_exc


from sqlmodel import col, select, Session
from acoustid import fingerprint_file, FingerprintGenerationError
from pydantic import BaseModel, Field, DirectoryPath, ConfigDict
from sqlalchemy.exc import InvalidRequestError

from soundterm.settings import get_settings
from soundterm.models import TrackMetadata, Song, LocalAlbumMetadata
from soundterm.utils import SmartParser, is_audio_file_valid_probe
from soundterm.utils.database import commit_if_dirty

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


settings = get_settings()


class LibraryManagerError(Exception):
    pass


class LibraryErrorModel(BaseModel):
    file_path: Path
    error_message: str


class ModelBase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


class LibraryManager(ModelBase):
    path: DirectoryPath = Field(default=settings.music_dir)
    errors: list[LibraryErrorModel] = Field(default_factory=list)
    session: Session
    scanned: dict[str, Song] = Field(default_factory=dict)
    strict_mode: bool = Field(default=True)

    # after init, resolve the path to an absolute path and validate it exists
    def model_post_init(self, __context: object) -> None:
        self.path = Path(self.path).resolve()
        if not self.path.exists():
            raise ValueError(f"Music directory {self.path} does not exist.")
        if not self.path.is_dir():
            raise ValueError(f"Music directory {self.path} is not a directory.")
        print(f"Initialized LibraryManager with path: {self.path}")

    def scan_music_directory(self) -> None:
        for song_path_str in self.path.glob("**/*.mp3"):
            song_path = Path(song_path_str)
            print(f"Processing {song_path}...")
            try:
                song = self.process_song(song_path)
                if song:
                    self.scanned[str(song_path)] = song
                    if settings.debug:
                        print()
                        print("Song data:")
                        for key, value in song.model_dump().items():
                            if key == "fingerprint":
                                print(f"  {key}: {value[:10]}... (truncated)")
                                continue
                            if "metadata" in key and isinstance(value, dict):
                                print(f"  {key}:")
                                for meta_key, meta_value in value.items():
                                    if meta_key == "fingerprint":
                                        print(
                                            f"    {meta_key}: {meta_value[:10]}... (truncated)"
                                        )
                                        continue
                                    print(f"    {meta_key}: {meta_value}")
                            else:
                                print(f"  {key}: {value}")
                    else:
                        raise LibraryManagerError(
                            f"Failed to process {song_path}. No song data returned."
                        )
            except InvalidRequestError as e:
                raise InvalidRequestError from e
            except Exception as e:
                print(f"Error processing {song_path}: {e}")
                # add to error set to skip in future runs
                library_error = LibraryErrorModel(
                    file_path=song_path, error_message=str(e) + "\n" + format_exc()
                )
                self.errors.append(library_error)
                if self.strict_mode:
                    raise LibraryManagerError(
                        f"Error processing {song_path}: {e}. Aborting due to strict mode."
                    ) from e

        for error in self.errors:
            print(f"Error processing {error.file_path}: {error.error_message}")

        for scanned_path, song in self.scanned.items():
            print(f"Successfully processed {scanned_path}: {song}")

        print(f"Finished processing {self.path}.")

    def process_song(self, file_path: PathLike) -> Optional["Song"]:

        # ensure the file path is within the music directory
        fpath = Path(file_path).resolve()
        if not fpath.is_relative_to(self.path):
            raise ValueError(
                f"File path {file_path} is not within the music directory {self.path}"
            )
        # validate file exists and is not empty before trying to generate fingerprint
        file_size = fpath.stat().st_size
        if file_size == 0:
            print(f"File {file_path} is empty. Skipping empty files.")
            return None

        new_song: Optional["Song"] = None

        # Check if we've already processed this file path directory before and have album metadata cached

        statement = select(LocalAlbumMetadata).where(
            col(LocalAlbumMetadata.path) == str(fpath.parent)
        )
        album_meta = self.session.exec(statement).first()
        if not album_meta:
            album_meta = self.process_album(file_path, self.session)

        commit_if_dirty(self.session, album_meta)

        found_track = album_meta.find_track_by_path(file_path)
        if found_track:
            print(
                f"Song for {file_path} already exists in album metadata. Using cached version."
            )
            return found_track.associated_song

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

        base_track_metadata = TrackMetadata(
            path=file_path, duration=duration, fingerprint=fingerprint
        )
        album_track_metadata = album_meta.parse_song_filename(file_path)

        extracted_track_metadata = TrackMetadata(path=file_path)

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

        combined_track_metadata = base_track_metadata + combined_track_metadata
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

        print(file_path)
        print(f"Combined track metadata: {combined_track_metadata}")
        commit_if_dirty(self.session, combined_track_metadata)
        commit_if_dirty(self.session, album_meta)

        new_song = Song(
            fingerprint=fingerprint,
            track=combined_track_metadata,
            albums=set([album_meta]),
        )
        return new_song

    def process_album(
        self,
        track_file_path: PathLike,
        session: Session,
        album_meta: Optional[LocalAlbumMetadata] = None,
        force: bool = False,
        continue_on_success: bool = False,
    ) -> LocalAlbumMetadata:

        fpath = Path(track_file_path)
        album_file_path = fpath.parent
        album_name = album_file_path.name
        if not album_meta or force:
            if force:
                print(
                    f"Forcing update of album metadata for {album_name} at {album_file_path}"
                )
            else:
                print(f"No album metadata found for {album_name} at {album_file_path}")
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

                parser = SmartParser()
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
            album_meta = LocalAlbumMetadata(
                title=album_name,
                artists=artists,
                songs=[],
                filename_metadata_pattern=filename_metadata_pattern,
                path=str(album_file_path),
                parser=parser,
            )

        return album_meta
