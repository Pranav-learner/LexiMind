"""Auth HTTP routes: register, login, me.

Thin transport adapters — they build the service, call it, and translate domain errors to
HTTP. No business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.errors import AuthError
from app.auth.models import User
from app.auth.repository import UserRepository
from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.auth.security import create_token
from app.auth.service import AuthService
from app.db.base import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _service(db: Session) -> AuthService:
    return AuthService(UserRepository(db))


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = _service(db).register(
            email=req.email, password=req.password, display_name=req.display_name
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return TokenResponse(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    try:
        user, token = _service(db).login(email=req.email, password=req.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
