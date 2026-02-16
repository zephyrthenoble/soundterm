from pydantic import Field, FilePath, DirectoryPath
from os import PathLike
from pathlib import Path


from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE: PathLike = Path(".env")
DEFAULT_ENV_FILE_ENCODING: str = "utf-8"
DEFAULT_ENV_PREFIX: str = "SOUNDTERM_"
DEFAULT_DATABASE_PATH: PathLike = Path.home() / ".soundterm" / "database.db"
DEFAULT_MUSIC_DIR: PathLike = Path.home() / "Music"
DEFAULT_FPCALC_PATH: PathLike = Path("/usr/bin/fpcalc")
PARSE_CLI_ARGS: bool = True
DEFAULT_ERROR_FILE_PATH: PathLike = Path("cache/error_files.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding=DEFAULT_ENV_FILE_ENCODING,
        env_prefix=DEFAULT_ENV_PREFIX,
        cli_parse_args=PARSE_CLI_ARGS,
    )
    database: PathLike = Field(default=DEFAULT_DATABASE_PATH)
    error_file: PathLike = Field(default=DEFAULT_ERROR_FILE_PATH)
    music_dir: DirectoryPath = Field(default=DEFAULT_MUSIC_DIR)
    fpcalc: FilePath = Field(default=DEFAULT_FPCALC_PATH)
    file: FilePath | None = Field(default=None)

    def model_post_init(self, __context: object) -> None:
        self.database = Path(self.database)
        self.error_file = Path(self.error_file)
        self.music_dir = Path(self.music_dir)
        self.fpcalc = Path(self.fpcalc)
        if not self.database.parent.exists():
            self.database.parent.mkdir(parents=True, exist_ok=True)
        if not self.music_dir.exists():
            raise ValueError(f"Music directory {self.music_dir} does not exist.")


print(Settings().model_dump())  # type: ignore
