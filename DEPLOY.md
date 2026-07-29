# Going Live — Entirely From Your Phone (Render, free tier)

No computer needed. Everything below works from your Android browser.

## What this deploys

- `site/` — one Node service: serves the website, the admin panel, AND proxies
  to the backend — so you only ever visit ONE url from your phone.
- `global-ai-solutions/backend/` — the FastAPI backend (auth, wallet, AI agents, database).
- A free Postgres database, provisioned automatically.

`render.yaml` describes all of this as one "Blueprint" so Render sets it up together.

## Steps (phone browser only)

1. **GitHub** (github.com, free): create a repo, upload this entire folder
   (`site/`, `global-ai-solutions/`, `android/`, `render.yaml` — all of it) using
   "Add file → Upload files."
2. **Render** (render.com, free): sign up → **New → Blueprint** → connect the
   GitHub repo you just made. Render reads `render.yaml` and sets up both
   services + the database automatically.
3. When prompted, fill in the environment variables it flags as required:
   - `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (from developer.paypal.com, phone browser works fine)
   - `ANTHROPIC_API_KEY` (or swap `DEFAULT_AI_PROVIDER`/keys for OpenAI or Gemini)
4. Tap **Apply** / **Deploy**. Render builds both services — takes a few minutes.
5. You get a real URL like `https://global-ai-solutions-site.onrender.com` —
   open it on your phone. That's your live site.
6. Admin panel: same URL + `/admin` — e.g.
   `https://global-ai-solutions-site.onrender.com/admin` — log in with an
   admin account (see below), manage everything from your phone.

## Creating your first admin account (phone browser)

Render's free tier includes a web shell you can open from your phone via the
Render dashboard → your backend service → **Shell** tab. Run:

```bash
python -c "
import asyncio
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.wallet import Wallet
import uuid

async def make_admin():
    async with AsyncSessionLocal() as db:
        user = User(email='you@yourbusiness.com', hashed_password=hash_password('ChangeThisPassword123!'),
                    full_name='Admin', role=UserRole.SUPER_ADMIN)
        db.add(user); await db.flush()
        db.add(Wallet(user_id=user.id)); await db.commit()
        print('Admin created:', user.email)

asyncio.run(make_admin())
"
```

Then log into `/admin` with that email/password.

## What's real vs. what's a free-tier trade-off

- Real: live PayPal payments, real database, real AI agents, real admin control — all yours.
- Trade-off: Render's free tier sleeps a service after 15 min of no traffic (wakes
  on the next visit, ~30s delay). Fine for testing/early users; upgrade to Render's
  paid tier (~$7/mo) later for always-on, once you have real traffic.

## Still only you can do this part

Verify your real PayPal Business account (bank + identity, PayPal-side, unavoidable),
and if you want the Android app store-published, your Google Play Developer account.
