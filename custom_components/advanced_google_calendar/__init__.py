"""The Advanced Google Calendar integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from aiohttp import ClientError, ClientResponseError

from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    config_entry_oauth2_flow,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import GoogleCalendarApi, GoogleCalendarApiError, GoogleCalendarAuthError
from .const import CONF_CALENDARS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import (
    AdvancedGoogleCalendarConfigEntry,
    AdvancedGoogleCalendarData,
    CalendarUpdateCoordinator,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (register services once)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: AdvancedGoogleCalendarConfigEntry
) -> bool:
    """Set up one Google account from a config entry."""
    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except ValueError as err:
        # Application credentials were removed
        raise ConfigEntryNotReady(
            "OAuth implementation not available, please check the application "
            "credentials"
        ) from err

    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    try:
        await session.async_ensure_token_valid()
    except ClientResponseError as err:
        if 400 <= err.status < 500:
            raise ConfigEntryAuthFailed(
                "Google rejected the stored credentials, please re-authenticate"
            ) from err
        raise ConfigEntryNotReady(f"Could not refresh token: {err}") from err
    except (ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(f"Could not refresh token: {err}") from err

    async def _token_provider() -> str:
        await session.async_ensure_token_valid()
        return str(session.token["access_token"])

    api = GoogleCalendarApi(async_get_clientsession(hass), _token_provider)

    try:
        all_calendars = await api.async_list_calendars()
    except GoogleCalendarAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except GoogleCalendarApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    selected: list[str] = entry.options.get(CONF_CALENDARS, [])
    available = {cal.calendar_id: cal for cal in all_calendars}
    for calendar_id in selected:
        if calendar_id not in available:
            _LOGGER.warning(
                "Calendar %s is no longer available for %s and is skipped",
                calendar_id,
                entry.title,
            )

    data = AdvancedGoogleCalendarData(
        api=api,
        account=entry.unique_id or entry.title,
        calendars={cid: available[cid] for cid in selected if cid in available},
        options=dict(entry.options),
    )

    interval = timedelta(
        minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    for calendar_id, calendar in data.calendars.items():
        coordinator = CalendarUpdateCoordinator(hass, entry, api, calendar, interval)
        await coordinator.async_config_entry_first_refresh()
        data.coordinators[calendar_id] = coordinator

    entry.runtime_data = data

    _async_remove_stale_entities(hass, entry, set(data.calendars))
    _async_remove_legacy_device(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_remove_stale_entities(
    hass: HomeAssistant,
    entry: AdvancedGoogleCalendarConfigEntry,
    active_calendar_ids: set[str],
) -> None:
    """Remove entities of calendars that were deselected in the options."""
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}-"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != CALENDAR_DOMAIN:
            continue
        calendar_id = reg_entry.unique_id.removeprefix(prefix)
        if calendar_id not in active_calendar_ids:
            _LOGGER.debug(
                "Removing entity %s (calendar deselected)", reg_entry.entity_id
            )
            registry.async_remove(reg_entry.entity_id)


def _async_remove_legacy_device(
    hass: HomeAssistant, entry: AdvancedGoogleCalendarConfigEntry
) -> None:
    """Remove the per-account device created by versions before 0.5.0.

    Calendars are no longer grouped under a device; the entities belong
    directly to the config entry.
    """
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, str(entry.unique_id))}
    )
    if device is None or entry.entry_id not in device.config_entries:
        return
    # Detach the entities first: removing a device also removes the entities
    # attached to it, which would lose entity ids and user customizations.
    entity_registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_device(
        entity_registry, device.id, include_disabled_entities=True
    ):
        if reg_entry.config_entry_id == entry.entry_id:
            entity_registry.async_update_entity(reg_entry.entity_id, device_id=None)
    device_registry.async_update_device(
        device.id, remove_config_entry_id=entry.entry_id
    )


async def _async_update_listener(
    hass: HomeAssistant, entry: AdvancedGoogleCalendarConfigEntry
) -> None:
    """Reload the entry when the options were changed.

    The listener is also called when the OAuth token in entry.data is refreshed;
    in that case nothing needs to be done.
    """
    if dict(entry.options) == entry.runtime_data.options:
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: AdvancedGoogleCalendarConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
