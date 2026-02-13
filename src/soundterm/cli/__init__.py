import soundterm.settings
from soundterm.models.song import Song

from pathlib import Path


def main() -> None:
    print("Hello from soundterm!")
    song_path = Path(
        r"C:\Users\zephy\Music\Griffin McElroy - The Adventure Zone- The Crystal Kingdom OST\02 Crystal Kingdom - Part One.mp3"
    )
    fpcalc_path = Path(r"D:\projects\soundterm\bin\fpcalc.exe")
    # add to system path so pyacoustid can find it
    import os

    os.environ["PATH"] += os.pathsep + os.path.dirname(fpcalc_path)
    song = Song.from_file_path(song_path)
    print()
    print("Song data:")
    for key, value in song.model_dump().items():
        if key == "fingerprint":
            print(f"  {key}: {value[:10]}... (truncated)")
            continue
        if "metadata" in key:
            print(f"  {key}:")
            for meta_key, meta_value in value.items():
                if meta_key == "fingerprint":
                    print(f"    {meta_key}: {meta_value[:10]}... (truncated)")
                    continue
                print(f"    {meta_key}: {meta_value}")
        else:
            print(f"  {key}: {value}")
