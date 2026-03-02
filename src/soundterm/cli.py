from soundterm.settings import get_settings
from soundterm.models import Song
from soundterm.libray import LibraryManager
from soundterm.utils.database import SessionManager
import os

from pathlib import Path
import json


def test_sqlmodel() -> None:
    song = Song(
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration=300,
        fingerprint="abc123",
        metadata={"key": "value"},
    )
    print(song)


def single_file_mode(file_path: Path, library_manager: LibraryManager) -> None:
    song = library_manager.process_song(file_path)
    if song:
        print(song)
    else:
        print(f"Failed to process {file_path}.")


def main() -> None:
    settings = get_settings()
    error_file_json_list = []
    error_file_list_path = Path(settings.error_file)
    if error_file_list_path.exists():
        with open(error_file_list_path, "r") as f:
            error_file_json_list = json.load(f)
    error_set = set(error_file_json_list)
    # add to system path so pyacoustid can find it
    if str(settings.fpcalc) not in os.environ["PATH"]:
        os.environ["PATH"] += os.pathsep + os.path.dirname(str(settings.fpcalc))
    with SessionManager() as session:
        library_manager = LibraryManager(path=settings.music_dir, session=session)
        try:
            if settings.file:
                print(f"Running single file mode on {settings.file}...")
                single_file_mode(settings.file, library_manager)
            else:
                library_manager.scan_music_directory()

        finally:
            if error_set:
                with open(error_file_list_path, "w") as f:
                    json.dump(list(error_set), f)
