from __future__ import annotations
from pydantic import Field, FilePath, DirectoryPath, BeforeValidator
from os import PathLike
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Annotated
from shutil import which
import os


DEFAULT_CONFIG_DIR = Path.home() / ".config" / ".soundterm"
DEFAULT_ERROR_FILE_PATH = DEFAULT_CONFIG_DIR / "cache" / "error_files.json"
DEFAULT_DATABASE_PATH = DEFAULT_CONFIG_DIR / "database.db"
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_ENV_FILE_ENCODING: str = "utf-8"
DEFAULT_ENV_PREFIX: str = "SOUNDTERM_"
DEFAULT_MUSIC_DIR = Path.home() / "Music"
DEFAULT_FPCALC_PATH = "fpcalc"
PARSE_CLI_ARGS: bool = True
CLI_IMPLICIT_FLAGS: bool = True
DEFAULT_SCORE_THRESHOLD: float = 0.7
DEFAULT_TIMEOUT: int = 30


def get_settings() -> Settings:
    return Settings()  # type: ignore


def pathlike_to_path(value: PathLike) -> Path:
    return Path(value)


def valid_potential_file(value: PathLike) -> Path:
    path = Path(value)
    if path.exists() and not path.is_file():
        raise FileNotFoundError(f"Path '{value}' exists but is not a file.")
    if not path.parent.exists():
        raise FileNotFoundError(
            f"Directory '{path.parent}' for potential file '{value}' does not exist."
        )
    return path


def check_executable_in_path(value: str | PathLike) -> Path:
    # use shutil.which to check if the executable is in PATH
    path = which(str(value))
    if not path:
        exe_path = Path(value).resolve()
        if not exe_path.is_file():
            raise FileNotFoundError(f"Path '{value}' does not exist or is not a file.")
        if not os.access(exe_path, os.X_OK):
            raise FileNotFoundError(f"File '{value}' is not executable.")

        # If the executable is found at the given path, add its parent directory to PATH if it's not already there
        if exe_path.parent and str(exe_path.parent) not in os.environ["PATH"]:
            os.environ["PATH"] += os.pathsep + str(exe_path.parent)
        stem = exe_path.stem
        # Check again if the executable can be found in PATH after adding its directory
        path = which(stem)
        if not path:
            raise FileNotFoundError(f"Executable '{value}' not found in system PATH.")
    return Path(path)


def existing_file_or_none(value: str) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"File '{value}' not found.")
    return path


def existing_file(value: PathLike) -> Path:
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"File '{value}' not found.")
    return path


# A file that may or may not exist, but if it does exist, it must be a file (not a directory)
# Files that will be created
PotentialFile = Annotated[Path, BeforeValidator(valid_potential_file)]

# Could be a path that exists, or an executable in PATH
ExecutablePath = Annotated[Path, BeforeValidator(check_executable_in_path)]

# This is for the command line option of a single file to process. It can be None (if not provided) or an existing file.
NoneOrSingleFile = Annotated[Path | None, BeforeValidator(existing_file_or_none)]

# Path must exist and be a file, not a directory
ExistingFile = Annotated[Path, BeforeValidator(existing_file)]


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

    # directory of this file needs to be created if it doesn't exist, but the file itself doesn't need to exist and will be created when writing to it
    database: PotentialFile = Field(default=DEFAULT_DATABASE_PATH)
    error_file: PotentialFile = Field(
        default=DEFAULT_ERROR_FILE_PATH, alias="error-file"
    )

    # must exist
    music_dir: DirectoryPath = Field(default=DEFAULT_MUSIC_DIR, alias="music-dir")

    # must exist and be executable, or be an executable in PATH
    fpcalc: ExecutablePath = Field(default=Path(DEFAULT_FPCALC_PATH))
    score_threshold: float = Field(
        default=DEFAULT_SCORE_THRESHOLD, alias="score-threshold"
    )
    timeout: int = Field(default=DEFAULT_TIMEOUT, alias="timeout")
    api_key: str = Field(alias="api-key", validation_alias="API_KEY")

    # only exists for the CLI single file mode, and must be an existing file if provided
    file: NoneOrSingleFile = Field(default=None)


if __name__ == "__main__":
    print(get_settings().model_dump())
