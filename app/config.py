"""Application configuration"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""

    # Database
    database_url: str = "sqlite:///./issuebridge.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Sync
    default_sync_interval_minutes: int = 10
    # Comma-separated allowlist of issue fields to sync (global; applies to all project pairs).
    # If empty/omitted, the service uses its built-in default set.
    #
    # Example: "title,description,labels,assignees,comments"
    sync_fields: str | None = None

    # Logging
    log_level: str = "INFO"

    # Auth (optional)
    # When enabled, all routes (UI, API, docs, static) are protected by HTTP Basic auth,
    # except for /health.
    auth_enabled: bool = False
    auth_username: str | None = None
    auth_password: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
