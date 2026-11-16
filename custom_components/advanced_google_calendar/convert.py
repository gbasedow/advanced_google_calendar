"""Conversion between Google Calendar API objects and Home Assistant objects."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEvent
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import RRULE_PREFIX

_LOGGER = logging.getLogger(__name__)

# Fields copied from a series to a new series when it is split ("this and future")
INHERITED_SERIES_FIELDS = (
    "colorId",
    "reminders",
    "transparency",
    "visibility",
    "extendedProperties",
)


# ---------------------------------------------------------------------- #
# Google -> Home Assistant
# ---------------------------------------------------------------------- #
def parse_google_time(value: Mapping[str, Any] | None) -> date | datetime | None:
    """Parse a Google 'start'/'end'/'originalStartTime' object."""
    if not value:
        return None
    if raw := value.get("dateTime"):
        parsed = dt_util.parse_datetime(raw)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            tz = dt_util.get_time_zone(value.get("timeZone") or "") or (
                dt_util.get_default_time_zone()
            )
            parsed = parsed.replace(tzinfo=tz)
        return dt_util.as_local(parsed)
    if raw := value.get("date"):
        return dt_util.parse_date(raw)
    return None


def extract_rrule(recurrence: list[str] | None) -> str | None:
    """Return the RRULE (without prefix) of a Google recurrence list."""
    for line in recurrence or []:
        if line.startswith(RRULE_PREFIX):
            return line.removeprefix(RRULE_PREFIX)
    return None


def google_event_to_calendar_event(
    item: Mapping[str, Any], series_rrule: str | None = None
) -> CalendarEvent | None:
    """Convert a Google event resource into a Home Assistant CalendarEvent.

    For instances of recurring events (``recurringEventId`` present) the uid is the
    id of the series and the recurrence_id is the id of the instance. The rrule of
    the series has to be supplied by the caller (``series_rrule``) because the API
    does not return it for expanded instances.
    """
    if item.get("status") == "cancelled":
        return None

    start = parse_google_time(item.get("start"))
    end = parse_google_time(item.get("end"))
    if start is None:
        return None
    if end is None or type(end) is not type(start) or end < start:
        end = start + (
            timedelta(days=1) if not isinstance(start, datetime) else timedelta()
        )

    if series_id := item.get("recurringEventId"):
        uid: str = series_id
        recurrence_id: str | None = item["id"]
        rrule = series_rrule
    else:
        uid = item["id"]
        recurrence_id = None
        rrule = extract_rrule(item.get("recurrence"))

    kwargs: dict[str, Any] = {
        "start": start,
        "end": end,
        "summary": item.get("summary") or "",
        "description": item.get("description"),
        "location": item.get("location"),
        "uid": uid,
        "recurrence_id": recurrence_id,
    }
    try:
        return CalendarEvent(**kwargs, rrule=rrule)
    except HomeAssistantError:
        # Rules Home Assistant cannot handle (e.g. FREQ=HOURLY) are dropped,
        # the event itself is still shown.
        try:
            return CalendarEvent(**kwargs)
        except HomeAssistantError as err:
            _LOGGER.warning("Skipping invalid event %s: %s", item.get("id"), err)
            return None


# ---------------------------------------------------------------------- #
# Home Assistant -> Google
# ---------------------------------------------------------------------- #
def build_google_time(
    value: date | datetime, time_zone: str, *, for_patch: bool = False
) -> dict[str, Any]:
    """Build a Google 'start'/'end' object from a date or datetime."""
    if isinstance(value, datetime):
        tz = dt_util.get_time_zone(time_zone) or dt_util.get_default_time_zone()
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        result: dict[str, Any] = {
            "dateTime": value.astimezone(tz).isoformat(),
            "timeZone": time_zone,
        }
        if for_patch:
            result["date"] = None
        return result
    result = {"date": value.isoformat()}
    if for_patch:
        # Explicitly clear the fields of a former timed event
        result["dateTime"] = None
        result["timeZone"] = None
    return result


def build_google_body(
    data: Mapping[str, Any], time_zone: str, *, for_patch: bool = False
) -> dict[str, Any]:
    """Build a (partial) Google event body from Home Assistant event data.

    Keys of ``data`` follow the Home Assistant calendar conventions:
    summary, description, location, dtstart, dtend. Only present keys are
    converted, so the result can be used for PATCH requests. The rrule is
    handled separately by the caller.
    """
    body: dict[str, Any] = {}
    if "summary" in data:
        body["summary"] = data["summary"] or ""
    if "description" in data:
        body["description"] = data["description"] or ""
    if "location" in data:
        body["location"] = data["location"] or ""
    if (start := data.get("dtstart")) is not None:
        body["start"] = build_google_time(start, time_zone, for_patch=for_patch)
    if (end := data.get("dtend")) is not None:
        body["end"] = build_google_time(end, time_zone, for_patch=for_patch)
    return body


def replace_rrule(recurrence: list[str] | None, rrule: str | None) -> list[str]:
    """Replace (or remove, if rrule is empty) the RRULE in a recurrence list.

    Other lines (EXDATE, RDATE, ...) are kept as long as the event stays recurring.
    """
    if not rrule:
        return []
    others = [line for line in recurrence or [] if not line.startswith(RRULE_PREFIX)]
    return [f"{RRULE_PREFIX}{rrule}", *others]


def strip_rrule_end(rrule: str) -> str:
    """Remove COUNT and UNTIL from a rule (used when a series is split)."""
    parts = [
        part
        for part in rrule.split(";")
        if part and part.split("=", 1)[0].upper() not in ("COUNT", "UNTIL")
    ]
    return ";".join(parts)


def truncate_recurrence(
    recurrence: list[str], original_start: date | datetime
) -> list[str]:
    """End a series right before the given occurrence (sets RRULE UNTIL)."""
    if isinstance(original_start, datetime):
        until_dt = original_start.astimezone(UTC) - timedelta(seconds=1)
        until = until_dt.strftime("%Y%m%dT%H%M%SZ")
    else:
        until = (original_start - timedelta(days=1)).strftime("%Y%m%d")

    result: list[str] = []
    for line in recurrence:
        if line.startswith(RRULE_PREFIX):
            rule = strip_rrule_end(line.removeprefix(RRULE_PREFIX))
            result.append(f"{RRULE_PREFIX}{rule};UNTIL={until}")
        else:
            result.append(line)
    return result


def series_copy_body(series: Mapping[str, Any]) -> dict[str, Any]:
    """Return the fields of a series that should survive a split."""
    return {key: series[key] for key in INHERITED_SERIES_FIELDS if key in series}


def event_as_service_dict(event: CalendarEvent) -> dict[str, Any]:
    """Return a full dict representation (incl. uid) for service responses."""
    return {
        "uid": event.uid,
        "recurrence_id": event.recurrence_id,
        "rrule": event.rrule,
        "summary": event.summary,
        "description": event.description,
        "location": event.location,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "all_day": event.all_day,
    }
