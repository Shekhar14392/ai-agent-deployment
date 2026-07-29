"""
schemas.py — every Pydantic request/response model.
(Consolidated from schemas/auth.py, wallet.py, agent.py)
"""
import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole, TransactionType, WithdrawalStatus, AgentType, MessageRole


# ------------------------------------------------------------------- auth --

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2, max_length=255)
    company_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    company_name: str | None
    role: UserRole
    is_active: bool
    is_verified: bool

    class Config:
        from_attributes = True


# ----------------------------------------------------------------- wallet --

class WalletOut(BaseModel):
    balance: Decimal
    currency: str

    class Config:
        from_attributes = True


class WalletTransactionOut(BaseModel):
    id: uuid.UUID
    type: TransactionType
    amount: Decimal
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class WithdrawalCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    payout_method: str
    payout_details: str


class WithdrawalOut(BaseModel):
    id: uuid.UUID
    amount: Decimal
    status: WithdrawalStatus
    payout_method: str
    created_at: datetime

    class Config:
        from_attributes = True


class WithdrawalDecision(BaseModel):
    status: WithdrawalStatus
    admin_note: str | None = None


# ------------------------------------------------------------------ agent --

class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    agent_type: AgentType
    message: str
    provider: str | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    provider: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    reply: MessageOut
