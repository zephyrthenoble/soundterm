from __future__ import annotations
from sqlmodel import create_engine, Session, SQLModel


from soundterm.settings import get_settings


class SessionManager:
    def __init__(self, echo: bool = False):

        settings = get_settings()
        rm_database = True
        if rm_database and settings.database.exists():
            print(f"Removing existing database at {settings.database}...")
            settings.database.unlink()
        sqlite_url = f"sqlite:///{settings.database}"
        self.engine = create_engine(sqlite_url, echo=echo)
        print(f"Using database at {settings.database}")
        SQLModel.metadata.create_all(self.engine)

    def __enter__(self) -> Session:
        self.session = Session(self.engine)
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.session.close()

    @staticmethod
    def get_session(echo: bool = False) -> "SessionManager":
        return SessionManager(echo=echo)


def commit_if_dirty(session, instance) -> None:
    if instance in session.dirty:
        print(f"Instance {instance} is dirty. Committing to database.")
        session.add(instance)
        session.commit()
