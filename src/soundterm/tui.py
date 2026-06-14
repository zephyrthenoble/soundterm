from soundterm.config import config, debug

from soundterm.menu import MenuScreen
from soundterm.dirtree import DirPicker

from pathlib import Path


from textual.app import App



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
