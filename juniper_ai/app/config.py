from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database (pool: tune per env — workers × concurrent DB ops; see SQLAlchemy pool_size / max_overflow)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/juniper_ai"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Juniper API — default host matches Flicknmix / xml-uat (see scripts/test_juniper_sandbox.py)
    juniper_api_url: str = "https://xml-uat.bookingengine.es"
    juniper_email: str = ""
    juniper_password: str = ""
    juniper_use_mock: bool = True

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Auth
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    api_keys: str = "test-api-key"

    # Rate Limiting
    rate_limit_user: int = 60
    rate_limit_api_key: int = 300

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Static data sync
    static_data_sync_interval_days: int = 15
    hotel_portfolio_page_size: int = 500

    # HotelAvail batching — Juniper UAT requires HotelCodes instead of
    # DestinationZone (REQ_PRACTICE, ticket 1096690). Availability is now
    # fetched in parallel batches of JPCodes resolved from the local cache.
    hotel_avail_batch_size: int = 25
    hotel_avail_batch_concurrency: int = 3
    hotel_avail_max_candidates: int = 200

    # Conversations
    conversation_ttl_hours: int = 24
    max_message_history: int = 20  # DB fetch limit + agent_node tail window (env: MAX_MESSAGE_HISTORY)
    search_results_limit: int = 5

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


settings = Settings()
