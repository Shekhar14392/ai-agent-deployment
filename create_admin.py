import asyncio
import uuid
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.wallet import Wallet


async def make_admin():
    email = "shekors143@gmail.com"
    password = "Shekor39"
    full_name = "Admin"
    role = "ADMIN"

    async with AsyncSessionLocal() as db:
        async with db.begin():
            new_user = User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=role,
                is_active=True,
            )
            db.add(new_user)
            await db.flush()  # ensures new_user.id is available

            new_wallet = Wallet(
                id=uuid.uuid4(),
                user_id=new_user.id,
                balance=Decimal("0.00"),
                currency="USD",
            )
            db.add(new_wallet)

        print(f"✅ Admin created: {new_user.email} (id={new_user.id})")


if __name__ == "__main__":
    asyncio.run(make_admin())
