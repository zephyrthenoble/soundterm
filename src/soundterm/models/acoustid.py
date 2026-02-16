import re
from joblib.test.test_memory import count_and_append
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict, model_validator
import json
from pydantic import ValidationError
from typing import Any, TYPE_CHECKING


from pprint import pprint

if TYPE_CHECKING:
    from soundterm.models.track import TrackMetadata

SCORE_THRESHOLD = 0.7
DEFAULT_TIMEOUT = 30
API_KEY = "iRDSOogTx3"  # Replace with your actual AcoustID API key


class AcoustIDAPIModel(SQLModel):
    # populate_by_name: allows us to use the alias (e.g. "type") when creating the model, even though the field name is different (e.g. "primary_type")
    # extra="ignore": allows us to ignore any extra fields that are not defined in the model, which is useful when dealing with APIs that may return additional data we don't care about
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class AcoustIDArtist(AcoustIDAPIModel):
    id: str | None = None
    name: str


class AcoustIDTrack(AcoustIDAPIModel):
    artists: list[str] | None = None
    id: int | str | None = None
    position: int | None = None
    title: str | None = None
    duration: float | None = None

    @model_validator(mode="before")
    @classmethod
    def build_release_group_type(cls, data: Any) -> Any:
        if isinstance(data, dict):
            artists: list[str] | str | None = data.get("artists")
            if isinstance(artists, list) and artists:
                first_artist: str = artists[0]
                if isinstance(first_artist, dict) and "name" in first_artist:
                    data["artists"] = [
                        artist["name"]
                        for artist in artists
                        if isinstance(artist, dict) and "name" in artist
                    ]
                elif isinstance(first_artist, str):
                    normalized_artists = artists
                    if len(artists) == 1:
                        normalized_artists = [
                            name.strip() for name in artists[0].split(",")
                        ]
                    data["artists"] = normalized_artists
        return data


class AcoustIDMediums(AcoustIDAPIModel):
    position: int | None = None
    track_count: int | None = None
    tracks: list[AcoustIDTrack] = Field(default_factory=list)


class AcoustIDRelease(AcoustIDAPIModel):
    id: str | None = None
    title: str | None = None
    mediums: list[AcoustIDMediums] = Field(default_factory=list)


class AcoustIDReleaseGroup(AcoustIDAPIModel):
    id: str | None = None
    title: str | None = None
    artists: list[AcoustIDArtist] = Field(default_factory=list)
    releases: list[AcoustIDRelease] = Field(default_factory=list)
    primary_type: str | None = Field(default=None, alias="type")
    secondary_types: list[str] = Field(default_factory=list, alias="secondarytypes")


class AcoustIDSongRecordings(AcoustIDAPIModel):
    id: str | None = None
    duration: float | None = None
    title: str | None = None
    artists: list[AcoustIDArtist] = Field(default_factory=list)


class AcoustIDFlattenedMetadata(AcoustIDSongRecordings, AcoustIDTrack):
    pass


class AcoustIDSongMetadata(AcoustIDAPIModel):
    id: str | None = None
    releasegroups: list[AcoustIDReleaseGroup] = Field(default_factory=list)
    recordings: list[AcoustIDSongRecordings] = Field(default_factory=list)

    def flatten(self) -> list[AcoustIDSongRecordings]:
        """@brief Flatten the nested structure of release groups and recordings in the AcoustID metadata.
        @return A flat list of AcoustIDSongRecordings extracted from the nested release groups and recordings.
        """
        flattened_recordings: list[AcoustIDSongRecordings] = []
        if self.recordings:
            for recording in self.recordings:
                flattened_recordings.append(recording)
        return flattened_recordings


class AcoustIDSongMetadataResults(AcoustIDAPIModel):
    id: str | None = None
    recordings: list[AcoustIDSongMetadata] = Field(default_factory=list)
    score: float

    def flatten_recordings(self) -> list[AcoustIDSongRecordings]:
        """@brief Flatten the nested structure of recordings in the AcoustID metadata results.
        @return A flat list of AcoustIDSongRecordings extracted from the nested release groups and recordings.
        """
        flattened_recordings: list[AcoustIDSongRecordings] = []
        for recording in self.recordings:
            flattened_recordings.extend(recording.flatten())
        return flattened_recordings


class AcoustIDLookupResults(AcoustIDAPIModel):
    results: list[AcoustIDSongMetadataResults] = Field(default_factory=list)
    status: str

    def create_track_metadata(
        self, score_threshold: float
    ) -> dict[float, list["TrackMetadata"]]:
        """@brief Create a TrackMetadata instance from the AcoustID lookup results, using the first result that meets the score threshold.
        @param score_threshold Minimum score to consider a result valid.
        @return A TrackMetadata instance populated with data from the result.
        """
        from soundterm.models.track import TrackMetadata

        track_metadata_ranking: dict[float, list["TrackMetadata"]] = {}

        results_list = [x for x in self.results if x.score >= score_threshold]

        count_to_recording: dict[int, dict] = {}
        count = 1
        for result in results_list:
            print(f"Result ID: {result.id}, Score: {result.score}")
            score = result.score
            print(f"Score: {score}")
            recordings = result.recordings
            if not recordings:
                print("No recordings found for this result.")
                print(f"Result data: {result}")
                continue
            for recording in recordings:
                recording_id = recording.id
                releases = recording.get("releasegroups", [])
                release_titles = [release.title for release in recording.releasegroups]
                print(f"- Recording {count}: {recording_id}")
                print(f"  - Title: {recording.title}")
                print(f"  - Artists: {[artist.name for artist in recording.artists]}")
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

        return track_metadata_ranking

    @staticmethod
    def trackmetadata_from_fingerprint_results(
        fingerprint: str, duration: float, score_threshold: float
    ) -> list["TrackMetadata"]:
        from soundterm.models.track import TrackMetadata
        from acoustid import lookup

        track_metadata_list: list[TrackMetadata] = []

        count = 1
        count_to_recording = {}

        recording_response: dict = lookup(
            API_KEY,
            fingerprint,
            duration,
            [
                "recordings",
                "recordingids",
                "releases",
                "releaseids",
                "releasegroups",
                "releasegroupids",
                "tracks",
                "compress",
                "usermeta",
                "sources",
            ],
            DEFAULT_TIMEOUT,
        )
        results = recording_response.get("results", [])
        if not results:
            print("No matches found for this track.")
        else:
            from soundterm.models.acoustid import AcoustIDLookupResults

            acoustid_lookup_results = AcoustIDLookupResults.model_validate_json(
                json.dumps(recording_response)
            )
            pprint(recording_response)
            print(acoustid_lookup_results)
            input()
            for result in results:
                score = result.get("score", 0)
                if score < score_threshold:
                    continue
                print(f"Score: {score}")
                recordings = result.get("recordings", [])
                if not recordings:
                    print("No recordings found for this result.")
                    print(f"Result data: {result}")
                    continue
                else:
                    for recording in recordings:
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

        artist_list = (
            [x["name"] for x in selected_recording.get("artists", [])]
            if selected_recording
            else []
        )
        if selected_recording:
            releases = selected_recording.get("releasegroups", [])
            release_titles = [release.get("title") for release in releases]
            found_track_metadata = TrackMetadata(
                path=None,
                title=selected_recording.get("title"),
                artists=",".join(artist_list),
                releases=release_titles if release_titles else [],
            )
            track_metadata_list.append(found_track_metadata)

        return track_metadata_list


if __name__ == "__main__":
    data = json.load(open(r"/home/zephyrthenoble/Programming/soundterm/result.json"))

    try:
        acoustid_lookup_results = AcoustIDLookupResults.model_validate_json(
            json.dumps(data)
        )
        pprint(data)
        print(acoustid_lookup_results)

    except ValidationError as e:
        # Print the default error message (which will be truncated)
        print("Default error message:", e)

        # Iterate over all errors to access the full input value
        print("\nDetailed errors and full input:")
        for error in e.errors():
            print(f"* Error location: {error['loc']}")
            print(f"  Error message: {error['msg']}")
            print(f"  **Full input value for this error:** {error['input']}")
            print("-" * 20)
