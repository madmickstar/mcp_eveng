from __future__ import annotations

import pytest

from mcp_eveng.client import EvengClient
from mcp_eveng.config import EvengSettings


@pytest.fixture
def eveng_settings() -> EvengSettings:
    """Settings pointing at a fake EVENG host, independent of any real .env file."""
    return EvengSettings(
        host="eveng.test",
        port=80,
        protocol="http",
        username="admin",
        password="eve",
        html5="-1",
        verify_ssl=True,
        timeout_seconds=5,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def base_url(eveng_settings: EvengSettings) -> str:
    return eveng_settings.base_url


@pytest.fixture
async def client(eveng_settings: EvengSettings):
    """An EvengClient whose requests are intercepted by the `httpx_mock` fixture."""
    c = EvengClient(settings=eveng_settings)
    yield c
    await c.aclose()
