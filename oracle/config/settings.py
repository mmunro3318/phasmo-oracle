"""Oracle configuration — loaded from .env.local or environment."""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DIFFICULTY: str = "professional"
    DB_PATH: str = str(Path(__file__).parent / "ghost_database.yaml")
    SYNONYMS_PATH: str = str(Path(__file__).parent / "evidence_synonyms.yaml")
    GHOST_TESTS_PATH: str = str(Path(__file__).parent / "ghost_tests.yaml")
    SESSIONS_DIR: str = str(Path(__file__).parent.parent.parent / "sessions")

    model_config = {"env_file": ".env.local", "extra": "ignore"}


config = Settings()
