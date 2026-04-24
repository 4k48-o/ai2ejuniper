"""Conversation and message endpoints — the core of the agent API."""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from juniper_ai.app.api.middleware.auth import AuthContext, get_auth_context
from juniper_ai.app.api.schemas.requests import CreateConversationRequest, SendMessageRequest
from juniper_ai.app.api.schemas.responses import ConversationResponse, MessageResponse
from juniper_ai.app.config import settings
from juniper_ai.app.db.models import (
    Booking,
    BookingStatus,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    User,
)
from juniper_ai.app.db.session import get_db
from juniper_ai.app.services.booking_persist import persist_booking_record
from juniper_ai.app.services.users import get_or_create_user_by_external_id
from juniper_ai.app.webhooks.dispatcher import dispatch_event

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_or_create_user(db: AsyncSession, external_id: str) -> User:
    """Get or create a user by external ID."""
    return await get_or_create_user_by_external_id(db, external_id)


_BOOKING_DATA_PATTERN = re.compile(r"__BOOKING_DATA__(.+?)__END_BOOKING_DATA__", re.DOTALL)
_BOOKING_EVENT_PATTERN = re.compile(r"__BOOKING_EVENT__(.+?)__END_BOOKING_EVENT__", re.DOTALL)


def _extract_booking_data(messages: list) -> list[dict]:
    """Extract booking data dicts from tool messages in the agent result."""
    bookings = []
    for msg in messages:
        # Handle both message objects and raw strings (from on_tool_end events)
        if isinstance(msg, str):
            content = msg
        else:
            content = getattr(msg, "content", None)
        if not content or not isinstance(content, str):
            continue
        for match in _BOOKING_DATA_PATTERN.finditer(content):
            try:
                data = json.loads(match.group(1))
                if data.get("__booking__"):
                    bookings.append(data)
            except (json.JSONDecodeError, AttributeError):
                continue
    return bookings


def _extract_booking_events(messages: list) -> list[dict]:
    """Extract booking event payloads from tool messages in the agent result."""
    events = []
    for msg in messages:
        if isinstance(msg, str):
            content = msg
        else:
            content = getattr(msg, "content", None)
        if not content or not isinstance(content, str):
            continue
        for match in _BOOKING_EVENT_PATTERN.finditer(content):
            try:
                data = json.loads(match.group(1))
                if data.get("__booking_event__") and data.get("event_type"):
                    events.append(data)
            except (json.JSONDecodeError, AttributeError):
                continue
    return events


async def _load_recent_messages_for_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    limit: int,
) -> list[Message]:
    """Load the most recent `limit` messages in chronological order (oldest first).

    Avoids full-table scans for long conversations; aligns with ``graph.agent_node``
    truncation using :attr:`settings.max_message_history`.
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def _persist_booking(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    booking_data: dict,
) -> None:
    """Persist a booking to the database with idempotency protection."""
    await persist_booking_record(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        booking_data=booking_data,
    )


async def _apply_booking_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    booking_event: dict,
) -> None:
    """Apply booking.cancelled / booking.modified events to persisted bookings."""
    event_type = booking_event.get("event_type")
    juniper_booking_id = booking_event.get("booking_id")
    if not event_type or not juniper_booking_id:
        return

    result = await db.execute(
        select(Booking).where(
            Booking.user_id == user_id,
            Booking.juniper_booking_id == juniper_booking_id,
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        return

    if event_type == "booking.cancelled":
        booking.status = BookingStatus.cancelled
    elif event_type == "booking.modified":
        booking.status = BookingStatus.modified
        if booking_event.get("check_in"):
            booking.check_in = booking_event["check_in"]
        if booking_event.get("check_out"):
            booking.check_out = booking_event["check_out"]
    else:
        return

    try:
        await dispatch_event(
            db=db,
            event_type=event_type,
            booking_id=str(booking.id),
            booking_details={
                "juniper_booking_id": booking.juniper_booking_id,
                "hotel_name": booking.hotel_name,
                "check_in": booking.check_in,
                "check_out": booking.check_out,
                "total_price": booking.total_price,
                "currency": booking.currency,
                "status": booking.status.value,
            },
        )
    except Exception:
        logger.error("Failed to dispatch %s webhook", event_type, exc_info=True)


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation session."""
    user = await _get_or_create_user(db, request.external_user_id)

    conversation = Conversation(
        user_id=user.id,
        status=ConversationStatus.active,
        state={},
        language="en",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.conversation_ttl_hours),
    )
    db.add(conversation)
    await db.flush()

    logger.info("Created conversation %s for user %s", conversation.id, user.external_id)
    return ConversationResponse(
        id=conversation.id,
        user_id=user.id,
        status=conversation.status.value,
        language=conversation.language,
        created_at=conversation.created_at,
    )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: uuid.UUID,
    request: SendMessageRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to the agent and get a response."""
    # For API key auth, require X-External-User-Id header
    if auth.auth_type == "api_key" and not auth.external_user_id:
        raise HTTPException(
            status_code=400,
            detail="X-External-User-Id header is required for API key authentication",
        )

    # Load conversation with user scope — always enforce ownership
    result = await db.execute(
        select(Conversation).join(User).where(
            Conversation.id == conversation_id,
            User.external_id == auth.user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check expiry
    if conversation.is_expired:
        conversation.status = ConversationStatus.expired
        await db.flush()
        raise HTTPException(status_code=410, detail="Conversation expired. Please create a new one.")

    # Save user message
    user_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.user,
        content=request.content,
    )
    db.add(user_message)

    # Load user preferences
    user_result = await db.execute(select(User).where(User.id == conversation.user_id))
    user = user_result.scalar_one()

    # Load message history (recent N only; current user row not flushed yet)
    db_messages = await _load_recent_messages_for_conversation(
        db, conversation.id, settings.max_message_history
    )

    # Convert to LangChain messages
    lc_messages = []
    for msg in db_messages:
        if msg.role == MessageRole.user:
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == MessageRole.assistant:
            lc_messages.append(AIMessage(content=msg.content))

    # Add current message
    lc_messages.append(HumanMessage(content=request.content))

    # Run agent
    result_messages = []
    try:
        from juniper_ai.app.agent.graph import agent_graph

        result_state = await agent_graph.ainvoke(
            {
                "messages": lc_messages,
                "user_id": str(user.id),
                "conversation_id": str(conversation.id),
                "preferences": user.preferences or {},
                "language": conversation.language or "en",
            },
            config={"recursion_limit": 25, "configurable": {"user_id": str(user.id)}},
        )

        result_messages = result_state.get("messages", [])

        # Extract the last AI message
        ai_messages = [m for m in result_messages if isinstance(m, AIMessage)]
        if ai_messages:
            last_ai = ai_messages[-1]
            response_text = last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)
        else:
            response_text = "I'm sorry, I couldn't process your request. Could you please try again?"

    except Exception as e:
        logger.error("Agent error in conversation %s: %s", conversation_id, e, exc_info=True)
        response_text = "I'm experiencing a temporary issue. Please try again in a moment."

    # Check for booking data in tool messages and persist to database
    for booking_data in _extract_booking_data(result_messages):
        await _persist_booking(
            db=db,
            user_id=user.id,
            conversation_id=conversation.id,
            booking_data=booking_data,
        )
    for booking_event in _extract_booking_events(result_messages):
        await _apply_booking_event(
            db=db,
            user_id=user.id,
            booking_event=booking_event,
        )

    # Save assistant message
    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=response_text,
    )
    db.add(assistant_message)

    # Update conversation timestamp
    conversation.updated_at = datetime.now(timezone.utc)
    conversation.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.conversation_ttl_hours)

    return MessageResponse(
        text=response_text,
        data=None,
        status="idle",
    )


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Events message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: uuid.UUID,
    request: SendMessageRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to the agent and stream the response via SSE."""
    # For API key auth, require X-External-User-Id header
    if auth.auth_type == "api_key" and not auth.external_user_id:
        raise HTTPException(
            status_code=400,
            detail="X-External-User-Id header is required for API key authentication",
        )

    # Load conversation with user scope — always enforce ownership
    result = await db.execute(
        select(Conversation).join(User).where(
            Conversation.id == conversation_id,
            User.external_id == auth.user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check expiry
    if conversation.is_expired:
        conversation.status = ConversationStatus.expired
        await db.flush()
        raise HTTPException(status_code=410, detail="Conversation expired. Please create a new one.")

    # Save user message
    user_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.user,
        content=request.content,
    )
    db.add(user_message)

    # Load user preferences
    user_result = await db.execute(select(User).where(User.id == conversation.user_id))
    user = user_result.scalar_one()

    # Load message history (recent N only; current user row not flushed yet)
    db_messages = await _load_recent_messages_for_conversation(
        db, conversation.id, settings.max_message_history
    )

    # Convert to LangChain messages
    lc_messages = []
    for msg in db_messages:
        if msg.role == MessageRole.user:
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == MessageRole.assistant:
            lc_messages.append(AIMessage(content=msg.content))

    # Add current message
    lc_messages.append(HumanMessage(content=request.content))

    # Capture state needed by the generator (db session stays open for StreamingResponse)
    user_id = user.id
    user_preferences = user.preferences or {}
    conv_language = conversation.language or "en"

    async def event_generator() -> AsyncGenerator[str, None]:
        """Stream SSE events from the agent graph."""
        from juniper_ai.app.agent.graph import agent_graph

        full_text = ""
        result_messages = []

        try:
            yield _sse_event("status", {"status": "thinking"})

            input_state = {
                "messages": lc_messages,
                "user_id": str(user_id),
                "conversation_id": str(conversation_id),
                "preferences": user_preferences,
                "language": conv_language,
            }

            async for event in agent_graph.astream_events(
                input_state, version="v2", config={"recursion_limit": 25, "configurable": {"user_id": str(user_id)}}
            ):
                kind = event.get("event", "")

                if kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield _sse_event("status", {"status": "calling_tool", "tool": tool_name})

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        content = chunk.content
                        if isinstance(content, str):
                            full_text += content
                            yield _sse_event("token", {"text": content})

                elif kind == "on_tool_end":
                    output = event.get("data", {}).get("output")
                    if output:
                        result_messages.append(output)

                elif kind == "on_chat_model_end":
                    output = event.get("data", {}).get("output")
                    if output and isinstance(output, AIMessage):
                        result_messages.append(output)

            # Determine final response text
            if full_text:
                response_text = full_text
            elif result_messages:
                last_ai = result_messages[-1]
                response_text = last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)
            else:
                response_text = "I'm sorry, I couldn't process your request. Could you please try again?"

            yield _sse_event("done", {"text": response_text})

        except Exception as e:
            logger.error("Stream error in conversation %s: %s", conversation_id, e, exc_info=True)
            yield _sse_event("error", {"error": "I'm experiencing a temporary issue. Please try again in a moment."})
            response_text = "I'm experiencing a temporary issue. Please try again in a moment."
            result_messages = []

        # Persist bookings from tool messages
        for booking_data in _extract_booking_data(result_messages):
            await _persist_booking(
                db=db,
                user_id=user_id,
                conversation_id=conversation.id,
                booking_data=booking_data,
            )
        for booking_event in _extract_booking_events(result_messages):
            await _apply_booking_event(
                db=db,
                user_id=user_id,
                booking_event=booking_event,
            )

        # Save assistant message
        assistant_message = Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=response_text,
        )
        db.add(assistant_message)

        # Update conversation timestamp
        conversation.updated_at = datetime.now(timezone.utc)
        conversation.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.conversation_ttl_hours)
        await db.flush()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation status and details."""
    # For API key auth, require X-External-User-Id header
    if auth.auth_type == "api_key" and not auth.external_user_id:
        raise HTTPException(
            status_code=400,
            detail="X-External-User-Id header is required for API key authentication",
        )

    # Enforce ownership — scope by authenticated user
    result = await db.execute(
        select(Conversation).join(User).where(
            Conversation.id == conversation_id,
            User.external_id == auth.user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.is_expired:
        conversation.status = ConversationStatus.expired

    return ConversationResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        status=conversation.status.value,
        language=conversation.language,
        created_at=conversation.created_at,
    )
