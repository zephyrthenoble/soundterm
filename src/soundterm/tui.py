from textual.containers import Container
from textual.containers import Horizontal
from textual.screen import Screen
from textual.containers import VerticalGroup
import tomlkit
from typing import Iterable, Any
from pathlib import Path

import tomlkit

from textual.app import App, ComposeResult, RenderResult
from textual.widgets import Footer, Header, DirectoryTree, Label, Button
from textual.reactive import reactive

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

debug = {}


class DirPicker(Screen):
    temp_library: reactive[Path | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Container(id="dirpicker"):
            with Horizontal():
                yield Button("Select", id="select", variant="success", disabled=True)
                yield Button("Clear", id="clear")
                yield Button("Cancel", id="cancel", variant="error")
            with Horizontal():
                yield Button("Clear", id="clear-selection")
                yield Label(id="label-library")
            yield DirOnlyTree(Path.home())

    def on_mount(self):
        self.reset_temp_library()

    def watch_temp_library(self, old, new):
        label = self.query_one("#label-library", Label)
        label.content = str(new)

    def reset_temp_library(self):
        self.temp_library = Path(config["library"]) if config.get("library") else None
        label = self.query_one("#label-library", Label)
        label.content = "None"
        self.query_one("#select", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.reset_temp_library()
            self.app.pop_screen()

        if event.button.id == "select":
            self.notify(f"Selected {self.temp_library}")
            self.update_config()
            self.reset_temp_library()
            self.app.pop_screen()

        if event.button.id == "clear":
            self.query_one(DirOnlyTree).remove()
            self.mount(DirOnlyTree(Path.home()))

        if event.button.id == "clear-selection":
            self.reset_temp_library()

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Triggered when a user clicks or presses Enter on a directory."""
        # event.path contains a standard pathlib.Path object
        selected_path = event.path

        # Display a temporary toast notification in the UI
        # self.notify(f"You selected directory: {selected_path}")
        self.query_one("#select", Button).disabled = False
        self.temp_library = selected_path
        self.query_one("#label-library", Label).content = str(self.temp_library)

    def update_config(self):
        config["library"] = str(self.temp_library)

        config_path.write_text(tomlkit.dumps(config))


class MenuScreen(Screen):
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        mixer.init()
        yield Header()
        yield Footer()


class MainApp(App):
    """A Textual app to manage stopwatches."""

    CSS_PATH = "style.tcss"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("s", "play_song", "Play a song"),
    ]

    SCREENS = {"menu": MenuScreen, "dirpicker": DirPicker}
    library: Path
    temp_library: Path

    def on_mount(self):
        self.push_screen("menu")

        if config.get("library") or debug.get("dirpicker"):
            self.push_screen("dirpicker")

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


class DirOnlyTree(DirectoryTree):
    def filter_paths(self: "DirOnlyTree", paths: Iterable[Path]) -> Iterable[Path]:
        return [
            path for path in paths if (path.is_dir() and not path.stem.startswith("."))
        ]
