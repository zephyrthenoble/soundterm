import tomlkit
from textual.widgets import Button
from typing import Iterable, Any
from pathlib import Path

import tomlkit

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, DirectoryTree

from pygame import mixer

from platformdirs import PlatformDirs

dirs = PlatformDirs("soundterm")
dirs.user_config_path.mkdir(parents=True, exist_ok=True)
config_type = "toml"
config_file_name = Path(f"config.{config_type}")
config_path = dirs.user_config_path / config_file_name


config: dict[str, Any] = {}
if config_type == "toml":
    if config_path.exists():
        with config_path.open("rb") as con_p:
            config = tomlkit.load(con_p)
else:
    raise ImportError(f"file type {config_type} not supported")

"""
version=1

library="/home/zephyrthenoble/music"
"""


class MainApp(App):
    """A Textual app to manage stopwatches."""

    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("s", "play_song", "Play a song"),
    ]

    library: Path
    temp_library: Path

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        # mixer.init()
        yield Header()
        if config.get("library"):
            self.library = Path(config["library"])
        else:
            yield DirOnlyTree(Path.home())
            yield Button("Select", id="select", variant="success")
            yield Button("Clear", id="clear")
        yield Footer()

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )

    def action_play_song(self) -> None:
        """Test"""
        dir = Path("/home/zephyrthenoble/Music/Kirby Canvas Curse")
        sound = mixer.Sound(dir / "10. Kirby Clear Dance 3.mp3")
        sound.play()

    def update_config(self):
        config["library"] = str(self.library)

        config_path.write_text(tomlkit.dumps(config))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "select":
            if self.temp_library:
                self.notify(f"Selected {self.temp_library}")
                self.library = self.temp_library
                self.update_config()
            self.query_one(DirOnlyTree).remove()
            dquery = self.query(Button)
            for b in dquery:
                if b.id == "select" or b.id == "clear":
                    b.remove()

        if event.button.id == "clear":
            self.query_one(DirOnlyTree).remove()
            self.mount(DirOnlyTree(Path.home()))

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Triggered when a user clicks or presses Enter on a directory."""
        # event.path contains a standard pathlib.Path object
        selected_path = event.path

        # Display a temporary toast notification in the UI
        self.notify(f"You selected directory: {selected_path}")
        self.temp_library = selected_path


class DirOnlyTree(DirectoryTree):
    def filter_paths(self: "DirOnlyTree", paths: Iterable[Path]) -> Iterable[Path]:
        return [path for path in paths if path.is_dir()]
