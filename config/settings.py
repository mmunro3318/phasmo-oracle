from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_DIR = Path(__file__).parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_CONFIG_DIR / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    DIFFICULTY: str = "professional"
    DB_PATH: str = str(_CONFIG_DIR / "ghost_database.yaml")
    SYNONYMS_PATH: str = str(_CONFIG_DIR / "evidence_synonyms.yaml")


config = Settings()
