from soundterm.config import config, debug

from soundterm.menu import MenuScreen
from soundterm.dirtree import DirPicker

from typing import Iterable, Any
from pathlib import Path

from rich.table import Table

from textual import log
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
    DataTable,
    Static,
    ProgressBar,
)
from textual.widgets.option_list import Option
from textual.reactive import reactive
from textual.visual import VisualType


from platformdirs import PlatformDirs

RUNNING = True


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
