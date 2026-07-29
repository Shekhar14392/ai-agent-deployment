import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_register_and_login_flow(client: AsyncClient):
    register_payload = {
        "email": "founder@example.com",
        "password": "SuperSecret123!",
        "full_name": "Ada Founder",
        "company_name": "Nomad Roasters",
    }
    register_resp = await client.post("/api/v1/auth/register", json=register_payload)
    assert register_resp.status_code == 201
    assert register_resp.json()["email"] == register_payload["email"]

    # duplicate registration should fail
    dup_resp = await client.post("/api/v1/auth/register", json=register_payload)
    assert dup_resp.status_code == 400

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    me_resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == register_payload["email"]


async def test_login_with_wrong_password_fails(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.com",
            "password": "CorrectHorse123!",
            "full_name": "Second User",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "second@example.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401
