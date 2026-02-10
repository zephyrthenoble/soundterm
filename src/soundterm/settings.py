from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "SoundTerm"
    debug_mode: bool = False
    database: str = r"D:\projects\soundterm\soundterm.db"
    song_library: str = r"C:\Users\zephy\Music"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
