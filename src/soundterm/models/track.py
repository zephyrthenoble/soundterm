from sqlmodel import SQLModel, Field
from typing import Optional, Iterable, cast, Literal
from datetime import datetime
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


class TrackMetadata(SQLModel):
    path: PathLike
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

    def compare_title(self, other_title: str) -> bool:
        """@brief Compare track title with another string, ignoring common variations.

        This method performs a case-insensitive comparison of the track's title
        against another string, while ignoring common formatting differences such
        as punctuation, whitespace, and certain stop words. It is designed to
        determine if two titles likely refer to the same song even if they are
        not exact matches.

        @param other_title The title string to compare against.
        @return True if the titles are considered a match, False otherwise.
        """

        def normalize_title(title: str) -> str:
            # Convert to lowercase
            title = title.lower()
            # Remove punctuation and special characters
            title = re.sub(r"[^\w\s]", "", title)
            # Remove extra whitespace
            title = re.sub(r"\s+", " ", title).strip()
            # Remove common stop words (optional)
            stop_words = {"the", "a", "an", "and", "of", "in", "on", "for"}
            title_words = [word for word in title.split() if word not in stop_words]
            return " ".join(title_words)

        normalized_self_title = normalize_title(self.title or "")
        normalized_other_title = normalize_title(other_title or "")

        return normalized_self_title == normalized_other_title

    def _add_paths(
        self,
        other: Optional[PathLike],
        strategy: TrackMetadataCombinePathStrategy = "raise",
    ) -> Optional[PathLike]:
        """@brief Combine two file paths, ensuring consistency.

        When merging TrackMetadata from different sources, we may encounter cases
        where both have a path but they differ. This method defines the logic for how to handle such conflicts based on the specified strategy.
        @param other The other path to combine with self.
        @param strategy The strategy to resolve conflicts: 'self' to keep self's path,
        'other' to keep the other path, 'raise' to raise an error on conflict.
        @return The combined path based on the specified strategy.
        """

        if self.path and other:
            if self.path != other:
                if strategy == "self":
                    print(
                        f"Conflict in paths: keeping self '{self.path}' over other '{other}'"
                    )
                    return self.path
                elif strategy == "other":
                    print(
                        f"Conflict in paths: keeping other '{other}' over self '{self.path}'"
                    )
                    return other
                elif strategy == "raise":
                    raise ValueError(
                        f"Cannot combine different paths: '{self.path}' vs '{other}'"
                    )
        return self.path or other

    def _add_fingerprints(
        self,
        other: Optional[Fingerprint],
        strategy: TrackMetadataCombineFingerprintsStrategy = "raise",
    ) -> Optional[Fingerprint]:
        """@brief Combine two audio fingerprints, ensuring consistency.

        When merging TrackMetadata from different sources, we may encounter cases
        where both have a fingerprint but they differ. This method defines the logic for how to handle such conflicts based on the specified strategy.
        @param other The other fingerprint to combine with self.
        @param strategy The strategy to resolve conflicts: 'self' to keep self's fingerprint,
        'other' to keep the other fingerprint, 'raise' to raise an error on conflict.
        @return The combined fingerprint based on the specified strategy.
        """

        if self.fingerprint and other:
            if self.fingerprint != other:
                if strategy == "self":
                    print(
                        f"Conflict in fingerprints: keeping self '{self.fingerprint}' over other '{other}'"
                    )
                    return self.fingerprint
                elif strategy == "other":
                    print(
                        f"Conflict in fingerprints: keeping other '{other}' over self '{self.fingerprint}'"
                    )
                    return other
                elif strategy == "raise":
                    raise ValueError(
                        f"Cannot combine different fingerprints: '{self.fingerprint}' vs '{other}'"
                    )
        return self.fingerprint or other

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
        y, sr = librosa.load(self.path, sr=self.sample_rate)

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

        for tag_key, meta_key in tag_mappings.items():
            print(f"Checking for tag: {tag_key}")

            try:
                # there is an issue when checking for certain tags in some file types because of the special characters
                # so we need to catch ValueError as we access the file object
                if tag_key in audio_file:
                    audio_tag_value = audio_file[tag_key]
                    print(f"Tag {tag_key} is of type {type(audio_tag_value)}")
                    if audio_tag_value is None:
                        print(f"Tag {tag_key} is None, skipping.")
                        continue
                    elif isinstance(audio_tag_value, Iterable):
                        tag_list = list(audio_tag_value)
                        if len(tag_list) > 1:
                            print(f"Tag {tag_key} is a list with multiple values.")
                            for v in tag_list:
                                print(f" - {v}, type: {type(v)}")
                            # Join multiple values into a single string
                            input("Press Enter to continue...")
                        elif len(tag_list) == 0:
                            print(f"Tag {tag_key} is an empty list, skipping.")
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

        # Common track number patterns at the beginning of filename
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
                    if match.groupdict().get("artist") and not self.artist:
                        self.artist = match.group("artist").strip()
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
