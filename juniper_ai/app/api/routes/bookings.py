"""Booking endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.api.middleware.auth import AuthContext, get_auth_context
from juniper_ai.app.api.schemas.responses import BookingResponse
from juniper_ai.app.db.models import Booking, User
from juniper_ai.app.db.session import get_db

router = APIRouter()


@router.get("/bookings", response_model=list[BookingResponse])
async def list_bookings(
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """List all bookings for the authenticated user."""
    result = await db.execute(
        select(Booking).join(User).where(
            User.external_id == auth.user_id
        ).order_by(Booking.created_at.desc())
    )
    bookings = result.scalars().all()
    return [
        BookingResponse(
            id=b.id,
            juniper_booking_id=b.juniper_booking_id,
            status=b.status.value,
            hotel_name=b.hotel_name,
            check_in=b.check_in,
            check_out=b.check_out,
            total_price=b.total_price,
            currency=b.currency,
            created_at=b.created_at,
        )
        for b in bookings
    ]


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific booking by ID."""
    result = await db.execute(
        select(Booking).join(User).where(
            Booking.id == booking_id,
            User.external_id == auth.user_id,
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    return BookingResponse(
        id=booking.id,
        juniper_booking_id=booking.juniper_booking_id,
        status=booking.status.value,
        hotel_name=booking.hotel_name,
        check_in=booking.check_in,
        check_out=booking.check_out,
        total_price=booking.total_price,
        currency=booking.currency,
        created_at=booking.created_at,
    )
