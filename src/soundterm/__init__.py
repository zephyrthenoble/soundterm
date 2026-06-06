from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from pygame import mixer


class StopwatchApp(App):
    """A Textual app to manage stopwatches."""

    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("s", "play_song", "Play a song"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        mixer.init()
        yield Header()
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


def main():
    app = StopwatchApp()
    app.run()


if __name__ == "__main__":
    main()
