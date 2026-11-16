"""Minimal async client for the Google Calendar REST API (v3)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
import logging
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientResponseError, ClientSession

from homeassistant.util import dt as dt_util

from .const import API_BASE_URL, WRITE_ACCESS_ROLES

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
MAX_PAGE_SIZE = 2500

type TokenProvider = Callable[[], Awaitable[str]]


class GoogleCalendarApiError(Exception):
    """Generic error talking to the Google Calendar API."""


class GoogleCalendarAuthError(GoogleCalendarApiError):
    """Authentication with Google failed (token invalid or revoked)."""


class GoogleCalendarNotFoundError(GoogleCalendarApiError):
    """The requested calendar or event does not exist (anymore)."""


@dataclass(frozen=True, slots=True)
class GoogleCalendarInfo:
    """Information about a calendar from the user's calendar list."""

    calendar_id: str
    summary: str
    access_role: str
    primary: bool = False
    time_zone: str | None = None

    @property
    def writable(self) -> bool:
        """Return True if events of this calendar can be modified."""
        return self.access_role in WRITE_ACCESS_ROLES


def _quote(value: str) -> str:
    """Quote a path segment (calendar ids contain '@' and '#')."""
    return quote(value, safe="")


def _rfc3339(value: datetime) -> str:
    """Format a datetime as RFC3339 string as required by the API."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return value.isoformat()


class GoogleCalendarApi:
    """Thin wrapper around the Google Calendar REST API."""

    def __init__(self, session: ClientSession, token_provider: TokenProvider) -> None:
        """Initialize the API client."""
        self._session = session
        self._token_provider = token_provider

    async def _async_get_token(self) -> str:
        """Return a valid access token."""
        try:
            return await self._token_provider()
        except ClientResponseError as err:
            if HTTPStatus.BAD_REQUEST <= err.status < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise GoogleCalendarAuthError(
                    f"Refreshing the access token failed: {err.message}"
                ) from err
            raise GoogleCalendarApiError(
                f"Refreshing the access token failed: {err.message}"
            ) from err
        except (ClientError, TimeoutError) as err:
            raise GoogleCalendarApiError(
                f"Refreshing the access token failed: {err}"
            ) from err

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a request and return the decoded JSON body."""
        token = await self._async_get_token()
        url = f"{API_BASE_URL}{path}"
        _LOGGER.debug("%s %s params=%s body=%s", method, path, params, json)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    if resp.status == HTTPStatus.NO_CONTENT:
                        return {}
                    try:
                        payload: Any = await resp.json(content_type=None)
                    except ValueError:
                        payload = None
                    if resp.status >= HTTPStatus.BAD_REQUEST:
                        self._raise_for_status(resp.status, payload)
        except (ClientError, TimeoutError) as err:
            raise GoogleCalendarApiError(
                f"Error communicating with Google Calendar API: {err}"
            ) from err
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _raise_for_status(status: int, payload: Any) -> None:
        """Raise a matching exception for an error response."""
        message = f"HTTP {status}"
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            message = f"{message}: {payload['error'].get('message', '')}".strip()
        if status == HTTPStatus.UNAUTHORIZED:
            raise GoogleCalendarAuthError(message)
        if status in (HTTPStatus.NOT_FOUND, HTTPStatus.GONE):
            raise GoogleCalendarNotFoundError(message)
        raise GoogleCalendarApiError(message)

    # ------------------------------------------------------------------ #
    # Calendar list
    # ------------------------------------------------------------------ #
    async def async_list_calendars(self) -> list[GoogleCalendarInfo]:
        """Return all calendars of the authenticated user."""
        calendars: list[GoogleCalendarInfo] = []
        params: dict[str, Any] = {"maxResults": 250, "showHidden": "true"}
        while True:
            data = await self._async_request(
                "GET", "/users/me/calendarList", params=params
            )
            for item in data.get("items", []):
                if item.get("deleted"):
                    continue
                calendars.append(
                    GoogleCalendarInfo(
                        calendar_id=item["id"],
                        summary=item.get("summaryOverride")
                        or item.get("summary")
                        or item["id"],
                        access_role=item.get("accessRole", "reader"),
                        primary=bool(item.get("primary", False)),
                        time_zone=item.get("timeZone"),
                    )
                )
            if not (page_token := data.get("nextPageToken")):
                break
            params["pageToken"] = page_token
        return calendars

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    async def async_list_events(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """List events (recurring events expanded to single instances)."""
        params: dict[str, Any] = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": _rfc3339(time_min),
            "maxResults": min(max_results or MAX_PAGE_SIZE, MAX_PAGE_SIZE),
        }
        if time_max is not None:
            params["timeMax"] = _rfc3339(time_max)

        items: list[dict[str, Any]] = []
        while True:
            data = await self._async_request(
                "GET", f"/calendars/{_quote(calendar_id)}/events", params=params
            )
            items.extend(data.get("items", []))
            if max_results is not None and len(items) >= max_results:
                return items[:max_results]
            if not (page_token := data.get("nextPageToken")):
                break
            params["pageToken"] = page_token
        return items

    async def async_get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        """Return a single event (or a single instance of a recurring event)."""
        return await self._async_request(
            "GET", f"/calendars/{_quote(calendar_id)}/events/{_quote(event_id)}"
        )

    async def async_insert_event(
        self, calendar_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new event."""
        return await self._async_request(
            "POST", f"/calendars/{_quote(calendar_id)}/events", json=body
        )

    async def async_patch_event(
        self, calendar_id: str, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Modify an existing event (only the fields contained in body)."""
        return await self._async_request(
            "PATCH",
            f"/calendars/{_quote(calendar_id)}/events/{_quote(event_id)}",
            json=body,
        )

    async def async_delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete an event (or cancel a single instance of a recurring event)."""
        await self._async_request(
            "DELETE", f"/calendars/{_quote(calendar_id)}/events/{_quote(event_id)}"
        )
