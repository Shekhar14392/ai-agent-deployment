"""
Unified AI provider layer.

Every AI agent in the platform (Sales, Support, Lead-Gen, Appointment, Analytics)
calls `generate_reply()` below. The provider actually used is resolved per-request:

  1. explicit `provider` argument (user picked one in the UI), else
  2. account's saved preference (not modeled in Phase 1, defaults to settings), else
  3. settings.DEFAULT_AI_PROVIDER

This means swapping providers is a config change, not a code change, and a user
can be on OpenAI while another is on Claude with zero branching in the callers.
"""
from __future__ import annotations

import enum
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings

settings = get_settings()


class Provider(str, enum.Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"


AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "sales": (
        "You are the Sales agent for a business on the Global AI Solutions platform. "
        "Qualify the lead, answer product/pricing questions, and move the conversation "
        "toward a booked call or purchase. Be concise, warm, and never invent pricing "
        "or facts you were not given."
    ),
    "support": (
        "You are the Customer Support agent for a business on the Global AI Solutions "
        "platform. Resolve the customer's issue clearly and briefly. If the issue needs "
        "a human (refunds, disputes, account security), say you're escalating it rather "
        "than guessing at a resolution."
    ),
    "lead_gen": (
        "You are the Lead Generation agent. Your job is to identify buying intent in a "
        "conversation and capture the lead's name, contact info, and need. Ask one "
        "focused question at a time."
    ),
    "appointment": (
        "You are the Appointment Booking agent. Help the user find a time that works and "
        "confirm the booking details clearly (date, time, timezone, what the meeting covers)."
    ),
    "analytics": (
        "You are the Analytics agent. Given business metrics or questions about performance, "
        "give clear, numbers-first answers and flag notable trends. Do not fabricate figures "
        "you were not given."
    ),
}


class AIProviderError(Exception):
    pass


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _call_anthropic(system: str, history: list[dict]) -> str:
    import anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise AIProviderError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=history,
    )
    return "".join(block.text for block in response.content if block.type == "text")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _call_openai(system: str, history: list[dict]) -> str:
    from openai import AsyncOpenAI

    if not settings.OPENAI_API_KEY:
        raise AIProviderError("OPENAI_API_KEY is not configured")

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    messages = [{"role": "system", "content": system}, *history]
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _call_gemini(system: str, history: list[dict]) -> str:
    import google.generativeai as genai

    if not settings.GEMINI_API_KEY:
        raise AIProviderError("GEMINI_API_KEY is not configured")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name="gemini-1.5-pro", system_instruction=system)
    # Gemini expects roles "user"/"model" instead of "user"/"assistant"
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [m["content"]]} for m in history
    ]
    response = await model.generate_content_async(contents)
    return response.text or ""


PROVIDER_DISPATCH = {
    Provider.ANTHROPIC: _call_anthropic,
    Provider.OPENAI: _call_openai,
    Provider.GEMINI: _call_gemini,
}


async def generate_reply(
    agent_type: str,
    history: list[dict],
    provider: Optional[str] = None,
) -> tuple[str, str]:
    """
    Returns (reply_text, provider_used).
    `history` is a list of {"role": "user"|"assistant", "content": str}, oldest first.
    """
    resolved_provider = Provider(provider or settings.DEFAULT_AI_PROVIDER)
    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_type, "You are a helpful business assistant.")

    call_fn = PROVIDER_DISPATCH[resolved_provider]
    try:
        reply = await call_fn(system_prompt, history)
    except AIProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalize all provider SDK errors
        raise AIProviderError(f"{resolved_provider.value} request failed: {exc}") from exc

    return reply, resolved_provider.value
