from numpy import e
import soundterm.settings
from soundterm.models.song import Song

import os

from pathlib import Path
import json


# add to system path so pyacoustid can find it


def main() -> None:

    settings = soundterm.settings.Settings()
    error_file_json_list = []
    error_file_list_path = Path(settings.error_file)
    if error_file_list_path.exists():
        with open(error_file_list_path, "r") as f:
            error_file_json_list = json.load(f)
    error_set = set(error_file_json_list)
    if str(settings.fpcalc) not in os.environ["PATH"]:
        os.environ["PATH"] += os.pathsep + os.path.dirname(str(settings.fpcalc))
    try:
        if settings.file:
            print(f"Running single file mode on {settings.file}...")
            song = Song.from_file_path(Path(settings.file))
            if not song:
                print(f"Failed to process {settings.file}.")
                error_set.add(str(settings.file))
            print(song)
        else:
            song_list = []
            for song_path_str in Path(settings.music_dir).glob("**/*.mp3"):
                if str(song_path_str) in error_set:
                    print(
                        f"Skipping {song_path_str} as it previously failed to process."
                    )
                    continue
                print(f"Processing {song_path_str}...")
                song_path = Path(song_path_str)
                song = Song.from_file_path(song_path)
                if not song:
                    print(f"Failed to process {song_path}. Skipping.")
                    error_set.add(str(song_path))
                    continue
                song_list.append(song)
                debug = False
                if debug:
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
            print(f"Finished processing {song_path}.")
            print(f"Song count: {len(song_list)}")

    finally:
        if error_set:
            with open(error_file_list_path, "w") as f:
                json.dump(list(error_set), f)
