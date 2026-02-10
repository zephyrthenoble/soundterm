from sqlmodel import SQLModel, Field
from typing import Optional
import musicbrainzngs
from pprint import pprint
from uuid import uuid4
import json
from datetime import datetime
from soundterm.utils.filename_parser import SmartParser
from pathlib import Path

from soundterm.models.track import TrackMetadata
from acoustid import (
    fingerprint_file,
    FingerprintGenerationError,
    lookup,
)


filepath_to_song_cache: dict[str, "Song"] = {}

fingerprint_to_song_cache: dict[str, "Song"] = {}

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


class Album(SQLModel):
    id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    songs: list["Song"] = Field(default_factory=list)
    filename_metadata_pattern: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @staticmethod
    def from_file_path(file_path: str) -> "Album":
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
            album_meta = Album(
                id=str(uuid4()),
                title=album_name,
                artists=artists,
                songs=[],
                filename_metadata_pattern=filename_metadata_pattern,
            )
            with open(album_meta_path, "w") as f:
                json.dump(album_meta.model_dump(), f, indent=4)

        else:
            with open(album_meta_path, "r") as f:
                album_meta_data = json.load(f)
                album_meta = Album.model_validate_json(json.dumps(album_meta_data))
        return album_meta

    def parse_song_filename(self, filename: str) -> TrackMetadata:
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
    id: Optional[int] = Field(default=None, primary_key=True)
    fingerprint: str = Field(default=None, unique=True)
    file_paths: set[str] = Field(sa_column_kwargs={"type_": "TEXT"})
    title: str
    duration: float
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @staticmethod
    def from_file_path(file_path: str) -> "Song":
        # Placeholder implementation: In a real application, you would extract metadata from the file

        duration, fingerprint = fingerprint_file(file_path)
        fpath = Path(file_path)

        song = None
        if fingerprint is None:
            raise FingerprintGenerationError(
                f"Could not generate fingerprint for file: {file_path}"
            )

        album_meta = Album.from_file_path(file_path)
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
            id_to_recording = {}
            if recording_response["status"] == "ok" and recording_response["results"]:
                from acoustid import parse_lookup_result

                for score, _id, title, artist_names in parse_lookup_result(
                    recording_response
                ):
                    print(
                        f"Score: {score}, ID: {_id}, Title: {title}, Artists: {artist_names}"
                    )
                    print(f"File name: {fpath.stem}, File suffix: {fpath.suffix}")
                    # compare title and artist names to file name to see if they match
                    if fpath.stem.lower() in title.lower():
                        print("Title matches file name!")
                    if any(
                        artist_name.lower() in fpath.stem.lower()
                        for artist_name in artist_names
                    ):
                        print("Artist name matches file name!")
                    id_to_recording[_id] = {
                        "title": title,
                        "artists": [artist_names],
                        "score": score,
                        "id": _id,
                        "title_match": combined_track_metadata.compare_title(title),
                    }
                id_to_release_group = {}
                results = recording_response["results"]
                for result in results:
                    for recording in result.get("recordings", []):
                        for release_group in recording.get("releasegroups", []):
                            release_group_id = release_group["id"]
                            if release_group_id not in id_to_release_group:
                                id_to_release_group[release_group_id] = release_group
                            id_to_recording[recording["id"]]["release_group"] = (
                                release_group
                            )

                if len(id_to_recording) > 1:
                    print("Multiple recordings found")
                    # sort by score
                    sorted_recordings = sorted(
                        id_to_recording.values(), key=lambda x: x["score"], reverse=True
                    )
                    SCORE_THRESHOLD = 0.7
                    found_recordings = []
                    for recording in sorted_recordings:
                        if recording["score"] < SCORE_THRESHOLD:
                            print(
                                f"Low score ({recording['score']}) for recording {recording['id']}, skipping detailed comparison."
                            )
                            break
                        if recording["title_match"]:
                            found_recordings.append(recording)

                    if len(found_recordings) == 1:
                        found_recording = found_recordings[0]
                    elif len(found_recordings) > 1:
                        print(
                            "Warning: Multiple recordings have title matches. This may indicate an issue with the metadata or multiple versions of the same song."
                        )

                        ### Test release group metadata to see if it can help us narrow down the results further
                        # If there are multiple found recordings, we can try to use the release group information to further narrow down the results
                        for (
                            release_group_id,
                            release_group,
                        ) in id_to_release_group.items():
                            print(f"Release Group ID: {release_group_id}")
                            print(f"Title: {release_group.get('title')}")
                            print(
                                f"Primary Type: {release_group.get('primary_type')}, Secondary Types: {release_group.get('secondary_types')}"
                            )
                            print(
                                f"Artists: {[artist['name'] for artist in release_group.get('artists', [])]}"
                            )
                            if release_group.get("primary_type") == "Album":
                                album_title = release_group.get("title", "").lower()
                                if album_title and album_title in fpath.stem.lower():
                                    print(
                                        f"Album title '{album_title}' matches file name, selecting recording with release group '{release_group.get('title')}'"
                                    )
                                    found_recordings = [
                                        rec
                                        for rec in found_recordings
                                        if rec.get("release_group", {}).get("id")
                                        == release_group_id
                                    ]
                                    break

                    if len(found_recordings) == 1:
                        found_recording = found_recordings[0]
                    elif len(found_recordings) > 1:
                        print(
                            "Warning: Multiple recordings have title matches and album matches. This may indicate an issue with the metadata or multiple versions of the same song."
                        )

                        ### Use deepdiff to compare the metadata of the found recordings and see if we can find any differences that would help us narrow down the results

                        import deepdiff

                        # create pairwise combinations of found_recordings
                        pairs = []
                        for i in range(len(found_recordings)):
                            for j in range(i + 1, len(found_recordings)):
                                pairs.append((found_recordings[i], found_recordings[j]))

                        diffs = []
                        print(f"Comparing {len(pairs)} pairs of release groups:")
                        for pair in pairs:
                            diff = deepdiff.DeepDiff(
                                pair[0], pair[1], ignore_order=True
                            )
                            print(f"Comparing {pair[0]['id']} and {pair[1]['id']}:")
                            print(diff)
                            diffs.append((pair[0]["id"], pair[1]["id"], diff))

                        print("Finished comparing pairs of release groups.")
                        # use user input to select the correct recording based on the differences
                        print(
                            "Please review the differences above and enter the ID (from the start) of the correct recording:"
                        )
                        selected_id = input().strip()
                        found_recording = None
                        for recording in found_recordings:
                            if recording["id"].startswith(selected_id):
                                found_recording = recording
                                break

                else:
                    print("Only one recording found for this fingerprint.")
                    found_recording = list(id_to_recording.values())[0]

                if not found_recording:
                    raise ValueError("No suitable recording found for this fingerprint")

                found_track_metadata = TrackMetadata(
                    path=file_path,
                    title=found_recording.get("title"),
                    artists=found_recording.get("artists", []),
                    album=found_recording.get("release_group", {}).get("title"),
                )
                combined_track_metadata = combined_track_metadata + found_track_metadata
                song = Song(
                    file_paths={file_path},
                    fingerprint=fingerprint,
                    title=combined_track_metadata.title or file_path.split("/")[-1],
                    artists=combined_track_metadata.artists or [],
                    album=combined_track_metadata.album or "",
                    duration=duration,  # Duration would be extracted from the file
                )
        if song is None:
            raise ValueError(f"Could not create song from file: {file_path}")
        fingerprint_to_song_cache[fingerprint] = song
        filepath_to_song_cache[file_path] = song
        return song
