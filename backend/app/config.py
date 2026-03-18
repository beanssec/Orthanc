from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://orthanc:orthanc_dev@postgres:5432/orthanc"
    JWT_SECRET: str = "change-me-to-a-random-string"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours
    ENCRYPTION_KEY: str = "change-me-to-a-random-string"
    CORS_ORIGINS: str = "*"

    # Feature flags
    NARRATIVE_TRACKERS_ENABLED: bool = False

    # Narrative lifecycle
    NARRATIVE_STALE_TTL_HOURS: int = 48  # Mark narrative stale after N hours of no new posts


settings = Settings()
