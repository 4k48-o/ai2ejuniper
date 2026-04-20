"""Prometheus-compatible metrics endpoint."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from juniper_ai.app.metrics import render_metrics

router = APIRouter()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(
        content=render_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
