"""Tests for Conversation API routes."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, ToolMessage

from juniper_ai.app.api.middleware.auth import AuthContext
from juniper_ai.app.db.models import Booking, BookingStatus, ConversationStatus, Message, MessageRole, User
from juniper_ai.app.main import app


def _jwt_headers(user_id: str = "test-user") -> dict:
    """Build Authorization header using a valid JWT."""
    import time
    from jose import jwt
    from juniper_ai.app.config import settings

    token = jwt.encode(
        {"sub": user_id, "exp": int(time.time()) + 3600},
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _api_key_headers(external_user_id: str | None = None) -> dict:
    """Build API key headers."""
    from juniper_ai.app.config import settings

    headers = {"X-API-Key": settings.api_keys_list[0]}
    if external_user_id:
        headers["X-External-User-Id"] = external_user_id
    return headers


# We mock the database session for all conversation tests.
# The approach: override the get_db and get_auth_context dependencies.


def _fake_user(external_id: str = "test-user"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.external_id = external_id
    user.preferences = {}
    return user


def _parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    """Parse `text/event-stream` body into (event_name, data_dict) pairs."""
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name: str | None = None
        data_payload: str | None = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_payload = line.removeprefix("data:").strip()
        if event_name and data_payload:
            events.append((event_name, json.loads(data_payload)))
    return events


def _fake_conversation(user_id: uuid.UUID, expired: bool = False):
    conv = MagicMock()
    conv.id = uuid.uuid4()
    conv.user_id = user_id
    conv.status = MagicMock(value="active")
    conv.language = "en"
    conv.created_at = datetime.now(timezone.utc)
    conv.updated_at = datetime.now(timezone.utc)
    if expired:
        conv.is_expired = True
        conv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    else:
        conv.is_expired = False
        conv.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    return conv


@pytest.mark.asyncio
async def test_create_conversation_returns_200():
    user = _fake_user()

    mock_db = AsyncMock()
    # For _get_or_create_user: execute returns a result with scalar_one_or_none
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute = AsyncMock(return_value=mock_result)
    def _add_side_effect(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    mock_db.add = MagicMock(side_effect=_add_side_effect)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/conversations",
                json={"external_user_id": "test-user"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_conversation_missing_external_user_id_returns_422():
    """CONV-04: request body must include external_user_id (Pydantic)."""
    auth = AuthContext(user_id="test-user", auth_type="jwt")
    mock_db = AsyncMock()
    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/conversations", json={})
        assert response.status_code == 422
        body = response.json()
        assert "detail" in body
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_or_create_user_inserts_new_user():
    """CONV-03: first seen external_id creates a User row (flush assigns id)."""
    from juniper_ai.app.api.routes.conversations import _get_or_create_user

    created: User | None = None

    def capture_add(obj):
        nonlocal created
        if isinstance(obj, User):
            created = obj
            obj.id = uuid.uuid4()

    db = AsyncMock()
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=lookup)
    db.add = MagicMock(side_effect=capture_add)
    db.flush = AsyncMock()

    user = await _get_or_create_user(db, "brand-new-ext-42")

    assert user is created
    assert user.external_id == "brand-new-ext-42"
    assert user.id is not None
    db.add.assert_called()
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_get_or_create_user_reuses_same_user_for_same_external_id():
    """CONV-02: repeated external_id returns the same User row (same id) without a second User insert."""
    from juniper_ai.app.api.routes.conversations import _get_or_create_user

    stored: User | None = None

    async def execute_side_effect(*_a, **_kw):
        r = MagicMock()
        r.scalar_one_or_none.return_value = stored
        return r

    def add_side_effect(obj):
        nonlocal stored
        if isinstance(obj, User):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            stored = obj

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.add = MagicMock(side_effect=add_side_effect)
    db.flush = AsyncMock()

    first = await _get_or_create_user(db, "same-ext")
    second = await _get_or_create_user(db, "same-ext")

    assert first is second
    assert first.id == second.id
    user_adds = [c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], User)]
    assert len(user_adds) == 1


@pytest.mark.asyncio
async def test_send_message_returns_200():
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    # First call: select Conversation join User
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    # Second call: select User by id
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    # Third call: select Messages
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "messages": [AIMessage(content="Here are some hotels for you!")]
        })
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "Find hotels in Barcelona"},
                )
        assert response.status_code == 200
        data = response.json()
        assert "text" in data
        assert data["status"] == "idle"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_content_over_5000_chars_returns_422():
    """CONV-09: SendMessageRequest max_length=5000."""
    auth = AuthContext(user_id="test-user", auth_type="jwt")
    mock_db = AsyncMock()
    conv_id = uuid.uuid4()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": "x" * 5001},
            )
        assert response.status_code == 422
        assert "detail" in response.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_empty_content_returns_422():
    """CONV-08: SendMessageRequest min_length=1 rejects empty string."""
    auth = AuthContext(user_id="test-user", auth_type="jwt")
    mock_db = AsyncMock()
    conv_id = uuid.uuid4()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": ""},
            )
        assert response.status_code == 422
        assert "detail" in response.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_persists_user_and_assistant_messages():
    """CONV-10: db.add called for user Message then assistant Message after agent reply."""
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [AIMessage(content="Assistant reply text")]}
        )
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "User question here"},
                )
        assert response.status_code == 200

        added_messages = [c[0][0] for c in mock_db.add.call_args_list if isinstance(c[0][0], Message)]
        assert len(added_messages) == 2
        roles = {m.role for m in added_messages}
        assert roles == {MessageRole.user, MessageRole.assistant}
        by_role = {m.role: m for m in added_messages}
        assert by_role[MessageRole.user].content == "User question here"
        assert by_role[MessageRole.assistant].content == "Assistant reply text"
        assert by_role[MessageRole.user].conversation_id == conv.id
        assert by_role[MessageRole.assistant].conversation_id == conv.id
    finally:
        app.dependency_overrides.clear()


class _ConversationWithRealExpiry:
    """Minimal stand-in for ORM Conversation with a real is_expired property."""

    def __init__(self, user_id: uuid.UUID):
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.status = ConversationStatus.active
        self.language = "en"
        now = datetime.now(timezone.utc)
        self.created_at = now
        self.updated_at = now
        self.expires_at = now + timedelta(hours=3)

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


@pytest.mark.asyncio
async def test_send_message_refreshes_conversation_expires_at():
    """CONV-11: expires_at (and updated_at) extended to now + conversation_ttl_hours."""
    from juniper_ai.app.config import settings

    user = _fake_user()
    conv = _ConversationWithRealExpiry(user.id)
    expires_before = conv.expires_at
    updated_before = conv.updated_at

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="OK")]})
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "Hi"},
                )
        assert response.status_code == 200

        assert conv.expires_at > expires_before
        assert conv.updated_at >= updated_before
        now = datetime.now(timezone.utc)
        ttl_seconds = settings.conversation_ttl_hours * 3600
        assert abs((conv.expires_at - now).total_seconds() - ttl_seconds) < 10
    finally:
        app.dependency_overrides.clear()


def _setup_stream_message_test():
    """Shared DB + auth wiring for POST .../messages/stream tests."""
    user = _fake_user()
    conv = _fake_conversation(user.id)
    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    auth = AuthContext(user_id="test-user", auth_type="jwt")
    return user, conv, mock_db, auth


@pytest.mark.asyncio
async def test_stream_message_emits_status_token_done_sequence():
    """CONV-12: SSE shows thinking → token(s) → done."""
    _user, conv, mock_db, auth = _setup_stream_message_test()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    async def fake_astream_events(*_a, **_kw):
        for text in ("Hello ", "world"):
            chunk = MagicMock()
            chunk.content = text
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    try:
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/conversations/{conv.id}/messages/stream",
                    json={"content": "Hi there"},
                ) as response:
                    assert response.status_code == 200
                    body = await response.aread()
        text = body.decode()
        events = _parse_sse_events(text)
        names = [e[0] for e in events]
        assert names[0] == "status"
        assert events[0][1].get("status") == "thinking"
        assert "token" in names
        assert names[-1] == "done"
        assert events[-1][1].get("text") == "Hello world"
        token_texts = [e[1].get("text", "") for e in events if e[0] == "token"]
        assert "".join(token_texts) == "Hello world"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_message_emits_calling_tool_on_tool_start():
    """CONV-13: on_tool_start yields status calling_tool with tool name."""
    _user, conv, mock_db, auth = _setup_stream_message_test()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    async def fake_astream_events(*_a, **_kw):
        yield {"event": "on_tool_start", "name": "search_hotels"}
        chunk = MagicMock()
        chunk.content = "ok"
        yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    try:
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/conversations/{conv.id}/messages/stream",
                    json={"content": "Search Barcelona"},
                ) as response:
                    assert response.status_code == 200
                    body = await response.aread()
        events = _parse_sse_events(body.decode())
        tool_status = [e for e in events if e[0] == "status" and e[1].get("status") == "calling_tool"]
        assert len(tool_status) == 1
        assert tool_status[0][1].get("tool") == "search_hotels"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_message_agent_failure_emits_error_event():
    """CONV-14: exception during astream_events yields error SSE (after thinking)."""
    _user, conv, mock_db, auth = _setup_stream_message_test()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    async def fake_astream_events(*_a, **_kw):
        raise RuntimeError("simulated agent failure")
        yield  # pragma: no cover

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    try:
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/conversations/{conv.id}/messages/stream",
                    json={"content": "Break please"},
                ) as response:
                    assert response.status_code == 200
                    body = await response.aread()
        events = _parse_sse_events(body.decode())
        assert any(e[0] == "status" and e[1].get("status") == "thinking" for e in events)
        err = [e for e in events if e[0] == "error"]
        assert len(err) == 1
        assert "temporary issue" in err[0][1].get("error", "").lower()
        assert "done" not in [e[0] for e in events]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_message_persists_user_and_assistant_after_done():
    """CONV-15: after successful stream, user + assistant Message rows are added."""
    _user, conv, mock_db, auth = _setup_stream_message_test()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    async def fake_astream_events(*_a, **_kw):
        chunk = MagicMock()
        chunk.content = "Streamed reply"
        yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    try:
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/conversations/{conv.id}/messages/stream",
                    json={"content": "User stream msg"},
                ) as response:
                    assert response.status_code == 200
                    await response.aread()

        mock_db.flush.assert_awaited()
        added_messages = [c[0][0] for c in mock_db.add.call_args_list if isinstance(c[0][0], Message)]
        assert len(added_messages) == 2
        roles = {m.role for m in added_messages}
        assert roles == {MessageRole.user, MessageRole.assistant}
        by_role = {m.role: m for m in added_messages}
        assert by_role[MessageRole.user].content == "User stream msg"
        assert by_role[MessageRole.assistant].content == "Streamed reply"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_processes_booking_events_from_agent_output():
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        event_payload = (
            '__BOOKING_EVENT__{"__booking_event__": true, "event_type": "booking.cancelled", '
            '"booking_id": "JNP-123"}__END_BOOKING_EVENT__'
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [AIMessage(content=f"Done\n\n{event_payload}")]}
        )
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations._apply_booking_event", new_callable=AsyncMock) as mock_apply:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "Cancel booking JNP-123"},
                )
        assert response.status_code == 200
        assert mock_apply.await_count == 1
        called_event = mock_apply.await_args.kwargs["booking_event"]
        assert called_event["event_type"] == "booking.cancelled"
        assert called_event["booking_id"] == "JNP-123"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_to_expired_conversation_returns_410():
    user = _fake_user()
    conv = _fake_conversation(user.id, expired=True)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    mock_db.execute = AsyncMock(return_value=conv_result)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/conversations/{conv.id}/messages",
                json={"content": "Hello"},
            )
        assert response.status_code == 410
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_to_nonexistent_conversation_returns_404():
    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=conv_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        fake_id = uuid.uuid4()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/conversations/{fake_id}/messages",
                json={"content": "Hello"},
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_key_without_external_user_id_returns_400():
    """Regression test: API key auth without X-External-User-Id must fail."""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    # Auth with api_key but no external_user_id
    auth = AuthContext(user_id="apikey:test-api", auth_type="api_key", external_user_id=None)

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        fake_id = uuid.uuid4()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/conversations/{fake_id}/messages",
                json={"content": "Hello"},
            )
        assert response.status_code == 400
        assert "X-External-User-Id" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_conversation_with_ownership_check():
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    mock_db.execute = AsyncMock(return_value=conv_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/conversations/{conv.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(conv.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_conversation_not_owned_returns_404():
    """If the DB query scoped by user returns None, we get 404."""
    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=conv_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="other-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        fake_id = uuid.uuid4()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/conversations/{fake_id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_conversation_expired_marks_status_expired():
    """CONV-17: GET updates in-memory conversation.status to expired when is_expired."""
    from juniper_ai.app.db.models import ConversationStatus

    user = _fake_user()
    conv = _fake_conversation(user.id, expired=True)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    mock_db.execute = AsyncMock(return_value=conv_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/conversations/{conv.id}")
        assert response.status_code == 200
        assert response.json()["status"] == "expired"
        assert conv.status == ConversationStatus.expired
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_persist_booking_stores_booking_details():
    """BOOK-10: booking_details JSONB stores full tool payload with critical keys."""
    from juniper_ai.app.api.routes.conversations import _persist_booking

    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    booking_data = {
        "__booking__": True,
        "booking_id": "JNP-ABCDEF01",
        "hotel_name": "Persist Hotel",
        "check_in": "2026-07-01",
        "check_out": "2026-07-04",
        "total_price": "300.00",
        "currency": "EUR",
        "guest_name": "Pat Guest",
        "guest_email": "pat@example.com",
        "status": "confirmed",
    }

    existing = MagicMock()
    existing.scalar_one_or_none.return_value = None
    captured: list = []

    def capture_add(obj):
        captured.append(obj)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing)
    db.add = MagicMock(side_effect=capture_add)
    db.flush = AsyncMock()

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
        await _persist_booking(db, user_id, conv_id, booking_data)

    assert len(captured) == 1
    row = captured[0]
    assert isinstance(row, Booking)
    assert row.booking_details is not None
    assert row.booking_details.get("booking_id") == "JNP-ABCDEF01"
    assert row.booking_details.get("hotel_name") == "Persist Hotel"
    assert row.booking_details.get("check_in") == "2026-07-01"
    assert row.booking_details.get("check_out") == "2026-07-04"
    assert row.booking_details.get("total_price") == "300.00"
    assert row.booking_details.get("currency") == "EUR"
    assert row.booking_details.get("guest_name") == "Pat Guest"
    assert row.booking_details.get("guest_email") == "pat@example.com"
    assert row.booking_details.get("__booking__") is True


@pytest.mark.asyncio
async def test_persist_booking_idempotency_key_format():
    """PERSIST-05: idempotency_key is `{conversation_id}:{juniper_booking_id}`."""
    from juniper_ai.app.api.routes.conversations import _persist_booking

    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    juniper_id = "JNP-IDEMPOT1"
    booking_data = {
        "__booking__": True,
        "booking_id": juniper_id,
        "hotel_name": "Key Hotel",
        "check_in": "2026-08-01",
        "check_out": "2026-08-02",
        "total_price": "50",
        "currency": "EUR",
        "status": "confirmed",
    }

    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    captured: list = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup)
    db.add = MagicMock(side_effect=lambda o: captured.append(o))
    db.flush = AsyncMock()

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
        await _persist_booking(db, user_id, conv_id, booking_data)

    row = captured[0]
    assert row.idempotency_key == f"{conv_id}:{juniper_id}"


@pytest.mark.asyncio
async def test_persist_booking_duplicate_same_conversation_and_juniper_id_skips_insert():
    """PERSIST-04: second persist with same key does not add another Booking."""
    from juniper_ai.app.api.routes.conversations import _persist_booking

    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    booking_data = {
        "__booking__": True,
        "booking_id": "JNP-DUP-SAME",
        "hotel_name": "Dup Hotel",
        "check_in": "2026-09-01",
        "check_out": "2026-09-02",
        "total_price": "10",
        "currency": "EUR",
        "status": "confirmed",
    }

    first_lookup = MagicMock()
    first_lookup.scalar_one_or_none.return_value = None
    second_lookup = MagicMock()
    second_lookup.scalar_one_or_none.return_value = MagicMock()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[first_lookup, second_lookup])
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
        await _persist_booking(db, user_id, conv_id, booking_data)
        await _persist_booking(db, user_id, conv_id, booking_data)

    booking_adds = [c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], Booking)]
    assert len(booking_adds) == 1


@pytest.mark.asyncio
async def test_persist_booking_duplicate_logs_skipping():
    """PERSIST-06: duplicate idempotency_key → info log 'Duplicate booking detected'."""
    from juniper_ai.app.api.routes.conversations import _persist_booking

    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    juniper_id = "JNP-DUP-LOG"
    booking_data = {
        "__booking__": True,
        "booking_id": juniper_id,
        "hotel_name": "Log Hotel",
        "check_in": "2026-10-01",
        "check_out": "2026-10-02",
        "total_price": "20",
        "currency": "EUR",
        "status": "confirmed",
    }
    expected_key = f"{conv_id}:{juniper_id}"

    first_lookup = MagicMock()
    first_lookup.scalar_one_or_none.return_value = None
    second_lookup = MagicMock()
    second_lookup.scalar_one_or_none.return_value = MagicMock()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[first_lookup, second_lookup])
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock), \
         patch("juniper_ai.app.api.routes.conversations.logger") as log_mock:
        await _persist_booking(db, user_id, conv_id, booking_data)
        await _persist_booking(db, user_id, conv_id, booking_data)

    log_mock.info.assert_any_call(
        "Duplicate booking detected (idempotency_key=%s), skipping",
        expected_key,
    )


@pytest.mark.asyncio
async def test_persist_booking_dispatches_booking_confirmed_webhook():
    """PERSIST-07: after insert, dispatch_event(booking.confirmed, ...) is awaited."""
    from juniper_ai.app.api.routes.conversations import _persist_booking

    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    booking_data = {
        "__booking__": True,
        "booking_id": "JNP-WH-CONF",
        "hotel_name": "Webhook Inn",
        "check_in": "2026-11-01",
        "check_out": "2026-11-03",
        "total_price": "88.00",
        "currency": "EUR",
        "guest_name": "Guesty",
        "guest_email": "g@example.com",
        "status": "confirmed",
    }

    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    stored: Booking | None = None

    def capture_add(obj):
        nonlocal stored
        if isinstance(obj, Booking):
            stored = obj

    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup)
    db.add = MagicMock(side_effect=capture_add)
    db.flush = AsyncMock()

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock) as mock_dispatch:
        await _persist_booking(db, user_id, conv_id, booking_data)

    mock_dispatch.assert_awaited_once()
    kw = mock_dispatch.await_args.kwargs
    assert kw["event_type"] == "booking.confirmed"
    assert stored is not None
    assert kw["booking_id"] == str(stored.id)
    assert kw["db"] is db
    details = kw["booking_details"]
    assert details["juniper_booking_id"] == "JNP-WH-CONF"
    assert details["hotel_name"] == "Webhook Inn"
    assert details["guest_email"] == "g@example.com"


@pytest.mark.asyncio
async def test_persist_booking_dispatch_failure_does_not_raise():
    """PERSIST-08: webhook dispatch errors are logged and do not propagate."""
    from juniper_ai.app.api.routes.conversations import _persist_booking

    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    booking_data = {
        "__booking__": True,
        "booking_id": "JNP-WH-FAIL",
        "hotel_name": "Fail Hotel",
        "check_in": "2026-12-01",
        "check_out": "2026-12-02",
        "total_price": "1",
        "currency": "EUR",
        "status": "confirmed",
    }

    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup)
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch(
        "juniper_ai.app.api.routes.conversations.dispatch_event",
        new_callable=AsyncMock,
        side_effect=RuntimeError("webhook delivery failed"),
    ), patch("juniper_ai.app.api.routes.conversations.logger") as log_mock:
        await _persist_booking(db, user_id, conv_id, booking_data)

    log_mock.error.assert_called_once()
    args, _kwargs = log_mock.error.call_args
    assert args[0] == "Failed to dispatch booking.confirmed webhook"
    assert _kwargs.get("exc_info") is True


@pytest.mark.asyncio
async def test_send_message_persists_when_agent_emits_booking_data_block():
    """PERSIST-01: __BOOKING_DATA__ in agent messages → _persist_booking invoked with parsed dict."""
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    booking_payload = {
        "__booking__": True,
        "booking_id": "JNP-PERSIST01",
        "hotel_name": "Persist Inn",
        "check_in": "2026-04-01",
        "check_out": "2026-04-04",
        "total_price": "199.00",
        "currency": "EUR",
        "status": "confirmed",
        "rate_plan_code": "RPC_X",
        "guest_name": "Sam",
        "guest_email": "sam@example.com",
    }
    agent_text = (
        "Confirmed.\n"
        f"__BOOKING_DATA__{json.dumps(booking_payload)}__END_BOOKING_DATA__"
    )

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content=agent_text)]})
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations._persist_booking", new_callable=AsyncMock) as mock_persist:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "Book it"},
                )
        assert response.status_code == 200
        mock_persist.assert_awaited_once()
        passed = mock_persist.await_args.kwargs["booking_data"]
        assert passed["booking_id"] == "JNP-PERSIST01"
        assert passed.get("__booking__") is True
        assert passed["hotel_name"] == "Persist Inn"
        assert mock_persist.await_args.kwargs["conversation_id"] == conv.id
        assert mock_persist.await_args.kwargs["user_id"] == user.id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_skips_persist_without_booking_markers():
    """PERSIST-02: plain assistant text → _persist_booking not called."""
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [AIMessage(content="Here are hotels in Paris.")]}
        )
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations._persist_booking", new_callable=AsyncMock) as mock_persist:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "Search Paris"},
                )
        assert response.status_code == 200
        mock_persist.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_send_message_extracts_multiple_booking_blocks_from_tool_messages():
    """PERSIST-03: multiple ToolMessage payloads → _persist_booking once per __booking__ JSON."""
    user = _fake_user()
    conv = _fake_conversation(user.id)

    mock_db = AsyncMock()
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = conv
    user_result = MagicMock()
    user_result.scalar_one.return_value = user
    msg_result = MagicMock()
    msg_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[conv_result, user_result, msg_result])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    b1 = {
        "__booking__": True,
        "booking_id": "JNP-MULTI01",
        "hotel_name": "A",
        "check_in": "2026-05-01",
        "check_out": "2026-05-03",
        "total_price": "1",
        "currency": "EUR",
        "status": "confirmed",
        "rate_plan_code": "R1",
        "guest_name": "A",
        "guest_email": "a@b.c",
    }
    b2 = {
        "__booking__": True,
        "booking_id": "JNP-MULTI02",
        "hotel_name": "B",
        "check_in": "2026-06-01",
        "check_out": "2026-06-04",
        "total_price": "2",
        "currency": "USD",
        "status": "confirmed",
        "rate_plan_code": "R2",
        "guest_name": "B",
        "guest_email": "b@b.c",
    }

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    ToolMessage(
                        content=f"__BOOKING_DATA__{json.dumps(b1)}__END_BOOKING_DATA__",
                        tool_call_id="tc-1",
                    ),
                    ToolMessage(
                        content=f"__BOOKING_DATA__{json.dumps(b2)}__END_BOOKING_DATA__",
                        tool_call_id="tc-2",
                    ),
                    AIMessage(content="Two bookings completed."),
                ]
            }
        )
        with patch("juniper_ai.app.agent.graph.agent_graph", mock_graph), \
             patch("juniper_ai.app.api.routes.conversations._persist_booking", new_callable=AsyncMock) as mock_persist:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/conversations/{conv.id}/messages",
                    json={"content": "Book two rooms"},
                )
        assert response.status_code == 200
        assert mock_persist.await_count == 2
        ids = {c.kwargs["booking_data"]["booking_id"] for c in mock_persist.await_args_list}
        assert ids == {"JNP-MULTI01", "JNP-MULTI02"}
    finally:
        app.dependency_overrides.clear()


def test_extract_booking_events_from_tool_messages():
    from juniper_ai.app.api.routes.conversations import _extract_booking_events

    payload = (
        "Booking updated\n\n"
        '__BOOKING_EVENT__{"__booking_event__": true, "event_type": "booking.modified", "booking_id": "JNP-1"}__END_BOOKING_EVENT__'
    )
    events = _extract_booking_events([payload])
    assert len(events) == 1
    assert events[0]["event_type"] == "booking.modified"
    assert events[0]["booking_id"] == "JNP-1"


@pytest.mark.asyncio
async def test_apply_booking_event_updates_status_and_dates():
    from juniper_ai.app.api.routes.conversations import _apply_booking_event

    booking = MagicMock()
    booking.id = uuid.uuid4()
    booking.juniper_booking_id = "JNP-1"
    booking.status = BookingStatus.confirmed
    booking.hotel_name = "Hotel"
    booking.check_in = "2026-04-01"
    booking.check_out = "2026-04-02"
    booking.total_price = "100"
    booking.currency = "EUR"

    result = MagicMock()
    result.scalar_one_or_none.return_value = booking

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=result)

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
        await _apply_booking_event(
            db=mock_db,
            user_id=uuid.uuid4(),
            booking_event={
                "__booking_event__": True,
                "event_type": "booking.modified",
                "booking_id": "JNP-1",
                "check_in": "2026-05-01",
                "check_out": "2026-05-03",
            },
        )

    assert booking.status == BookingStatus.modified
    assert booking.check_in == "2026-05-01"
    assert booking.check_out == "2026-05-03"


@pytest.mark.asyncio
async def test_apply_booking_event_updates_status_cancelled():
    from juniper_ai.app.api.routes.conversations import _apply_booking_event

    booking = MagicMock()
    booking.id = uuid.uuid4()
    booking.juniper_booking_id = "JNP-2"
    booking.status = BookingStatus.confirmed
    booking.hotel_name = "Hotel"
    booking.check_in = "2026-04-01"
    booking.check_out = "2026-04-02"
    booking.total_price = "100"
    booking.currency = "EUR"

    result = MagicMock()
    result.scalar_one_or_none.return_value = booking

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=result)

    with patch("juniper_ai.app.api.routes.conversations.dispatch_event", new_callable=AsyncMock):
        await _apply_booking_event(
            db=mock_db,
            user_id=uuid.uuid4(),
            booking_event={
                "__booking_event__": True,
                "event_type": "booking.cancelled",
                "booking_id": "JNP-2",
            },
        )

    assert booking.status == BookingStatus.cancelled
