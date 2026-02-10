import soundterm.settings
from soundterm.models.song import Song


def main() -> None:
    print("Hello from soundterm!")
    song_path = r"C:\Users\zephy\Music\Griffin McElroy - The Adventure Zone- The Crystal Kingdom OST\02 Crystal Kingdom - Part One.mp3"
    fpcalc_path = r"D:\projects\soundterm\bin\fpcalc.exe"
    # add to system path so pyacoustid can find it
    import os

    os.environ["PATH"] += os.pathsep + os.path.dirname(fpcalc_path)
    song = Song.from_file_path(song_path)
    print(song)
