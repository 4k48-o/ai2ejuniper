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
    # Comma-separated; first key must match imToolTest `src/api/client.ts` default.
    api_keys: str = "test-api-key-1,test-api-key-2"

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

    # HotelAvail request advanced options — required by Juniper docs so that
    # HotelInfo (name / address / category) and CancellationPolicy come back
    # in the response, and so that @Context allows the supplier to route the
    # request through the correct availability pool (multi-hotel search =
    # FULLAVAIL, per-hotel detail = SINGLEAVAIL; see ``doc/juniper-hotel-api.md``
    # §Context). ``juniper_avail_timeout_ms`` maps to
    # ``AdvancedOptions/TimeOut`` — Juniper caps this at 8000 ms.
    juniper_avail_context: str = "FULLAVAIL"
    juniper_avail_show_hotel_info: bool = True
    juniper_avail_show_cancellation_policies: bool = True
    juniper_avail_show_only_available: bool = True
    juniper_avail_timeout_ms: int = 8000

    # HotelCheckAvail — docs recommend ``SINGLEAVAIL`` or ``VALUATION``
    # on the ``@Context`` attribute of ``HotelCheckAvailRQ``. Empty disables.
    juniper_check_avail_context: str = "SINGLEAVAIL"

    # HotelBookingRules — docs recommend ``VALUATION``, ``BOOKING``, or
    # ``PAYMENT`` on the ``@Context`` attribute of ``HotelBookingRulesRQ``
    # (see ``uploads/hotel-api-0.md`` §HotelBookingRules Request, line 2495).
    # This helps Juniper route the call through the valuation pool rather
    # than the availability one. Empty string disables the attribute.
    juniper_booking_rules_context: str = "VALUATION"

    # HotelBooking — ``@Context`` attribute on ``HotelBookingRQ``. Docs
    # recommend ``BOOKING`` (or ``PAYMENT`` when the call kicks off a
    # payment flow). Empty string disables the attribute.
    juniper_booking_context: str = "BOOKING"

    # HotelBooking price tolerance — fed into
    # ``HotelBookingInfo/Price/PriceRange/@Maximum`` as a percentage above
    # the total quoted by HotelBookingRules. 0.0 = strict (fail on any
    # upward drift); 0.02 = accept up to +2%. Minimum is always 0 (downward
    # drift can never fail the booking). Juniper rejects the booking if the
    # server-side price is outside this window.
    juniper_booking_price_tolerance_pct: float = 0.0

    # Conversations
    conversation_ttl_hours: int = 24
    max_message_history: int = 20  # DB fetch limit + agent_node tail window (env: MAX_MESSAGE_HISTORY)
    search_results_limit: int = 5

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


settings = Settings()
