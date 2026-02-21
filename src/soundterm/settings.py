from pydantic import Field, FilePath, DirectoryPath
from os import PathLike
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Annotated
from shutil import which

type ConfigFileType = PathLike
type ExecutablePathType = PathLike

DEFAULT_CONFIG_DIR: PathLike = Path.home() / ".config" / ".soundterm"
DEFAULT_ERROR_FILE_PATH: ConfigFileType = (
    DEFAULT_CONFIG_DIR / "cache" / "error_files.json"
)
DEFAULT_DATABASE_PATH: ConfigFileType = DEFAULT_CONFIG_DIR / "database.db"
DEFAULT_ENV_FILE: ConfigFileType = Path(".env")
DEFAULT_ENV_FILE_ENCODING: str = "utf-8"
DEFAULT_ENV_PREFIX: str = "SOUNDTERM_"
DEFAULT_MUSIC_DIR: PathLike = Path.home() / "Music"
DEFAULT_FPCALC_PATH: ExecutablePathType = Path("fpcalc")
PARSE_CLI_ARGS: bool = True
CLI_IMPLICIT_FLAGS: bool = True
DEFAULT_SCORE_THRESHOLD = 0.7
DEFAULT_TIMEOUT = 30


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding=DEFAULT_ENV_FILE_ENCODING,
        env_prefix=DEFAULT_ENV_PREFIX,
        cli_parse_args=PARSE_CLI_ARGS,
        cli_implicit_flags=CLI_IMPLICIT_FLAGS,
    )
    analyze_song: bool = Field(default=False, alias="analyze-song", flag=True)
    make_dirs: bool = Field(default=False, alias="make-dirs", flag=True)
    force_make_dirs: bool = Field(default=False, alias="force-make-dirs")
    database: Annotated[ConfigFileType, Field(default=DEFAULT_DATABASE_PATH)]
    error_file: Annotated[
        ConfigFileType, Field(default=DEFAULT_ERROR_FILE_PATH, alias="error-file")
    ]
    music_dir: Annotated[
        DirectoryPath, Field(default=DEFAULT_MUSIC_DIR, alias="music-dir")
    ]
    fpcalc: Annotated[ExecutablePathType, Field(default=DEFAULT_FPCALC_PATH)]
    score_threshold: float = Field(
        default=DEFAULT_SCORE_THRESHOLD, alias="score-threshold"
    )
    timeout: int = Field(default=DEFAULT_TIMEOUT, alias="timeout")
    api_key: str = Field(alias="api-key", validation_alias="API_KEY")
    file: FilePath | None = Field(default=None)

    def model_post_init(self, __context: object) -> None:
        for field_name, field_info in self.model_fields.items():
            value = getattr(self, field_name)
            if isinstance(value, PathLike):
                original_type = field_info.annotation
                # print(f"[Settings] Original type of '{field_name}': {original_type}")
                setattr(self, field_name, Path(value))
                value = getattr(self, field_name)
                assert isinstance(value, Path)
                if original_type is ExecutablePathType:
                    if not which(str(value)):
                        raise FileNotFoundError(
                            f"Executable '{value}' for field '{field_name}' not found in system PATH."
                        )
                    else:
                        continue

                test_to_make_dir = (
                    value.parent if original_type is ConfigFileType else value
                )
                if not test_to_make_dir.exists():
                    if self.make_dirs:
                        if not self.force_make_dirs:
                            confirm = (
                                input(
                                    f"Directory {test_to_make_dir} for path '{field_name}' does not exist. Do you want to create it? (y/n): "
                                )
                                .strip()
                                .lower()
                            )
                            if confirm != "y":
                                raise FileNotFoundError(
                                    f"Directory {test_to_make_dir} does not exist. User declined to create it."
                                )
                        print(
                            f"[Settings] Converting '{field_name}' to Path: {value} -> {Path(value)}"
                        )
                        test_to_make_dir.mkdir(parents=True, exist_ok=True)
                    else:
                        raise FileNotFoundError(
                            f"Directory {test_to_make_dir} does not exist. Set make-dirs=True to create it automatically."
                        )


if __name__ == "__main__":
    print(Settings().model_dump())  # type: ignore
