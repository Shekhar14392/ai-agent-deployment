"""
workers.py — autonomous background jobs.
(Consolidated from workers/autonomous_followup.py + autonomous_followup_loop.py)

This is what makes the Sales agent act WITHOUT a human starting the conversation.

Run once:    python -m app.workers
Run forever: python -m app.workers --loop   (used by the Docker worker service)
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core import AsyncSessionLocal
from app.models import Lead, LeadActivity, LeadStage
from app.ai_providers import generate_reply

logger = logging.getLogger("autonomous_followup")

FOLLOW_UP_HOURS = 72  # follow up on leads untouched for 3 days


async def run_once() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FOLLOW_UP_HOURS)
    followed_up = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead).where(
                Lead.stage.in_([LeadStage.NEW, LeadStage.CONTACTED, LeadStage.QUALIFIED]),
                Lead.updated_at < cutoff,
            )
        )
        stale_leads = result.scalars().all()

        for lead in stale_leads:
            history = [
                {
                    "role": "user",
                    "content": (
                        f"Lead name: {lead.name}. Notes: {lead.notes or 'none'}. "
                        f"They haven't responded in {FOLLOW_UP_HOURS} hours. "
                        "Draft a brief, warm follow-up message."
                    ),
                }
            ]
            try:
                reply_text, provider_used = await generate_reply(agent_type="sales", history=history)
            except Exception as exc:  # noqa: BLE001
                logger.error("Follow-up generation failed for lead %s: %s", lead.id, exc)
                continue

            db.add(LeadActivity(lead_id=lead.id, activity_type="ai_followup", content=reply_text))
            lead.updated_at = datetime.now(timezone.utc)
            followed_up += 1

            # TODO: actually deliver this message via WhatsApp Business API or email, e.g.:
            #   await send_whatsapp_message(lead.phone, reply_text)
            logger.info("Drafted follow-up for lead %s via %s", lead.id, provider_used)

        await db.commit()

    return followed_up


async def run_forever(interval_seconds: int = 3600):
    while True:
        count = await run_once()
        logger.info("Autonomous follow-up cycle complete: %d leads contacted", count)
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if "--loop" in sys.argv:
        asyncio.run(run_forever())
    else:
        asyncio.run(run_once())
