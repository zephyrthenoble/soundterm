import asyncio
from pygame import Sound
import tomlkit
from typing import Iterable, Any
from pathlib import Path

from rich.table import Table

from textual.app import App, ComposeResult
from textual.message import Message
from textual.containers import Horizontal, Container, HorizontalScroll
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    DirectoryTree,
    Label,
    Button,
    Rule,
    OptionList,
)
from textual.widgets.option_list import Option
from textual.reactive import reactive

from pygame import mixer, USEREVENT, event
from pygame.mixer import music


from platformdirs import PlatformDirs

RUNNING = True
MUSIC_END_EVENT = USEREVENT + 1
music.set_endevent(MUSIC_END_EVENT)

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
            with Horizontal(id="interactibles"):
                with Horizontal(id="selection-buttons"):
                    yield Button(
                        "Select",
                        id="select",
                        variant="success",
                        disabled=True,
                        classes="disabled",
                    )
                    yield Button("Reset", id="reset")
                    yield Button("Cancel", id="cancel", variant="error")
                with Horizontal(id="library-label"):
                    yield Button("Clear", id="clear-selection")
                    with HorizontalScroll(id="label-scroll"):
                        yield Label(id="label-library")
            yield Rule()
            yield DirOnlyTree(Path.home())

    def on_mount(self):
        self.reset_temp_library()
        self.app.set_focus(self.query_one(DirOnlyTree))

    def watch_temp_library(self, old, new):
        label = self.query_one("#label-library", Label)
        label.content = str(new)

    def reset_temp_library(self):
        self.temp_library = Path(config["library"]) if config.get("library") else None
        label = self.query_one("#label-library", Label)
        label.content = "None"
        select_button = self.query_one("#select", Button)
        select_button.disabled = True
        select_button.add_class("disabled")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.reset_temp_library()
            self.app.pop_screen()

        if event.button.id == "select":
            self.notify(f"Selected {self.temp_library}")
            self.update_config()
            self.reset_temp_library()
            self.app.pop_screen()

        if event.button.id == "reset":
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
        select_button = self.query_one("#select", Button)
        select_button.disabled = False
        select_button.remove_class("disabled")

        self.temp_library = selected_path
        self.query_one("#label-library", Label).content = str(self.temp_library)

    def update_config(self):
        config["library"] = str(self.temp_library)

        config_path.write_text(tomlkit.dumps(config))


class MenuScreen(Screen):
    BINDINGS = [
        ("s", "play_song", "Play a song"),
        ("l", "load_songs", "Load songs"),
        ("a", "add_song", "Add song to playlist"),
    ]
    selected_song: Path | None = None

    songlist: list[Path] = []
    current_track_index: int | None = None

    playlist: list[Path] = []
    highlighted_song: Path | None = None
    highlighted_track_index: int | None = None

    class MusicEnd(Message):
        def __init__(self):
            super().__init__()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted):
        if event.option_list.id == "music-library":
            self.highlighted_song_index = event.option_index
            self.highlighted_song = self.songlist[self.highlighted_song_index]

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        if event.option_list.id == "music-library":
            selected_song_index = event.option_index
            self.selected_song = self.songlist[selected_song_index]
            self.notify(f"Selected song {selected_song_index}: {self.selected_song}")

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Footer()
        with Container(id="music-container"):
            with Horizontal(id="music-columns"):
                yield OptionList(id="music-library")
                yield OptionList(id="playlist")

    def on_mount(self):
        self.run_worker(self.poll_pygame_music)
        self.action_load_songs()

    async def poll_pygame_music(self):
        mixer.init()
        while True:
            if self.current_track_index and self.playlist:
                for pevent in event.get():
                    if pevent.type == MUSIC_END_EVENT:
                        self.current_track_index = (self.current_track_index + 1) % len(
                            self.playlist
                        )
                        music.load(self.playlist[self.current_track_index])
                        music.play(fade_ms=1000)
            await asyncio.sleep(0.001)

    def action_play_song(self) -> None:
        if self.selected_song:
            music.fadeout(1000)
            music.load(self.selected_song)
            music.play(fade_ms=1000)
        else:
            self.notify("Please select a song")

    def action_load_songs(self):
        if not config.get("library"):
            self.notify("No library set")
        else:
            self.songlist = [
                song for song in Path(config["library"]).rglob("*.*") if song.is_file()
            ]
        ol = self.query_one("#music-library", OptionList)
        ol.add_options([Option(song.stem) for song in self.songlist])

    def action_add_song(self):
        ol = self.query_one("#playlist", OptionList)
        if self.highlighted_song:
            ol.add_option(Option(self.highlighted_song.stem))
        else:
            self.notify("No highlighted song")


class MainApp(App):
    CSS_PATH = "style.tcss"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
    ]

    SCREENS = {"menu": MenuScreen, "dirpicker": DirPicker}
    library: Path
    temp_library: Path

    def on_mount(self):
        self.push_screen("menu")

        if not config.get("library") or debug.get("dirpicker"):
            self.push_screen("dirpicker")
        self.library = config["library"]

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )


class DirOnlyTree(DirectoryTree):
    def filter_paths(self: "DirOnlyTree", paths: Iterable[Path]) -> Iterable[Path]:
        return [
            path for path in paths if (path.is_dir() and not path.stem.startswith("."))
        ]
