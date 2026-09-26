from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CurtaiLess API"
    app_env: str = "local"
    cors_origins: str = "http://localhost:5173"
    api_gateway_base_path: str = "/"
    aws_region: str = "us-east-1"
    data_bucket: str | None = None
    scenarios_table: str | None = None
    bedrock_model_id: str = "us.anthropic.claude-opus-5"
    bedrock_fallback_model_id: str = "us.anthropic.claude-sonnet-5"
    bedrock_emergency_model_id: str = "amazon.nova-pro-v1:0"
    bedrock_knowledge_base_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
