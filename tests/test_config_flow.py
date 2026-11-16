"""Tests for the config flow (OAuth2 + calendar selection) and reauth."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.advanced_google_calendar.const import (
    API_BASE_URL,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_SCOPE,
    OAUTH2_TOKEN,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow

from .conftest import ACCOUNT, CLIENT_ID, FakeGoogleApi

REDIRECT = "https://example.com/auth/external/callback"
CALENDAR_LIST = {
    "items": [
        {"id": ACCOUNT, "summary": ACCOUNT, "accessRole": "owner", "primary": True},
        {
            "id": "family@group.calendar.google.com",
            "summary": "Familie",
            "summaryOverride": "Familie (Override)",
            "accessRole": "writer",
        },
        {"id": "x@group.calendar.google.com", "summary": "Weg", "deleted": True},
    ]
}


async def _start_oauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    result: dict[str, Any],
    calendar_list: dict[str, Any] = CALENDAR_LIST,
) -> dict[str, Any]:
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    url = result["url"]
    assert url.startswith(OAUTH2_AUTHORIZE)
    assert f"client_id={CLIENT_ID}" in url
    assert "access_type=offline" in url
    assert "prompt=select_account+consent" in url
    assert "scope=https://www.googleapis.com/auth/calendar" in url.replace(
        "%3A", ":"
    ).replace("%2F", "/")

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == HTTPStatus.OK

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "refresh_token": "refresh",
            "access_token": "access",
            "token_type": "Bearer",
            "expires_in": 3599,
            "scope": OAUTH2_SCOPE,
        },
    )
    aioclient_mock.get(f"{API_BASE_URL}/users/me/calendarList", json=calendar_list)
    return await hass.config_entries.flow.async_configure(result["flow_id"])


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    fake_api: FakeGoogleApi,
) -> None:
    """Full flow: login, select calendars, entry is created."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _start_oauth(hass, hass_client_no_auth, aioclient_mock, result)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "calendars"

    # Error if nothing is selected
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"calendars": [], "scan_interval": 5}
    )
    assert result["errors"] == {"calendars": "no_calendar_selected"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "calendars": [ACCOUNT, "family@group.calendar.google.com"],
            "scan_interval": 3,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == ACCOUNT
    entry = result["result"]
    assert entry.unique_id == ACCOUNT
    assert entry.data["token"]["refresh_token"] == "refresh"
    assert entry.options == {
        "calendars": [ACCOUNT, "family@group.calendar.google.com"],
        "scan_interval": 3,
    }


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_second_account_and_duplicate(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The same account cannot be added twice, other accounts can."""
    MockConfigEntry(domain=DOMAIN, unique_id="other@example.com").add_to_hass(hass)
    MockConfigEntry(domain=DOMAIN, unique_id=ACCOUNT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _start_oauth(hass, hass_client_no_auth, aioclient_mock, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_flow_cannot_connect(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """API errors abort the flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    client = await hass_client_no_auth()
    await client.get(f"/auth/external/callback?code=abcd&state={state}")
    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 60,
            "token_type": "Bearer",
        },
    )
    aioclient_mock.get(
        f"{API_BASE_URL}/users/me/calendarList",
        status=500,
        json={"error": {"message": "backend"}},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize(
    ("account", "reason"),
    [(ACCOUNT, "reauth_successful"), ("someone@else.com", "wrong_account")],
)
async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    setup_integration: MockConfigEntry,
    account: str,
    reason: str,
) -> None:
    """Reauth updates the token, but only for the same account."""
    result = await setup_integration.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    calendar_list = {"items": [{"id": account, "accessRole": "owner", "primary": True}]}
    result = await _start_oauth(
        hass, hass_client_no_auth, aioclient_mock, result, calendar_list
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    if reason == "reauth_successful":
        assert setup_integration.data["token"]["expires_in"] == 3599
