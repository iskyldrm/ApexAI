from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlmodel import Field

from app.models.base import BaseModel


class PasswordResetToken(BaseModel, table=True):
    __tablename__ = "password_reset_tokens"

    user_id: str = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    token_hash: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: datetime | None = Field(default=None)


class EmailVerificationToken(BaseModel, table=True):
    __tablename__ = "email_verification_tokens"

    user_id: str = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    new_email: str | None = Field(default=None)
    token_hash: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: datetime | None = Field(default=None)


class RefreshToken(BaseModel, table=True):
    __tablename__ = "refresh_tokens"

    user_id: str = Field(
        sa_column=Column(ForeignKey("users.id"), index=True, nullable=False)
    )
    token_hash: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(default=None)
    ip_address: str | None = Field(default=None)