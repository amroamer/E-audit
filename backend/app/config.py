from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EAUDIT_", extra="ignore")

    database_url: str = "postgresql+psycopg2://eaudit:eaudit@localhost:5433/eaudit"
    cors_origins: str = "http://localhost:5173"
    claude_model: str = "claude-opus-5"
    # AI layer (Phase 2)
    llm_disabled: bool = False              # EAUDIT_LLM_DISABLED
    allow_hosted_egress: bool = False       # EAUDIT_ALLOW_HOSTED_EGRESS (real-data escape hatch)
    data_is_synthetic: bool = True          # EAUDIT_DATA_IS_SYNTHETIC
    anthropic_base_url: str | None = None   # prod: in-VPC gateway (the ONLY swap point)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
