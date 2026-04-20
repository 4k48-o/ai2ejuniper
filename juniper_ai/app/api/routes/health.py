"""Health check endpoint."""

from fastapi import APIRouter

from juniper_ai.app.api.schemas.responses import HealthResponse
from juniper_ai.app.config import settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        environment=settings.app_env,
    )
