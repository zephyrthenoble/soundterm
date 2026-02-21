from __future__ import annotations
from sqlmodel import create_engine, Session


from soundterm.settings import get_settings


class SessionManager:
    def __init__(self, echo: bool = False):

        settings = get_settings()
        self.engine = create_engine(str(settings.database), echo=echo)

    def __enter__(self) -> Session:
        self.session = Session(self.engine)
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.session.close()

    @staticmethod
    def get_session(echo: bool = False) -> "SessionManager":
        return SessionManager(echo=echo)
