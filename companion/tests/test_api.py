import httpx
import pytest

from snatcher.api import create_app
from snatcher.config import ConfigStore


class FakeSecrets:
    def get_deepgram_key(self):
        return "deepgram-test-key"

    def get_notion_token(self):
        return "notion-test-token"


@pytest.mark.asyncio
async def test_health_pairing_and_auth(tmp_path) -> None:
    app = create_app(
        config_store=ConfigStore(tmp_path),
        secret_store=FakeSecrets(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        health = await client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["ffmpeg"] is True
        assert health.json()["deepgram_configured"] is True

        assert (await client.get("/v1/settings")).status_code == 401
        bad_pair = await client.post("/v1/pair", json={"code": "00000000"})
        assert bad_pair.status_code == 401

        paired = await client.post("/v1/pair", json={"code": app.state.pairing_code})
        assert paired.status_code == 200
        token = paired.json()["token"]
        settings = await client.get(
            "/v1/settings",
            headers={"X-Snatcher-Token": token},
        )
        assert settings.status_code == 200
        assert "pair_token" not in settings.json()
