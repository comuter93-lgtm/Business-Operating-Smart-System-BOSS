from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    boss_app_name: str = "BOSS — Business Operating Smart System"
    boss_env: str = "development"
    boss_require_auth: bool = True
    database_url: str = "sqlite:///./boss.db"

    boss_secret_key: str = "dev-only-insecure-secret-change-in-production-64-chars-minimum"
    boss_session_ttl_hours: int = 12
    boss_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    boss_storage_dir: str = "./storage_data"
    boss_backup_dir: str = "./backups"

    boss_business_name: str = "AquaFlow Pumps & Spares India"
    boss_home_state: str = "DL"
    boss_gstin: str = "07AABCA1234F1Z5"

    # Integration credentials — remain blank unless explicitly configured
    amazon_sp_client_id: str = ""
    amazon_sp_client_secret: str = ""
    amazon_sp_refresh_token: str = ""
    flipkart_app_id: str = ""
    flipkart_app_secret: str = ""
    busy_bridge_endpoint: str = ""
    whatsapp_otp_provider_url: str = ""
    whatsapp_otp_api_token: str = ""

    # Rate limit settings
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    @property
    def storage_path(self) -> Path:
        p = Path(self.boss_storage_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def backup_path(self) -> Path:
        p = Path(self.boss_backup_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.boss_allowed_origins.split(",") if o.strip()]


settings = Settings()

