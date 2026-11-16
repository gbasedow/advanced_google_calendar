"""Data update coordinator for Advanced Google Calendar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    GoogleCalendarApi,
    GoogleCalendarApiError,
    GoogleCalendarAuthError,
    GoogleCalendarInfo,
)
from .const import DOMAIN, UPCOMING_EVENT_COUNT
from .convert import google_event_to_calendar_event

_LOGGER = logging.getLogger(__name__)


@dataclass
class AdvancedGoogleCalendarData:
    """Runtime data of a config entry (one Google account)."""

    api: GoogleCalendarApi
    account: str
    calendars: dict[str, GoogleCalendarInfo] = field(default_factory=dict)
    coordinators: dict[str, CalendarUpdateCoordinator] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


type AdvancedGoogleCalendarConfigEntry = ConfigEntry[AdvancedGoogleCalendarData]


class CalendarUpdateCoordinator(DataUpdateCoordinator[list[CalendarEvent]]):
    """Fetch the upcoming events of one Google calendar."""

    config_entry: AdvancedGoogleCalendarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AdvancedGoogleCalendarConfigEntry,
        api: GoogleCalendarApi,
        calendar: GoogleCalendarInfo,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {calendar.calendar_id}",
            update_interval=update_interval,
        )
        self.api = api
        self.calendar = calendar

    async def _async_update_data(self) -> list[CalendarEvent]:
        """Fetch the next upcoming events (used for the entity state)."""
        try:
            items = await self.api.async_list_events(
                self.calendar.calendar_id,
                time_min=dt_util.now(),
                max_results=UPCOMING_EVENT_COUNT,
            )
        except GoogleCalendarAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GoogleCalendarApiError as err:
            raise UpdateFailed(str(err)) from err

        events: list[CalendarEvent] = []
        for item in items:
            if (event := google_event_to_calendar_event(item)) is not None:
                events.append(event)
        return events
