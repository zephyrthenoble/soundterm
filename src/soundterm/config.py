from typing import Any
from pathlib import Path

from platformdirs import PlatformDirs
import tomlkit

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

debug = {}
