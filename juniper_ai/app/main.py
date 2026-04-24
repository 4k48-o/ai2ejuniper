import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from juniper_ai.app.api.routes import bookings, conversations, health, metrics, preferences, webhooks
from juniper_ai.app.api.middleware.rate_limit import check_rate_limit
from juniper_ai.app.api.middleware.request_id import RequestIDMiddleware, RequestIdFilter
from juniper_ai.app.config import settings
from juniper_ai.app.db.session import engine


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s] %(message)s",
        )
    )
    handler.addFilter(RequestIdFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


_configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting JuniperAI server (env=%s, llm=%s)", settings.app_env, settings.llm_provider)
    if settings.juniper_use_mock:
        logger.info("Juniper supplier: MOCK (no outbound SOAP; use for IM/offline dev)")
    else:
        logger.info(
            "Juniper supplier: LIVE SOAP → %s (IM/local dev: set JUNIPER_USE_MOCK=true to skip UAT)",
            settings.juniper_api_url,
        )
    yield
    await engine.dispose()
    logger.info("JuniperAI server shutdown")


app = FastAPI(
    title="JuniperAI",
    description="AI-powered hotel booking agent",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.app_env == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(RequestIDMiddleware)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(metrics.router, tags=["metrics"])
app.include_router(
    conversations.router,
    prefix="/api/v1",
    tags=["conversations"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    bookings.router,
    prefix="/api/v1",
    tags=["bookings"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    preferences.router,
    prefix="/api/v1",
    tags=["preferences"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    webhooks.router,
    prefix="/api/v1",
    tags=["webhooks"],
    dependencies=[Depends(check_rate_limit)],
)
