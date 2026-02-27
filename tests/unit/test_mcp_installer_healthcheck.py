from unittest.mock import MagicMock

import pytest
import fastapi.dependencies.utils as fastapi_dep_utils

# Avoid hard dependency on python-multipart during module import.
fastapi_dep_utils.ensure_multipart_is_installed = lambda: None
from mcp import installer as mcp_installer


def test_reload_hub_registry_prefers_reload_registry():
    hub = MagicMock()
    method = mcp_installer._reload_hub_registry(hub)
    assert method == "reload_registry"
    hub.reload_registry.assert_called_once()
    hub.refresh.assert_not_called()


def test_reload_hub_registry_falls_back_to_refresh():
    hub = MagicMock()
    hub.reload_registry = None
    method = mcp_installer._reload_hub_registry(hub)
    assert method == "refresh"
    hub.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_post_install_health_check_returns_healthy_when_online():
    hub = MagicMock()
    hub.list_mcps.return_value = [{"name": "demo-mcp", "online": True}]
    result = await mcp_installer._run_post_install_health_check(hub, "demo-mcp", attempts=1, delay_s=0.0)
    assert result == {"status": "healthy", "reason": "online"}


@pytest.mark.asyncio
async def test_post_install_health_check_returns_unhealthy_when_offline():
    hub = MagicMock()
    hub.list_mcps.return_value = [{"name": "demo-mcp", "online": False}]
    result = await mcp_installer._run_post_install_health_check(hub, "demo-mcp", attempts=2, delay_s=0.0)
    assert result["status"] == "unhealthy"
    assert result["reason"] == "mcp_listed_offline"


@pytest.mark.asyncio
async def test_post_install_health_check_returns_unknown_without_list_mcps():
    hub = object()
    result = await mcp_installer._run_post_install_health_check(hub, "demo-mcp", attempts=1, delay_s=0.0)
    assert result == {"status": "unknown", "reason": "hub_missing_list_mcps"}
