"""Entity services of Advanced Google Calendar."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import VolDictType

from .const import (
    ATTR_DAYS_FUTURE,
    ATTR_DAYS_PAST,
    ATTR_DESCRIPTION,
    ATTR_DRY_RUN,
    ATTR_DURATION,
    ATTR_END_DATE,
    ATTR_END_DATE_TIME,
    ATTR_EXCLUDE_REGEX,
    ATTR_INCLUDE_ALL_DAY,
    ATTR_INCLUDE_DETAILS,
    ATTR_INCLUDE_REGEX,
    ATTR_LOCATION,
    ATTR_RECURRENCE_ID,
    ATTR_RECURRENCE_RANGE,
    ATTR_RRULE,
    ATTR_SOURCE_ENTITY_ID,
    ATTR_START_DATE,
    ATTR_START_DATE_TIME,
    ATTR_SUMMARY,
    ATTR_UID,
    DEFAULT_DAYS_FUTURE,
    DEFAULT_DAYS_PAST,
    DOMAIN,
    MAX_DAYS_FUTURE,
    MAX_DAYS_PAST,
    RANGE_THIS_AND_FUTURE,
    SERVICE_DELETE_EVENT,
    SERVICE_LIST_EVENTS,
    SERVICE_SYNC_CALENDAR,
    SERVICE_UPDATE_EVENT,
)

RECURRENCE_RANGE = vol.In(["", RANGE_THIS_AND_FUTURE])

UPDATE_EVENT_SCHEMA: VolDictType = {
    vol.Required(ATTR_UID): cv.string,
    vol.Optional(ATTR_RECURRENCE_ID): cv.string,
    vol.Optional(ATTR_RECURRENCE_RANGE): RECURRENCE_RANGE,
    vol.Optional(ATTR_SUMMARY): cv.string,
    vol.Optional(ATTR_DESCRIPTION): cv.string,
    vol.Optional(ATTR_LOCATION): cv.string,
    vol.Exclusive(ATTR_START_DATE, "start"): cv.date,
    vol.Exclusive(ATTR_START_DATE_TIME, "start"): cv.datetime,
    vol.Exclusive(ATTR_END_DATE, "end"): cv.date,
    vol.Exclusive(ATTR_END_DATE_TIME, "end"): cv.datetime,
    vol.Optional(ATTR_RRULE): vol.Any(cv.string, ""),
}

DELETE_EVENT_SCHEMA: VolDictType = {
    vol.Required(ATTR_UID): cv.string,
    vol.Optional(ATTR_RECURRENCE_ID): cv.string,
    vol.Optional(ATTR_RECURRENCE_RANGE): RECURRENCE_RANGE,
}

LIST_EVENTS_SCHEMA: VolDictType = {
    vol.Optional(ATTR_START_DATE_TIME): cv.datetime,
    vol.Exclusive(ATTR_END_DATE_TIME, "end"): cv.datetime,
    vol.Exclusive(ATTR_DURATION, "end"): vol.All(cv.time_period, cv.positive_timedelta),
}

SYNC_CALENDAR_SCHEMA: VolDictType = {
    vol.Required(ATTR_SOURCE_ENTITY_ID): cv.entity_domain(CALENDAR_DOMAIN),
    vol.Optional(ATTR_DAYS_PAST, default=DEFAULT_DAYS_PAST): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=MAX_DAYS_PAST)
    ),
    vol.Optional(ATTR_DAYS_FUTURE, default=DEFAULT_DAYS_FUTURE): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=MAX_DAYS_FUTURE)
    ),
    vol.Optional(ATTR_INCLUDE_DETAILS, default=True): cv.boolean,
    vol.Optional(ATTR_INCLUDE_ALL_DAY, default=True): cv.boolean,
    vol.Optional(ATTR_INCLUDE_REGEX): vol.Any(None, cv.string),
    vol.Optional(ATTR_EXCLUDE_REGEX): vol.Any(None, cv.string),
    vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the entity services of the integration."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_UPDATE_EVENT,
        entity_domain=CALENDAR_DOMAIN,
        schema=UPDATE_EVENT_SCHEMA,
        func="async_update_event_service",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_EVENT,
        entity_domain=CALENDAR_DOMAIN,
        schema=DELETE_EVENT_SCHEMA,
        func="async_delete_event_service",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_LIST_EVENTS,
        entity_domain=CALENDAR_DOMAIN,
        schema=LIST_EVENTS_SCHEMA,
        func="async_list_events_service",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SYNC_CALENDAR,
        entity_domain=CALENDAR_DOMAIN,
        schema=SYNC_CALENDAR_SCHEMA,
        func="async_sync_calendar_service",
        supports_response=SupportsResponse.OPTIONAL,
    )
