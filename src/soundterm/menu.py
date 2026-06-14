from soundterm.config import config

from pathlib import Path

from pygame import error as PyGameError

from textual.css.query import NoMatches
from textual.widgets.option_list import DuplicateID
from textual import log
from textual.app import ComposeResult
from textual.message import Message
from textual.containers import Horizontal, Container
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Label,
    OptionList,
    DataTable,
    ProgressBar,
)
from textual.widgets.option_list import Option
from textual.visual import VisualType

from pygame import mixer, USEREVENT, event, Sound
from pygame.mixer import music

MUSIC_END_EVENT = USEREVENT + 1
music.set_endevent(MUSIC_END_EVENT)


class MenuScreen(Screen):
    BINDINGS = [
        ("s", "play_song", "Play a song"),
        ("l", "load_songs", "Load songs"),
        ("a", "add_song", "Add song to playlist"),
        ("r", "remove_song", "Remove song from playlist"),
    ]
    selected_song: Path | None = None
    song_start_time: float
    song_duration: float
    last_poll: float = -1

    songlist: list[Path] = []
    current_track_index: int | None = None

    playlist: list[Path] = []
    highlighted_song: Path | None = None
    highlighted_track_index: int | None = None

    selected_option: Option | None = None
    original_selected_prompt: VisualType | None = None

    class MusicEnd(Message):
        def __init__(self):
            super().__init__()

    def mark_selected(self, option_list: OptionList, option: Option):
        # undo previous selected
        if self.selected_option:
            # type checking....
            if not self.selected_option.id:
                self.notify("Selected option has no ID")
                return
            else:
                so_id = self.selected_option.id
            if not self.original_selected_prompt:
                self.notify("No original selected prompt")
                return
            else:
                so_prompt = self.original_selected_prompt
            option_list.replace_option_prompt(so_id, so_prompt)

        # add custom tag
        self.selected_option = option
        self.original_selected_prompt = option.prompt
        if not self.selected_option.id:
            self.notify("Selected option has no ID")
            return
        else:
            so_id = self.selected_option.id
        new_prompt = f"[bold]{option.prompt}*[/]"
        option_list.replace_option_prompt(self.selected_option.id, new_prompt)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted):
        if event.option_list.id == "music-library":
            self.highlighted_song_index = event.option_index
            self.highlighted_song = self.songlist[self.highlighted_song_index]

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        if event.option_list.id == "music-library":
            selected_song_index = event.option_index
            option = event.option_list.get_option_at_index(selected_song_index)
            self.mark_selected(event.option_list, option)
            self.selected_song = self.songlist[selected_song_index]
            self.notify(f"Selected song {selected_song_index}: {self.selected_song}")

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Footer()
        with Container(id="music-container"):
            yield ProgressBar(100, id="progress-song-bar")
            with Horizontal(id="music-columns"):
                yield OptionList(id="music-library")
                yield OptionList(id="playlist")
            with Horizontal(id="table-columns"):
                yield DataTable(id="table-library")
                yield DataTable(id="table-playlist")

            # with Horizontal(id="songinfo"):
            # yield Label("selected", id="selected-song-name")
            # yield Rule(orientation="vertical")
            # yield Label("playlist", id="playlist-song-name")

    def on_mount(self):
        mixer.init()
        self.action_load_songs()
        self.poll_timer = self.set_interval(1, self.poll_pygame_music)

    def play_song(self, filePath: Path, start_pos: float = 0):
        try:
            sound = Sound(filePath)
        except PyGameError:
            self.notify(f"Song {filePath} unable to play")
            return
        self.song_duration = sound.get_length()
        pbar = self.query_one(ProgressBar)
        pbar.total = self.song_duration
        self.last_poll = -1
        music.fadeout(1000)
        music.load(filePath)
        music.play(start=start_pos, fade_ms=1000)

    def poll_pygame_music(self):
        pbar = self.query_one(ProgressBar)
        if music.get_busy():
            play_duration = float(music.get_pos()) / 1000.0
            try:
                self.query_one("#selected-song-name", Label).content = str(
                    int(play_duration)
                )
                self.query_one("#playlist-song-name", Label).content = str(
                    int(self.song_duration)
                )
            except NoMatches:
                pass
            pbar.total = self.song_duration
            pbar.progress = play_duration

        if self.current_track_index and self.playlist:
            for pevent in event.get():
                if pevent.type == MUSIC_END_EVENT:
                    self.current_track_index = (self.current_track_index + 1) % len(
                        self.playlist
                    )
                    music.load(self.playlist[self.current_track_index])
                    music.play(fade_ms=1000)

    def action_play_song(self) -> None:
        if self.selected_song:
            self.play_song(self.selected_song, 0.0)
        else:
            self.notify("Please select a song")

    def action_load_songs(self):
        if not config.get("library"):
            self.notify("No library set")
            return
        else:
            self.songlist = [
                song for song in Path(config["library"]).rglob("*.*") if song.is_file()
            ]

        ol = self.query_one("#music-library", OptionList)
        song_list = []
        song_list = [song.stem for song in self.songlist]
        song_rows = []
        for song in self.songlist:
            album = song.parent.stem
            song = song.stem
            song_rows.append([album, song])

        table_songs = self.query_one("#table-library", DataTable)
        table_songs.add_column("album")
        table_songs.add_column("song")
        for row in song_rows:
            table_songs.add_row(*row)
        # ol.add_rows(song_rows)
        for row in song_list:
            try:
                ol.add_option(Option(row, id=str(hash(row))))
            except ValueError as e:
                log.error(f"{row}: {e}")
            except DuplicateID:
                log.warning(f"{row} already exists with hash {hash(row)}")

    def action_add_song(self):
        # ol = self.query_one("#playlist", OptionList)
        ol = self.query_one("#playlist", OptionList)
        if self.highlighted_song:
            # ol.add_option(Option((self.highlighted_song.parent.stem, self.highlighted_song.stem)))
            ol.add_option(Option(self.highlighted_song.stem))
            # ol.add_option(Option(self.highlighted_song.stem))
        else:
            self.notify("No highlighted song")
