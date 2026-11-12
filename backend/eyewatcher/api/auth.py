"""Login com JWT, papeis, limite de tentativas e ticket do WebSocket."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from eyewatcher.api import db
from eyewatcher.api.state import AppState, get_state

ALGORITHM: Final[str] = "HS256"
ROLE_RANK: Final[dict[str, int]] = {"viewer": 0, "operator": 1, "admin": 2}

MAX_FAILURES: Final[int] = 5
LOCK_SECONDS: Final[float] = 60.0
TICKET_TTL_SECONDS: Final[float] = 30.0

#: Hash valido de senha nenhuma: usuario inexistente custa o mesmo tempo que senha errada.
DUMMY_HASH: Final[bytes] = bcrypt.hashpw(b"eyewatcher", bcrypt.gensalt())

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    username: str
    role: str


class LoginAttempts:
    """Bloqueia por usuario e IP depois de MAX_FAILURES erros seguidos."""

    def __init__(self) -> None:
        self._failures: dict[str, tuple[int, float]] = {}

    def locked_for(self, key: str) -> float:
        count, last = self._failures.get(key, (0, 0.0))
        remaining = last + LOCK_SECONDS - time.monotonic()
        return remaining if count >= MAX_FAILURES and remaining > 0 else 0.0

    def fail(self, key: str) -> None:
        count, last = self._failures.get(key, (0, 0.0))
        if time.monotonic() - last > LOCK_SECONDS:
            count = 0
        self._failures[key] = (count + 1, time.monotonic())

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)


class TicketStore:
    """Ticket curto de uso unico: o JWT nunca vai na URL do WebSocket."""

    def __init__(self) -> None:
        self._tickets: dict[str, tuple[User, float]] = {}

    def issue(self, user: User) -> str:
        now = time.monotonic()
        self._tickets = {k: v for k, v in self._tickets.items() if v[1] > now}
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = (user, now + TICKET_TTL_SECONDS)
        return ticket

    def redeem(self, ticket: str) -> User | None:
        entry = self._tickets.pop(ticket, None)
        if entry is None or entry[1] < time.monotonic():
            return None
        return entry[0]


attempts = LoginAttempts()
tickets = TicketStore()


def client_ip(request: Request) -> str:
    # O nginx do frontend e o unico caminho ate aqui e sobrescreve este cabecalho.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def issue_token(state: AppState, user: User) -> str:
    claims = {
        "sub": user.username,
        "role": user.role,
        "exp": datetime.now(UTC) + timedelta(minutes=state.cfg.jwt_ttl_minutes),
    }
    return jwt.encode(claims, state.jwt_secret, algorithm=ALGORITHM)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    state: Annotated[AppState, Depends(get_state)],
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão inválida ou expirada")
    if credentials is None:
        raise unauthorized
    try:
        claims = jwt.decode(credentials.credentials, state.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
    return User(claims["sub"], claims["role"])


def require(role: str) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "seu papel não permite esta ação")
        return user

    return dependency


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(
    body: LoginBody, request: Request, state: Annotated[AppState, Depends(get_state)]
) -> dict[str, str]:
    ip = client_ip(request)
    key = f"{body.username}|{ip}"
    if (wait := attempts.locked_for(key)) > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"muitas tentativas; aguarde {wait:.0f} s"
        )

    row = await state.db.fetchrow(
        "SELECT username, password_hash, role FROM users WHERE username=$1", body.username
    )
    stored = row["password_hash"].encode("ascii") if row else DUMMY_HASH
    valid = await asyncio.to_thread(bcrypt.checkpw, body.password.encode("utf-8")[:72], stored)
    if row is None or not valid:
        attempts.fail(key)
        await db.audit(state.db, body.username, "login_failed", ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuário ou senha inválidos")

    attempts.clear(key)
    user = User(row["username"], row["role"])
    await db.audit(state.db, user.username, "login", ip=ip)
    return {"token": issue_token(state, user), "username": user.username, "role": user.role}


@router.get("/me")
async def me(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
    return {"username": user.username, "role": user.role}


@router.post("/ws-ticket")
async def ws_ticket(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
    return {"ticket": tickets.issue(user)}
