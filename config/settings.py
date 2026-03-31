from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="config/.env.local",
        extra="ignore",
    )

    # LLM
    OLLAMA_MODEL: str = "phi4-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # API fallback
    ANTHROPIC_API_KEY: str | None = None
    FALLBACK_ENABLED: bool = True
    FALLBACK_MODEL: str = "claude-haiku-4-5-20251001"

    # Game
    DIFFICULTY: str = "professional"

    # Voice — STT
    STT_MODEL: str = "base.en"
    WAKE_WORD: str = "oracle"
    MIC_DEVICE_NAME: str | None = None

    # Voice — TTS
    TTS_VOICE: str = "bm_fable"
    SPEAKER_DEVICE_NAME: str | None = None

    # Steam routing
    STEAM_ROUTE_DEVICE_NAME: str | None = None
    STEAM_ROUTE_GAIN: float = 1.0

    # Bidirectional
    LOOPBACK_ENABLED: bool = False
    LOOPBACK_DEVICE_NAME: str | None = None
    MIKE_SPEAKER_NAME: str = "Mike"
    KAYDEN_SPEAKER_NAME: str = "Kayden"

    # Paths
    DB_PATH: str = "config/ghost_database.yaml"
    SQLITE_PATH: str = "data/oracle_stats.db"
    SESSIONS_DIR: str = "sessions"


config = Settings()
