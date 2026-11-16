"""Config flow for Advanced Google Calendar."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import GoogleCalendarApi, GoogleCalendarApiError, GoogleCalendarInfo
from .const import (
    CONF_CALENDARS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    OAUTH2_SCOPE,
)

_LOGGER = logging.getLogger(__name__)

READ_ONLY_MARKER = " \U0001f512"  # lock symbol for read-only calendars


def _calendar_options(calendars: list[GoogleCalendarInfo]) -> list[SelectOptionDict]:
    """Return the selector options for a list of calendars."""
    ordered = sorted(
        calendars, key=lambda cal: (not cal.primary, cal.summary.casefold())
    )
    return [
        SelectOptionDict(
            value=cal.calendar_id,
            label=cal.summary if cal.writable else f"{cal.summary}{READ_ONLY_MARKER}",
        )
        for cal in ordered
    ]


def _calendar_schema(
    calendars: list[GoogleCalendarInfo],
    selected: list[str],
    scan_interval: int,
) -> vol.Schema:
    """Return the schema to select calendars and the poll interval."""
    known = {cal.calendar_id for cal in calendars}
    return vol.Schema(
        {
            vol.Optional(
                CONF_CALENDARS,
                default=[cid for cid in selected if cid in known],
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_calendar_options(calendars),
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_SCAN_INTERVAL, default=scan_interval): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
        }
    )


def _options_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize the form input."""
    return {
        CONF_CALENDARS: list(user_input.get(CONF_CALENDARS, [])),
        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
    }


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle the OAuth2 config flow (one entry per Google account)."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._calendars: list[GoogleCalendarInfo] = []

    @property
    def logger(self) -> logging.Logger:
        """Return the logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Request offline access so that a refresh token is issued."""
        return {
            "scope": OAUTH2_SCOPE,
            "access_type": "offline",
            # Always show the account chooser (several Google accounts) and the
            # consent screen (guarantees a refresh token)
            "prompt": "select_account consent",
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return OptionsFlowHandler()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauthentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"account": self._get_reauth_entry().title},
            )
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Called after a successful OAuth login."""
        access_token = data["token"]["access_token"]

        async def _token() -> str:
            return str(access_token)

        api = GoogleCalendarApi(async_get_clientsession(self.hass), _token)
        try:
            calendars = await api.async_list_calendars()
        except GoogleCalendarApiError as err:
            _LOGGER.error("Could not load calendar list: %s", err)
            return self.async_abort(reason="cannot_connect")

        primary = next((cal for cal in calendars if cal.primary), None)
        if primary is None:
            return self.async_abort(reason="no_primary_calendar")

        await self.async_set_unique_id(primary.calendar_id.lower())

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )

        self._abort_if_unique_id_configured()

        self._data = data
        self._calendars = calendars
        return await self.async_step_calendars()

    async def async_step_calendars(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose the calendars to synchronize."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options = _options_from_input(user_input)
            if not options[CONF_CALENDARS]:
                errors[CONF_CALENDARS] = "no_calendar_selected"
            else:
                return self.async_create_entry(
                    title=str(self.unique_id),
                    data=self._data,
                    options=options,
                )

        default_selected = [cal.calendar_id for cal in self._calendars if cal.primary]
        return self.async_show_form(
            step_id="calendars",
            data_schema=_calendar_schema(
                self._calendars,
                user_input.get(CONF_CALENDARS, default_selected)
                if user_input
                else default_selected,
                DEFAULT_SCAN_INTERVAL,
            ),
            errors=errors,
            description_placeholders={"account": str(self.unique_id)},
        )


class OptionsFlowHandler(OptionsFlow):
    """Change the synchronized calendars of an existing account."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the calendar selection."""
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")

        try:
            calendars = await entry.runtime_data.api.async_list_calendars()
        except GoogleCalendarApiError as err:
            _LOGGER.error("Could not load calendar list: %s", err)
            return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        if user_input is not None:
            options = _options_from_input(user_input)
            if not options[CONF_CALENDARS]:
                errors[CONF_CALENDARS] = "no_calendar_selected"
            else:
                return self.async_create_entry(data=options)

        current = (
            user_input.get(CONF_CALENDARS, [])
            if user_input
            else entry.options.get(CONF_CALENDARS, [])
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_calendar_schema(
                calendars,
                current,
                int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            ),
            errors=errors,
            description_placeholders={"account": entry.title},
        )
