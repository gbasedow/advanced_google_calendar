"""Constants for the Advanced Google Calendar integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "advanced_google_calendar"

OAUTH2_AUTHORIZE: Final = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH2_TOKEN: Final = "https://oauth2.googleapis.com/token"
OAUTH2_SCOPE: Final = "https://www.googleapis.com/auth/calendar"

API_BASE_URL: Final = "https://www.googleapis.com/calendar/v3"

# Options
CONF_CALENDARS: Final = "calendars"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 5  # minutes
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 60

# Number of upcoming events fetched by the coordinator (for the entity state)
UPCOMING_EVENT_COUNT: Final = 10

# Access roles of a Google calendar that allow writing events
WRITE_ACCESS_ROLES: Final = ("owner", "writer")

# Recurrence handling
RRULE_PREFIX: Final = "RRULE:"
RANGE_THIS_AND_FUTURE: Final = "THISANDFUTURE"

# Services
SERVICE_UPDATE_EVENT: Final = "update_event"
SERVICE_DELETE_EVENT: Final = "delete_event"
SERVICE_LIST_EVENTS: Final = "list_events"
SERVICE_SYNC_CALENDAR: Final = "sync_calendar"

ATTR_UID: Final = "uid"
ATTR_RECURRENCE_ID: Final = "recurrence_id"
ATTR_RECURRENCE_RANGE: Final = "recurrence_range"
ATTR_SUMMARY: Final = "summary"
ATTR_DESCRIPTION: Final = "description"
ATTR_LOCATION: Final = "location"
ATTR_START_DATE: Final = "start_date"
ATTR_END_DATE: Final = "end_date"
ATTR_START_DATE_TIME: Final = "start_date_time"
ATTR_END_DATE_TIME: Final = "end_date_time"
ATTR_RRULE: Final = "rrule"
ATTR_DURATION: Final = "duration"

# One-way calendar sync
ATTR_SOURCE_ENTITY_ID: Final = "source_entity_id"
ATTR_TARGET_ENTITY_ID: Final = "target_entity_id"
ATTR_DAYS_PAST: Final = "days_past"
ATTR_DAYS_FUTURE: Final = "days_future"
ATTR_INCLUDE_DETAILS: Final = "include_details"
ATTR_INCLUDE_ALL_DAY: Final = "include_all_day"
ATTR_INCLUDE_REGEX: Final = "include_regex"
ATTR_EXCLUDE_REGEX: Final = "exclude_regex"
ATTR_DRY_RUN: Final = "dry_run"

DEFAULT_DAYS_PAST: Final = 7
DEFAULT_DAYS_FUTURE: Final = 30
MAX_DAYS_PAST: Final = 365
MAX_DAYS_FUTURE: Final = 730

# Private extended properties of mirrored events
PROP_SOURCE: Final = "agcSource"
PROP_KEY: Final = "agcKey"
PROP_HASH: Final = "agcHash"
