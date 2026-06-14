from soundterm.config import config, config_path

from typing import Iterable
from pathlib import Path

import tomlkit
from textual import log
from textual.app import ComposeResult
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
    DataTable,
    Static,
    ProgressBar,
)
from textual.widgets.option_list import Option
from textual.reactive import reactive
from textual.visual import VisualType

from pygame import mixer, USEREVENT, event, Sound


class DirOnlyTree(DirectoryTree):
    def filter_paths(self: "DirOnlyTree", paths: Iterable[Path]) -> Iterable[Path]:
        return [
            path for path in paths if (path.is_dir() and not path.stem.startswith("."))
        ]


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
