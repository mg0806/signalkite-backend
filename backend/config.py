from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_redirect_url: str = "http://localhost:8000/auth/kite/callback"
    database_url: str = "postgresql+psycopg2://user:pass@localhost:5432/signalkite"
    redis_url: str = "redis://localhost:6379"
    fcm_server_key: str = ""
    jwt_secret: str = "change-me"
    broker_token_encryption_key: str = ""
    frontend_redirect_url: str = "signalkite://auth/success"
    cors_origins: str = "http://localhost:8081,http://127.0.0.1:8081"
    scheduler_enabled: bool = True
    worker_poll_seconds: int = 300
    db_auto_create: bool = False
    whatsapp_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    email_webhook_url: str = ""
    alert_email_to: str = ""
    sms_webhook_url: str = ""
    alert_phone_to: str = ""
    textlocal_api_key: str = ""
    textlocal_sender: str = "TXTLCL"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    rate_limit_per_minute: int = 120
    metrics_enabled: bool = True
    sentry_dsn: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8-sig")

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "local"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
