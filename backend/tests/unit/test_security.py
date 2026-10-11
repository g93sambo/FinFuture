"""
Unit tests for backend/core/security.py
Testing password hashing, JWT creation/decoding, get_current_user, WebSocket auth, and tenant isolation.
"""

from datetime import timedelta
import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException
from fastapi.exceptions import WebSocketException

from core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    get_current_user,
    authenticate_websocket,
    verify_client_ownership,
)
from db.models import DBUser, DBClientProfile


def test_password_hashing():
    pwd = "StrongPassword#2026"
    hashed = get_password_hash(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, "") is False

    with pytest.raises(ValueError):
        get_password_hash("")


def test_jwt_create_and_decode():
    payload = {"sub": "user-456", "email": "advisor@example.com"}
    token = create_access_token(payload)
    assert isinstance(token, str)

    decoded = decode_access_token(token)
    assert decoded["sub"] == "user-456"
    assert decoded["email"] == "advisor@example.com"
    assert "exp" in decoded
    assert "iat" in decoded


def test_jwt_expired_token():
    payload = {"sub": "user-456"}
    token = create_access_token(payload, expires_delta=timedelta(seconds=-10))

    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert "Token has expired" in exc_info.value.detail


def test_jwt_tampered_token():
    token = create_access_token({"sub": "user-456"})
    parts = token.split(".")
    tampered = parts[0] + "." + parts[1] + ".invalidSignature"

    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(tampered)
    assert exc_info.value.status_code == 401
    assert "Could not validate credentials" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_user_success(db_session):
    user = DBUser(id="u1", email="u1@example.com", hashed_password=get_password_hash("pwd"), is_active=True)
    db_session.add(user)
    await db_session.commit()

    token = create_access_token({"sub": "u1"})
    auth_user = await get_current_user(token=token, db=db_session)
    assert auth_user.id == "u1"
    assert auth_user.email == "u1@example.com"


@pytest.mark.asyncio
async def test_get_current_user_inactive(db_session):
    user = DBUser(id="u2", email="u2@example.com", hashed_password=get_password_hash("pwd"), is_active=False)
    db_session.add(user)
    await db_session.commit()

    token = create_access_token({"sub": "u2"})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db_session)
    assert exc_info.value.status_code == 403
    assert "Inactive user account" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_user_not_found(db_session):
    token = create_access_token({"sub": "non-existent-id"})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db_session)
    assert exc_info.value.status_code == 401
    assert "User not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_verify_client_ownership_success(db_session):
    user = DBUser(id="u3", email="u3@example.com", hashed_password="pwd", is_active=True)
    db_session.add(user)
    await db_session.commit()

    client = DBClientProfile(client_id="c3", user_id="u3", annual_income=120000.0)
    db_session.add(client)
    await db_session.commit()

    profile = await verify_client_ownership(user=user, client_id="c3", db=db_session)
    assert profile.client_id == "c3"
    assert profile.annual_income == 120000.0


@pytest.mark.asyncio
async def test_verify_client_ownership_mismatch(db_session):
    user_alice = DBUser(id="alice", email="alice@example.com", hashed_password="pwd", is_active=True)
    user_bob = DBUser(id="bob", email="bob@example.com", hashed_password="pwd", is_active=True)
    db_session.add_all([user_alice, user_bob])
    await db_session.commit()

    client_bob = DBClientProfile(client_id="client-bob", user_id="bob")
    db_session.add(client_bob)
    await db_session.commit()

    # Alice attempts to access Bob's client profile -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await verify_client_ownership(user=user_alice, client_id="client-bob", db=db_session)
    assert exc_info.value.status_code == 403
    assert "Forbidden" in exc_info.value.detail


@pytest.mark.asyncio
async def test_verify_client_ownership_not_found(db_session):
    user = DBUser(id="u4", email="u4@example.com", hashed_password="pwd", is_active=True)
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await verify_client_ownership(user=user, client_id="nonexistent-client", db=db_session)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_websocket_auth(db_session):
    user = DBUser(id="ws-user", email="ws@example.com", hashed_password="pwd", is_active=True)
    db_session.add(user)
    await db_session.commit()

    mock_ws = AsyncMock()

    # 1. Valid token
    token = create_access_token({"sub": "ws-user"})
    authed_user = await authenticate_websocket(mock_ws, token, db_session)
    assert authed_user.id == "ws-user"

    # 2. Missing token
    with pytest.raises(WebSocketException) as exc_info:
        await authenticate_websocket(mock_ws, None, db_session)
    assert exc_info.value.code == 1008
    mock_ws.close.assert_called_with(code=1008, reason="Missing authentication token")

    # 3. Invalid token
    with pytest.raises(WebSocketException) as exc_info:
        await authenticate_websocket(mock_ws, "invalid.token.here", db_session)
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_get_current_user_ws_dependency(db_session):
    from core.security import get_current_user_ws

    user = DBUser(id="ws-dep-user", email="wsdep@example.com", hashed_password="pwd", is_active=True)
    db_session.add(user)
    await db_session.commit()

    mock_ws = AsyncMock()
    token = create_access_token({"sub": "ws-dep-user"})

    # Valid token
    res = await get_current_user_ws(mock_ws, token=token, db=db_session)
    assert res.id == "ws-dep-user"

    # Missing token
    with pytest.raises(WebSocketException) as exc_info:
        await get_current_user_ws(mock_ws, token=None, db=db_session)
    assert exc_info.value.code == 1008

    # Invalid token
    with pytest.raises(WebSocketException) as exc_info:
        await get_current_user_ws(mock_ws, token="corrupt", db=db_session)
    assert exc_info.value.code == 1008
