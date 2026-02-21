from typing import Optional, Iterable, cast
from mutagen import File as MutagenFile
from mutagen._tags import Tags as MutagenTags
from mutagen._file import FileType as MutagenFileType
import librosa
import numpy as np
from traceback import print_exc
from pathlib import Path
import re
import io
import soundfile as sf
import tempfile

from os import PathLike, unlink


from soundterm.models import TrackMetadata

from pydantic import BaseModel


class TrackAnalyzer(BaseModel):
    path: PathLike
    duration: Optional[float] = None
    sample_rate: Optional[float] = None
    tempo: Optional[float] = None
    brightness: Optional[float] = None
    mfcc_mean: Optional[list[float]] = None
    key: Optional[str] = None
    energy: Optional[float] = None
    dynamic_range: Optional[float] = None
    zcr: Optional[float] = None
    valence: Optional[float] = None
    title: Optional[str] = None
    artists: Optional[str] = None
    releases: Optional[list[str]] = None
    track_number: Optional[int] = None
    parsed_title: Optional[str] = None
    parsed_track: Optional[int] = None

    def print_all_metadata(self):
        self.analyze_song()
        for field_name, value in self.__dict__.items():
            print(f"{field_name}: {type(value)}")

    def analyze_song(self) -> None:
        # Always extract metadata first (this is more reliable)
        self.extract_metadata()

        # Try audio analysis, but don't fail if it doesn't work
        try:
            self.audio_analysis()
        except Exception as audio_error:
            print(
                f"Warning: Audio analysis failed for {self.path}: {type(audio_error)} {audio_error}"
            )

    def audio_analysis(self) -> None:
        # Load audio file
        if not self.path:
            print("Warning: No path provided for audio analysis.")
            return
        y, _sr = librosa.load(self.path, sr=self.sample_rate)
        sr = float(_sr)

        self.sample_rate = sr
        # Tempo and beat
        tempo, beats = librosa.beat.beat_track(y=y, sr=self.sample_rate)
        self.tempo = float(tempo)

        # Mel-frequency spectrogram
        S = librosa.feature.melspectrogram(y=y, sr=self.sample_rate)
        # Spectral features
        spectral_centroids = librosa.feature.spectral_centroid(
            y=y, sr=self.sample_rate, S=S
        )[0]
        self.brightness = float(np.mean(spectral_centroids))

        # MFCC (Mel-frequency cepstral coefficients) for timbre
        mfccs = librosa.feature.mfcc(y=y, sr=self.sample_rate, n_mfcc=13, S=S)
        self.mfcc_mean = [float(x) for x in np.mean(mfccs, axis=1)]

        # Chroma features for key detection
        chroma = librosa.feature.chroma_stft(y=y, sr=self.sample_rate)
        self.key = self._detect_key(chroma)

        # Energy and dynamics
        rms = librosa.feature.rms(y=y)[0]
        self.energy = float(np.mean(rms))
        self.dynamic_range = float(np.std(rms))

        # Zero crossing rate (indicates percussive vs. harmonic content)
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        self.zcr = float(np.mean(zcr))

        # Mood estimation
        # Energy (0-1 scale)
        # Normalize energy based on typical ranges
        self.energy = min(1.0, self.energy / 0.3)

        # Valence (happiness) - based on brightness and tempo
        brightness_norm = min(1.0, self.brightness / 3000)
        tempo_norm = min(1.0, max(0.0, (self.tempo - 60) / 140))
        self.valence = (brightness_norm + tempo_norm) / 2

    def extract_metadata(self):
        metadata = {}
        if not self.path:
            print("Warning: No path provided for audio analysis.")
            return
        print(self.path)
        try:
            try:
                audio_file: MutagenFileType = MutagenFile(self.path)
                if audio_file:
                    # Extract common tags
                    if hasattr(audio_file, "tags") and audio_file.tags:
                        print(f"Tags found: {list(audio_file.tags.keys())}")
                        self._extract_common_tags(audio_file)

                    # Get duration
                    if hasattr(audio_file, "info") and hasattr(
                        audio_file.info, "length"
                    ):
                        self.duration = float(audio_file.info.length)

            except Exception as mutagen_error:
                print(f"Warning: Mutagen failed to read {self.path}: {mutagen_error}")
                # Continue with filename parsing even if mutagen fails
                print_exc()

            # Parse filename for track number and clean title

        except Exception as e:
            print(f"Error extracting metadata from {self.path}: {e}")
            print_exc()
            # Return basic info from filename even if everything else fails

        self._parse_filename(self.path)

        return metadata

    def _extract_common_tags(self, audio_file: MutagenFileType):
        """@brief Normalize mutagen tag representations across formats.

        @param audio_file Mutagen wrapper instance.
        @return Dict with consistent ``title``, ``artist``, ``album`` keys.
        @see extract_metadata
        """

        # Common tag mappings for different formats
        tag_mappings: dict[str, str] = {
            # ID3 tags (MP3)
            "TIT2": "title",
            "TPE1": "artist",
            "TALB": "album",
            "TDRC": "year",
            "TCON": "genre",
            "TRCK": "track",
            "TPE2": "albumartist",
            # Vorbis comments (FLAC, OGG)
            "TITLE": "title",
            "ARTIST": "artist",
            "ALBUM": "album",
            "DATE": "year",
            "GENRE": "genre",
            "TRACKNUMBER": "track",
            "ALBUMARTIST": "albumartist",
            # MP4 tags (M4A)
            "©nam": "title",
            "©ART": "artist",
            "©alb": "album",
            "©day": "year",
            "©gen": "genre",
            "trkn": "track",
            "aART": "albumartist",
            # other
            "copyright": "copyright",
        }

        prefixes = ["TXXX:", "COMM:"]  # Common prefixes for custom tags
        to_add = []
        for prefix in prefixes:
            for tag_key, meta_key in tag_mappings.items():
                full_tag = prefix + tag_key
                to_add.append((full_tag, meta_key))
        for full_tag, meta_key in to_add:
            tag_mappings[full_tag] = meta_key

        for tag_key, meta_key in tag_mappings.items():
            # print(f"Checking for tag: {tag_key}")

            try:
                # there is an issue when checking for certain tags in some file types because of the special characters
                # so we need to catch ValueError as we access the file object
                if tag_key in audio_file:
                    audio_tag_value = audio_file[tag_key]
                    # print(f"Tag {tag_key} is of type {type(audio_tag_value)}")
                    if audio_tag_value is None:
                        # print(f"Tag {tag_key} is None, skipping.")
                        continue
                    elif isinstance(audio_tag_value, Iterable):
                        tag_list = list(audio_tag_value)
                        if len(tag_list) > 1:
                            # print(f"Tag {tag_key} is a list with multiple values.")
                            for v in tag_list:
                                # print(f" - {v}, type: {type(v)}")
                                pass
                            # Join multiple values into a single string
                            input("Press Enter to continue...")
                        elif len(tag_list) == 0:
                            # print(f"Tag {tag_key} is an empty list, skipping.")
                            continue
                        else:
                            tag_value = cast(MutagenTags, tag_list[0])
                    else:
                        tag_value = cast(MutagenTags, audio_tag_value)

                        value: int | float | str | None = None
                        # Special handling for track numbers
                        if meta_key == "track":
                            if hasattr(tag_value, "text"):
                                value = (
                                    ",".join(tag_value.text) if tag_value.text else None  # type: ignore
                                )
                                if not value:
                                    continue
                                try:
                                    # Extract just the track number
                                    track_str = str(value).split("/")[0]
                                    self.track_number = int(track_str)
                                except (ValueError, IndexError):
                                    pass
                        else:
                            # Handle text values
                            if hasattr(tag_value, "text"):
                                value = (
                                    ",".join(tag_value.text)  # type: ignore
                                    if tag_value.text
                                    else str(tag_value)
                                )

                            self.__setattr__(meta_key, str(value).strip())
            except ValueError as ve:
                print(f"Warning: Mutagen ValueError {audio_file.get('title', '')} {ve}")

    def _parse_filename(self, file_path: PathLike):
        """@brief Derive best-effort title/track metadata from filenames.

        @param file_path Audio path (only basename is inspected).
        @return Dict including ``parsed_title`` and optional ``parsed_track``.
        @see services.song_factory.resolve_display_name
        @see services.song_factory.extract_track_number
        """

        filename = Path(file_path).stem  # Get filename without extension

        # #TODO combine this somehow with the other system Common track number patterns at the beginning of filename
        track_patterns = [
            r"^(?P<artist>.+)\s+-\s+(?P<album>.+)\s+-\s+(?P<track>\d{1,3})\s+-\s+(?P<title>.+)$",  # "Artist - Album - 01 - Title"
            r"^(?P<artist>.+)\s+(?P<album>.+)\s+(?P<track>\d{1,3})\s+[-._\s]*(?P<title>.+)$",  # "Artist Album 01 Title"
            r"^Track\s*(?P<track>\d{1,3})\s*[-._\s]*(?P<title>.+)$",  # "Track 01 - Title"
            r"^(?P<track>\d{1,3})\s*[-._\s]+(?P<title>.+)$",  # "01 - Title", "1. Title", "01_Title"
            r"^(?P<track>\d{1,3})\s*\.?\s*(?P<title>.+)$",  # "01 Title", "1.Title"
        ]

        track_number = None

        for pattern in track_patterns:
            match = re.match(pattern, filename, re.IGNORECASE)
            if match:
                try:
                    track_number = int(match.group("track"))
                    cleaned_title = match.group("title").strip()
                    if cleaned_title:  # Only use cleaned title if it's not empty
                        self.parsed_title = cleaned_title
                        if not self.title:
                            self.title = cleaned_title
                    self.parsed_track = track_number
                    if not self.track_number:
                        self.track_number = track_number
                    if match.groupdict().get("artist") and not self.artists:
                        self.artists = match.group("artist").strip()
                    if match.groupdict().get("album") and not self.releases:
                        self.releases = [match.group("album").strip()]
                    break
                except (ValueError, IndexError) as err:
                    print(f"Error parsing track number from filename {filename}: {err}")
                    continue

    def _detect_key(self, chroma) -> str:
        """@brief Estimate the musical key using chroma vectors.

        @param chroma 12xN chromagram from librosa.
        @return Best-fit key label such as ``"C#"``.
        """
        # Simplified key detection
        key_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        chroma_mean = np.mean(chroma, axis=1)
        key_idx = np.argmax(chroma_mean)
        return key_names[key_idx]

    @staticmethod
    def from_acoustid_result(results: dict, score_threshold: float) -> "TrackMetadata":
        """@brief Create TrackMetadata from an AcoustID lookup result.

        @param results The raw result dict from an AcoustID API lookup.
        @param score_threshold Minimum score to consider a result valid.
        @return A TrackMetadata instance populated with data from the result.
        """
        queried_metadata = TrackMetadata()
        if results.get("status") != "ok":
            raise ValueError(f"Invalid AcoustID result status: {results.get('status')}")

        results_list = results.get("results", [])
        print(f"Total results from AcoustID: {len(results_list)}")
        results_list = [x for x in results_list if x.get("score", 0) >= score_threshold]
        print(f"Results above score threshold {score_threshold}: {len(results_list)}")

        count_to_recording: dict[int, dict] = {}
        count = 1
        if not results_list:
            print("No results meet the score threshold.")
            return queried_metadata
        for result in results_list:
            score = result.get("score", 0)
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

        for result in results_list:
            result_id = result.get("id", "N/A")
            result_score = result.get("score", 0)
            print(f"Processing result ID: {result_id} with score: {result_score}")

            metadata = TrackMetadata()
            if "recordings" in result and len(result["recordings"]) > 0:
                recording = result["recordings"][0]
                metadata.title = recording.get("title")
                if "artists" in recording and len(recording["artists"]) > 0:
                    metadata.artists = recording["artists"][0].get("name", "")
                if "releases" in recording and len(recording["releases"]) > 0:
                    metadata.releases = [
                        r.get("title", "") for r in recording["releases"]
                    ]
            return metadata
        return queried_metadata

    def create_preview_segments(
        self, file_path: str, segment_duration: float = 5.0
    ) -> list[bytes]:
        """@brief Generate multiple WAV snippets for UI previews.

        Produces clips from the beginning, middle, and end of the track so a
        caller can stream lightweight previews.

        @param file_path Source audio path.
        @param segment_duration Length of each preview segment in seconds.
        @return List of byte buffers ready for transmission.
        """
        try:
            y, sr = librosa.load(file_path, sr=self.sample_rate)
            assert self.sample_rate is not None
            sr = int(self.sample_rate)
            if not self.duration:
                self.duration = len(y) / self.sample_rate
            segment_samples = int(segment_duration * self.sample_rate)

            segments = []

            # 1. Beginning (first 5 seconds)
            start_segment = y[:segment_samples]
            segments.append(self._audio_to_bytes(start_segment, sr))

            # 2. Random before middle
            middle_point = len(y) // 2
            before_middle_start = np.random.randint(
                segment_samples, middle_point - segment_samples
            )
            before_middle_segment = y[
                before_middle_start : before_middle_start + segment_samples
            ]
            segments.append(self._audio_to_bytes(before_middle_segment, sr))

            # 3. Middle (5 seconds around the center)
            middle_start = middle_point - segment_samples // 2
            middle_segment = y[middle_start : middle_start + segment_samples]
            segments.append(self._audio_to_bytes(middle_segment, sr))

            # 4. Random after middle
            after_middle_start = np.random.randint(
                middle_point, len(y) - segment_samples * 2
            )
            after_middle_segment = y[
                after_middle_start : after_middle_start + segment_samples
            ]
            segments.append(self._audio_to_bytes(after_middle_segment, sr))

            # 5. End (last 5 seconds)
            end_segment = y[-segment_samples:]
            segments.append(self._audio_to_bytes(end_segment, sr))

            return segments

        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"Error creating preview for {file_path}: {e}")
            return []

    def _audio_to_bytes(self, audio_data: np.ndarray, sample_rate: int) -> bytes:
        """@brief Serialize numpy audio buffers into WAV bytes.

        @param audio_data Mono audio array.
        @param sample_rate Sample rate to embed in the WAV header.
        @return Binary WAV payload or ``b''`` when conversion fails.
        @see create_preview_segments
        """
        try:
            # Ensure we have valid audio data
            if len(audio_data) == 0:
                print("Warning: Empty audio data")
                return b""

            # Use BytesIO to create WAV data in memory
            with io.BytesIO() as buffer:
                sf.write(buffer, audio_data, int(sample_rate), format="WAV")
                buffer.seek(0)
                data = buffer.getvalue()

                if len(data) == 0:
                    print("Warning: Generated zero-length audio data")
                    return b""

                return data
        except Exception as e:
            print(f"Error converting audio to bytes: {e}")
            # Fallback: try with temporary file
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False
                ) as temp_file:
                    sf.write(temp_file.name, audio_data, int(sample_rate))
                    temp_file.close()  # Close the file handle

                    # Read the file content
                    with open(temp_file.name, "rb") as f:
                        data = f.read()

                    # Clean up the temporary file
                    unlink(temp_file.name)

                    if len(data) == 0:
                        print("Warning: Fallback also generated zero-length data")
                        return b""

                    return data
            except Exception as fallback_error:
                print(f"Fallback audio conversion also failed: {fallback_error}")
                return b""
