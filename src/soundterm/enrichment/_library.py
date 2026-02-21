import json
from pathlib import Path
from os import PathLike
from pprint import pprint


from typing import Optional
from acoustid import fingerprint_file, FingerprintGenerationError

from pydantic import BaseModel, Field, ValidationError, DirectoryPath

from soundterm.settings import Settings
from soundterm.models import TrackMetadata, Song, CollectionAlbumMetadata
from soundterm.utils import SmartParser
from soundterm.utils import is_audio_file_valid_probe
from soundterm.enrichment import TrackAnalyzer

fingerprint_to_song_cache: dict[str, "Song"] = {}
filepath_to_albums: dict[Path, "CollectionAlbumMetadata"] = {}
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


settings = Settings()  # type: ignore


class LibraryManager(BaseModel):
    path: DirectoryPath = Field(default=settings.music_dir)
    save_path: Optional[Path] = Field(
        default=Path(settings.database).parent / "library_data.json"
    )
    albums: set[CollectionAlbumMetadata] = Field(default_factory=set)
    songs: set[Song] = Field(default_factory=set)

    def save(self):
        if self.save_path is None:
            raise ValueError("Save path is not set for LibraryManager.")
        for fingerprint, song in fingerprint_to_song_cache.items():
            if song not in self.songs:
                self.songs.add(song)
        for album_meta in filepath_to_albums.values():
            if album_meta not in self.albums:
                self.albums.add(album_meta)
        model = json.loads(self.model_dump_json())
        data = {
            "model": model,
            "fingerprint_to_song_cache": {
                k: json.loads(v.model_dump_json())
                for k, v in fingerprint_to_song_cache.items()
            },
            "filepath_to_albums": {
                str(k): json.loads(v.model_dump_json())
                for k, v in filepath_to_albums.items()
            },
        }
        try:
            with open(self.save_path, "w") as f:
                json.dump(data, f, indent=4)
            print(f"Library saved to {self.save_path}.")
        except TypeError as e:
            print(f"Error serializing library data to JSON: {e}")
            if self.save_path.exists():
                print(f"Removing corrupted save file at {self.save_path}.")
                self.save_path.unlink()
        except Exception as e:
            print(f"Error saving library to {self.save_path}: {e}")

    def load(self):
        if self.save_path is None:
            raise ValueError("Save path is not set for LibraryManager.")
        if not self.save_path.exists():
            print(
                f"No save file found at {self.save_path}. Starting with empty library."
            )
            return
        print(f"Loading library from {self.save_path}...")
        try:
            with open(self.save_path, "r") as f:
                data = json.load(f)
                print(data)
                model_data = data.get("model", {})
                self.path = model_data.get("path", self.path)
                global fingerprint_to_song_cache
                global filepath_to_albums
                fingerprint_to_song_cache = {
                    k: Song.model_validate(v)
                    for k, v in data.get("fingerprint_to_song_cache", {}).items()
                }
                filepath_to_albums = {
                    Path(k): CollectionAlbumMetadata.model_validate(v)
                    for k, v in data.get("filepath_to_albums", {}).items()
                }
                print(f"Library loaded from {self.save_path}.")
        except Exception as e:
            print(f"Error loading library from {self.save_path}: {e}")
            input("Press enter to continue with empty library...")
            return
        print(f"Loaded {len(fingerprint_to_song_cache)} songs in fingerprint cache.")

    # after init, resolve the path to an absolute path and validate it exists
    def model_post_init(self, __context: object) -> None:
        self.path = Path(self.path).resolve()
        if not self.path.exists():
            raise ValueError(f"Music directory {self.path} does not exist.")
        if not self.path.is_dir():
            raise ValueError(f"Music directory {self.path} is not a directory.")
        print(f"Initialized LibraryManager with path: {self.path}")

    def process_song(self, file_path: PathLike) -> Optional["Song"]:
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
        album_meta = self.process_album(file_path, fingerprint_to_song_cache)
        if file_path in album_meta.song_paths:
            print(
                f"Song for {file_path} already exists in album metadata. Using cached version."
            )
            next_song = next(
                song for song in album_meta.songs if file_path in song.file_paths
            )
            self.songs.add(next_song)
            return next_song

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

        trackanalyzer = TrackAnalyzer(path=file_path)
        trackanalyzer.analyze_song()
        trackanalyzer.print_all_metadata()

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
        print(f"Combined track metadata: {combined_track_metadata}")
        if fingerprint in fingerprint_to_song_cache:
            new_song = fingerprint_to_song_cache[fingerprint]
            new_song.file_paths.add(file_path)
        else:
            new_song = Song(
                file_paths={file_path},
                fingerprint=fingerprint,
                track_metadata=combined_track_metadata,
                album_metadata_id=album_meta.id,
            )
            new_song.pretty_print()
            if (
                album_meta
                and new_song.id
                and str(new_song.id) not in [str(song.id) for song in album_meta.songs]
            ):
                album_meta.songs.add(new_song)
                album_meta.save()
        if new_song is None:
            raise ValueError(f"Could not create song from file: {file_path}")
        fingerprint_to_song_cache[fingerprint] = new_song
        self.songs.add(new_song)
        return new_song

    def process_album(
        self,
        song_file_path: PathLike,
        fingerprint_to_song_cache: dict[str, "Song"],
        force: bool = False,
        continue_on_success: bool = False,
    ) -> "CollectionAlbumMetadata":

        fpath = Path(song_file_path)
        album_file_path = fpath.parent
        album_name = album_file_path.name
        album_meta_path = album_file_path / "album_meta.json"
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
            album_meta = CollectionAlbumMetadata(
                title=album_name,
                artists=artists,
                songs=[],
                filename_metadata_pattern=filename_metadata_pattern,
                path=str(album_file_path),
                parser=parser,
            )
            album_meta.save()
            filepath_to_albums[album_file_path] = album_meta

        else:
            if filepath_to_albums.get(album_file_path) and not force:
                print(
                    f"Album metadata for {album_name} already loaded in memory. Using cached version."
                )
                album_meta = filepath_to_albums[album_file_path]
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
                    except (json.JSONDecodeError, ValidationError) as e:
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
                        album_meta = self.process_album(
                            song_file_path,
                            fingerprint_to_song_cache=fingerprint_to_song_cache,
                            force=True,
                        )

        self.albums.add(album_meta)
        return album_meta
