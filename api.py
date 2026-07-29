"""
api.py — auth dependencies + every API router in the platform.
(Consolidated from api/deps.py, api/v1/auth.py, wallet.py, agents.py, __init__ files)
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, decode_token, hash_password, verify_password, create_access_token, create_refresh_token
from app.models import User, UserRole, Wallet, WalletTransaction, WithdrawalRequest, WithdrawalStatus
from app.models import Conversation, Message, MessageRole
from app.schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest, UserOut,
    WalletOut, WalletTransactionOut, WithdrawalCreate, WithdrawalOut, WithdrawalDecision,
    ChatRequest, ChatResponse, MessageOut,
)
from app.ai_providers import generate_reply, AIProviderError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# --------------------------------------------------------------- dependencies --

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise credentials_error from exc

    if payload.get("type") != "access":
        raise credentials_error
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_error

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error
    return user


def require_roles(*roles: UserRole):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return checker


require_admin = require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN)
require_super_admin = require_roles(UserRole.SUPER_ADMIN)


# --------------------------------------------------------------------- auth --

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        company_name=payload.company_name,
    )
    db.add(user)
    await db.flush()
    db.add(Wallet(user_id=user.id, balance=0, currency="USD"))
    await db.commit()
    await db.refresh(user)
    return user


@auth_router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@auth_router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = decode_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == data["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@auth_router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# ------------------------------------------------------------------- wallet --

wallet_router = APIRouter(prefix="/wallet", tags=["wallet"])


@wallet_router.get("", response_model=WalletOut)
async def get_wallet(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    return result.scalar_one()


@wallet_router.get("/transactions", response_model=list[WalletTransactionOut])
async def get_transactions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one()
    tx_result = await db.execute(
        select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id)
        .order_by(WalletTransaction.created_at.desc())
    )
    return tx_result.scalars().all()


@wallet_router.post("/withdrawals", response_model=WithdrawalOut, status_code=201)
async def request_withdrawal(
    payload: WithdrawalCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one()
    if wallet.balance < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")
    withdrawal = WithdrawalRequest(
        user_id=user.id, amount=payload.amount,
        payout_method=payload.payout_method, payout_details=payload.payout_details,
    )
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal


@wallet_router.get("/withdrawals", response_model=list[WithdrawalOut])
async def list_my_withdrawals(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WithdrawalRequest).where(WithdrawalRequest.user_id == user.id)
        .order_by(WithdrawalRequest.created_at.desc())
    )
    return result.scalars().all()


@wallet_router.get("/admin/withdrawals", response_model=list[WithdrawalOut], dependencies=[Depends(require_admin)])
async def admin_list_withdrawals(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WithdrawalRequest).order_by(WithdrawalRequest.created_at.desc()))
    return result.scalars().all()


@wallet_router.patch(
    "/admin/withdrawals/{withdrawal_id}", response_model=WithdrawalOut, dependencies=[Depends(require_admin)]
)
async def admin_decide_withdrawal(withdrawal_id: uuid.UUID, payload: WithdrawalDecision, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id))
    withdrawal = result.scalar_one_or_none()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")

    if payload.status == WithdrawalStatus.APPROVED and withdrawal.status == WithdrawalStatus.PENDING:
        wallet_result = await db.execute(select(Wallet).where(Wallet.user_id == withdrawal.user_id))
        wallet = wallet_result.scalar_one()
        if wallet.balance < withdrawal.amount:
            raise HTTPException(status_code=400, detail="User no longer has sufficient balance")
        wallet.balance -= withdrawal.amount
        db.add(WalletTransaction(
            wallet_id=wallet.id, type="debit", amount=withdrawal.amount,
            description=f"Withdrawal {withdrawal.id} approved",
        ))

    withdrawal.status = payload.status
    withdrawal.admin_note = payload.admin_note
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal


# ------------------------------------------------------------------- agents --

agents_router = APIRouter(prefix="/agents", tags=["agents"])


@agents_router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if payload.conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == payload.conversation_id, Conversation.user_id == user.id)
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(user_id=user.id, agent_type=payload.agent_type, title=payload.message[:80])
        db.add(conversation)
        await db.flush()

    user_message = Message(conversation_id=conversation.id, role=MessageRole.USER, content=payload.message)
    db.add(user_message)
    await db.flush()

    history_result = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.asc())
    )
    history = [
        {"role": "user" if m.role == MessageRole.USER else "assistant", "content": m.content}
        for m in history_result.scalars().all()
    ]

    try:
        reply_text, provider_used = await generate_reply(
            agent_type=payload.agent_type.value, history=history, provider=payload.provider
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    agent_message = Message(
        conversation_id=conversation.id, role=MessageRole.AGENT, content=reply_text, provider=provider_used
    )
    db.add(agent_message)
    await db.commit()
    await db.refresh(agent_message)
    return ChatResponse(conversation_id=conversation.id, reply=MessageOut.model_validate(agent_message))


@agents_router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)
    )
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    )
    return result.scalars().all()


# -------------------------------------------------------------- aggregation --

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(wallet_router)
api_router.include_router(agents_router)
