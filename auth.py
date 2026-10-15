"""Authentication for teachers and students.

Server-side session tokens: login mints a random token, only its SHA-256 is
stored (table auth_tokens), and logout deletes the row. Passwords are hashed
with scrypt from the standard library, so no extra dependencies are needed.

Two separate role dependencies guard the API:
  - require_teacher  → everything under /api/v1 except /auth and /student
  - require_student  → everything under /api/v1/student
A token minted for one role is rejected by the other role's dependency.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

import db_models as m
from database import get_db

TOKEN_TTL = timedelta(days=7)

# Teacher registration is open by default. Set TEACHER_INVITE_CODE on the
# server to require that code for every teacher account after the first, so a
# student cannot simply register as a teacher.
TEACHER_INVITE_CODE = os.getenv("TEACHER_INVITE_CODE", "")

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


# ── Passwords ────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
        )
        return hmac.compare_digest(dk, bytes.fromhex(dk_hex))
    except Exception:
        return False


# ── Login rate limiting (in-memory; resets on server restart) ────────────────

_MAX_FAILS, _WINDOW_S = 5, 15 * 60
_fails: dict[str, list[float]] = {}


def _check_rate_limit(key: str) -> None:
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < _WINDOW_S]
    _fails[key] = recent
    if len(recent) >= _MAX_FAILS:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")


def _record_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


def _clear_fails(key: str) -> None:
    _fails.pop(key, None)


def check_attempt_limit(key: str) -> None:
    """Shared by the student enrollment-code endpoint."""
    _check_rate_limit(key)


def record_attempt_fail(key: str) -> None:
    _record_fail(key)


# ── Tokens ───────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, role: str, user_id: int) -> str:
    db.query(m.AuthToken).filter(m.AuthToken.expires_at < _now()).delete()
    token = secrets.token_urlsafe(32)
    db.add(
        m.AuthToken(token_hash=_sha(token), role=role, user_id=user_id, expires_at=_now() + TOKEN_TTL)
    )
    db.commit()
    return token


def _extract_token(request: Request, query_token: str | None) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    # <img src> / <a href> cannot send headers, so image and PDF links carry
    # the token in the query string instead.
    return query_token or None


def _resolve(db: Session, token: str | None, role: str) -> int:
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    row = db.query(m.AuthToken).filter(m.AuthToken.token_hash == _sha(token)).first()
    if not row or row.expires_at < _now():
        raise HTTPException(status_code=401, detail="Session expired — sign in again")
    if row.role != role:
        raise HTTPException(status_code=403, detail=f"This area is for {role}s only")
    return row.user_id


def require_teacher(
    request: Request, token: str | None = Query(default=None), db: Session = Depends(get_db)
) -> m.Teacher:
    teacher = db.get(m.Teacher, _resolve(db, _extract_token(request, token), "teacher"))
    if not teacher:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return teacher


def require_student(
    request: Request, token: str | None = Query(default=None), db: Session = Depends(get_db)
) -> m.StudentAccount:
    acct = db.get(m.StudentAccount, _resolve(db, _extract_token(request, token), "student"))
    if not acct:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return acct


# ── Schemas ──────────────────────────────────────────────────────────────────


class TeacherRegister(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    invite_code: str | None = None


class StudentRegister(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str


class AuthResult(BaseModel):
    token: str
    role: str
    user: UserRead


# ── Routes ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


@router.post("/teacher/register", response_model=AuthResult)
def teacher_register(body: TeacherRegister, db: Session = Depends(get_db)) -> AuthResult:
    email = body.email.lower()
    first = db.query(m.Teacher).count() == 0
    if not first and TEACHER_INVITE_CODE:
        if not hmac.compare_digest((body.invite_code or "").encode(), TEACHER_INVITE_CODE.encode()):
            raise HTTPException(status_code=403, detail="Invalid teacher invite code")
    if db.query(m.Teacher).filter(m.Teacher.email == email).first():
        raise HTTPException(status_code=409, detail="A teacher with this email already exists")
    teacher = m.Teacher(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    db.add(teacher)
    db.flush()
    if first:
        # Adopt classes that predate accounts.
        db.query(m.CourseClass).filter(m.CourseClass.teacher_id.is_(None)).update(
            {m.CourseClass.teacher_id: teacher.id}
        )
    db.commit()
    return AuthResult(token=issue_token(db, "teacher", teacher.id), role="teacher", user=teacher)


@router.post("/teacher/login", response_model=AuthResult)
def teacher_login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> AuthResult:
    key = f"teacher:{body.email.lower()}:{_client(request)}"
    _check_rate_limit(key)
    teacher = db.query(m.Teacher).filter(m.Teacher.email == body.email.lower()).first()
    if not teacher or not verify_password(body.password, teacher.password_hash):
        _record_fail(key)
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    _clear_fails(key)
    return AuthResult(token=issue_token(db, "teacher", teacher.id), role="teacher", user=teacher)


@router.post("/student/register", response_model=AuthResult)
def student_register(body: StudentRegister, db: Session = Depends(get_db)) -> AuthResult:
    email = body.email.lower()
    if db.query(m.StudentAccount).filter(m.StudentAccount.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    acct = m.StudentAccount(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    db.add(acct)
    db.commit()
    return AuthResult(token=issue_token(db, "student", acct.id), role="student", user=acct)


@router.post("/student/login", response_model=AuthResult)
def student_login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> AuthResult:
    key = f"student:{body.email.lower()}:{_client(request)}"
    _check_rate_limit(key)
    acct = db.query(m.StudentAccount).filter(m.StudentAccount.email == body.email.lower()).first()
    if not acct or not verify_password(body.password, acct.password_hash):
        _record_fail(key)
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    _clear_fails(key)
    return AuthResult(token=issue_token(db, "student", acct.id), role="student", user=acct)


def _logout(request: Request, token: str | None, role: str, db: Session) -> None:
    raw = _extract_token(request, token)
    _resolve(db, raw, role)
    db.query(m.AuthToken).filter(m.AuthToken.token_hash == _sha(raw)).delete()
    db.commit()


@router.post("/teacher/logout", status_code=204)
def teacher_logout(request: Request, token: str | None = Query(default=None), db: Session = Depends(get_db)) -> None:
    _logout(request, token, "teacher", db)


@router.post("/student/logout", status_code=204)
def student_logout(request: Request, token: str | None = Query(default=None), db: Session = Depends(get_db)) -> None:
    _logout(request, token, "student", db)


@router.get("/teacher/me", response_model=UserRead)
def teacher_me(teacher: m.Teacher = Depends(require_teacher)) -> m.Teacher:
    return teacher


@router.get("/student/me", response_model=UserRead)
def student_me(acct: m.StudentAccount = Depends(require_student)) -> m.StudentAccount:
    return acct
