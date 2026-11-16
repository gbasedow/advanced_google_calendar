"""Calendar platform for Advanced Google Calendar."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import (
    DATA_COMPONENT as CALENDAR_DATA_COMPONENT,
    EVENT_RRULE,
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import (
    GoogleCalendarApiError,
    GoogleCalendarAuthError,
    GoogleCalendarNotFoundError,
)
from .const import (
    ATTR_DESCRIPTION,
    ATTR_END_DATE,
    ATTR_END_DATE_TIME,
    ATTR_LOCATION,
    ATTR_RECURRENCE_ID,
    ATTR_RECURRENCE_RANGE,
    ATTR_RRULE,
    ATTR_START_DATE,
    ATTR_START_DATE_TIME,
    ATTR_SUMMARY,
    ATTR_UID,
    DEFAULT_DAYS_FUTURE,
    DEFAULT_DAYS_PAST,
    DOMAIN,
    PROP_SOURCE,
    RANGE_THIS_AND_FUTURE,
    RRULE_PREFIX,
)
from .convert import (
    build_google_body,
    build_google_time,
    event_as_service_dict,
    extract_rrule,
    google_event_to_calendar_event,
    parse_google_time,
    replace_rrule,
    series_copy_body,
    strip_rrule_end,
    truncate_recurrence,
)
from .coordinator import AdvancedGoogleCalendarConfigEntry, CalendarUpdateCoordinator
from .sync import SyncOptions, SyncPlan, compile_regex, plan_sync

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
MAX_PARALLEL_SERIES_LOOKUPS = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AdvancedGoogleCalendarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar entities of one Google account."""
    data = entry.runtime_data
    async_add_entities(
        AdvancedGoogleCalendarEntity(data.coordinators[calendar_id], entry)
        for calendar_id in data.calendars
    )


def _as_local_datetime(value: date | datetime) -> datetime:
    """Return a comparable local datetime for a date or datetime."""
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    return dt_util.start_of_local_day(value)


class AdvancedGoogleCalendarEntity(
    CoordinatorEntity[CalendarUpdateCoordinator], CalendarEntity
):
    """A Google calendar synchronized in both directions."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CalendarUpdateCoordinator,
        entry: AdvancedGoogleCalendarConfigEntry,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        calendar = coordinator.calendar
        self._api = coordinator.api
        self._calendar_id = calendar.calendar_id
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}-{calendar.calendar_id}"
        self._attr_name = calendar.summary
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name=entry.title,
            manufacturer="Google",
            model="Google Calendar",
            entry_type=DeviceEntryType.SERVICE,
        )
        if calendar.writable:
            self._attr_supported_features = (
                CalendarEntityFeature.CREATE_EVENT
                | CalendarEntityFeature.DELETE_EVENT
                | CalendarEntityFeature.UPDATE_EVENT
            )
        self._attr_extra_state_attributes = {
            "calendar_id": calendar.calendar_id,
            "access_role": calendar.access_role,
        }
        # rrule of recurring series (id -> rrule) for expanded instances
        self._series_rrules: dict[str, str | None] = {}
        # Prevents parallel sync runs into this calendar
        self._sync_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #
    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        now = dt_util.now()
        for event in self.coordinator.data or []:
            if event.end_datetime_local > now:
                return event
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data; series rules may have changed in Google."""
        self._series_rrules.clear()
        super()._handle_coordinator_update()

    @property
    def _time_zone(self) -> str:
        return str(self.hass.config.time_zone)

    @contextmanager
    def _api_errors(self, action: str) -> Iterator[None]:
        """Translate API errors into Home Assistant errors."""
        try:
            yield
        except GoogleCalendarAuthError as err:
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                f"Google authentication failed while trying to {action}; "
                "please re-authenticate the integration"
            ) from err
        except GoogleCalendarNotFoundError as err:
            raise HomeAssistantError(
                f"Event not found while trying to {action}: {err}"
            ) from err
        except GoogleCalendarApiError as err:
            raise HomeAssistantError(
                f"Google Calendar error while trying to {action}: {err}"
            ) from err

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the events in the given time range (read live from Google)."""
        return await self._async_fetch_events(start_date, end_date)

    async def _async_fetch_events(
        self, start_date: datetime, end_date: datetime, *, skip_mirrors: bool = False
    ) -> list[CalendarEvent]:
        """Load and convert events; optionally without events created by a sync."""
        with self._api_errors("load events"):
            items = await self._api.async_list_events(
                self._calendar_id, time_min=start_date, time_max=end_date
            )
        await self._async_resolve_series_rrules(
            {item["recurringEventId"] for item in items if "recurringEventId" in item}
        )
        events: list[CalendarEvent] = []
        for item in items:
            if skip_mirrors and PROP_SOURCE in (
                (item.get("extendedProperties") or {}).get("private") or {}
            ):
                continue
            series_rrule = self._series_rrules.get(item.get("recurringEventId", ""))
            if (
                event := google_event_to_calendar_event(item, series_rrule)
            ) is not None:
                events.append(event)
        return events

    async def _async_resolve_series_rrules(self, series_ids: set[str]) -> None:
        """Load the rrule of recurring series that are not cached yet."""
        missing = [sid for sid in series_ids if sid not in self._series_rrules]
        if not missing:
            return
        semaphore = asyncio.Semaphore(MAX_PARALLEL_SERIES_LOOKUPS)

        async def _load(series_id: str) -> None:
            async with semaphore:
                try:
                    series = await self._api.async_get_event(
                        self._calendar_id, series_id
                    )
                except GoogleCalendarApiError as err:
                    _LOGGER.debug("Could not load series %s: %s", series_id, err)
                    self._series_rrules[series_id] = None
                    return
                self._series_rrules[series_id] = extract_rrule(series.get("recurrence"))

        await asyncio.gather(*(_load(sid) for sid in missing))

    async def async_sync_calendar_service(
        self,
        *,
        source_entity_id: str,
        days_past: int = DEFAULT_DAYS_PAST,
        days_future: int = DEFAULT_DAYS_FUTURE,
        include_details: bool = True,
        include_all_day: bool = True,
        include_regex: str | None = None,
        exclude_regex: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Service: mirror another calendar one-way into this calendar.

        Only events created by this sync relation (marked with private extended
        properties) are changed or deleted; other events are never touched.
        """
        self._ensure_writable()
        if source_entity_id == self.entity_id:
            raise ServiceValidationError("Source and target calendar must be different")
        source = self.hass.data[CALENDAR_DATA_COMPONENT].get_entity(source_entity_id)
        if not isinstance(source, CalendarEntity):
            raise ServiceValidationError(
                f"Source calendar {source_entity_id} not found"
            )
        options = SyncOptions(
            include_details=include_details,
            include_all_day=include_all_day,
            include_regex=compile_regex(include_regex, "include_regex"),
            exclude_regex=compile_regex(exclude_regex, "exclude_regex"),
        )
        registry_entry = er.async_get(self.hass).async_get(source_entity_id)
        source_id = registry_entry.id if registry_entry else source_entity_id

        today = dt_util.start_of_local_day()
        start = today - timedelta(days=days_past)
        end = today + timedelta(days=days_future + 1)

        async with self._sync_lock:
            try:
                if isinstance(source, AdvancedGoogleCalendarEntity):
                    # Mirrors are never mirrored again (prevents A->B->A loops)
                    source_events = await source._async_fetch_events(
                        start, end, skip_mirrors=True
                    )
                else:
                    source_events = await source.async_get_events(self.hass, start, end)
            except HomeAssistantError:
                raise
            except Exception as err:
                raise HomeAssistantError(
                    f"Could not read events of {source_entity_id}: {err}"
                ) from err
            with self._api_errors("load the mirrored events"):
                target_items = await self._api.async_list_events(
                    self._calendar_id,
                    time_min=start,
                    time_max=end,
                    private_extended_property=f"{PROP_SOURCE}={source_id}",
                )
            plan = plan_sync(
                source_events, target_items, source_id, options, self._time_zone
            )
            result: dict[str, Any] = {
                "created": len(plan.create),
                "updated": len(plan.update),
                "deleted": len(plan.delete),
                "unchanged": plan.unchanged,
                "errors": [],
            }
            if dry_run:
                result["dry_run"] = True
                result["to_create"] = [summary for summary, _ in plan.create]
                result["to_update"] = [summary for summary, _, _ in plan.update]
                result["to_delete"] = [summary for summary, _ in plan.delete]
                return result

            errors: list[str] = result["errors"]
            await self._async_execute_sync_plan(plan, errors)
            if errors:
                _LOGGER.warning(
                    "Sync %s -> %s finished with %d errors: %s",
                    source_entity_id,
                    self.entity_id,
                    len(errors),
                    errors,
                )
        _LOGGER.debug("Sync %s -> %s: %s", source_entity_id, self.entity_id, result)
        if plan.create or plan.update or plan.delete:
            await self.coordinator.async_refresh()
        return result

    async def _async_execute_sync_plan(self, plan: SyncPlan, errors: list[str]) -> None:
        """Write the planned changes; errors of single events are collected."""
        with self._api_errors("synchronize the calendar"):
            for summary, body in plan.create:
                try:
                    await self._api.async_insert_event(self._calendar_id, body)
                except GoogleCalendarAuthError:
                    raise
                except GoogleCalendarApiError as err:
                    errors.append(f"create '{summary}': {err}")
            for summary, event_id, body in plan.update:
                try:
                    await self._api.async_patch_event(self._calendar_id, event_id, body)
                except GoogleCalendarAuthError:
                    raise
                except GoogleCalendarApiError as err:
                    errors.append(f"update '{summary}': {err}")
            for summary, event_id in plan.delete:
                try:
                    await self._api.async_delete_event(self._calendar_id, event_id)
                except GoogleCalendarNotFoundError:
                    pass  # already gone
                except GoogleCalendarAuthError:
                    raise
                except GoogleCalendarApiError as err:
                    errors.append(f"delete '{summary}': {err}")

    async def async_list_events_service(
        self,
        start_date_time: datetime | None = None,
        end_date_time: datetime | None = None,
        duration: timedelta | None = None,
    ) -> dict[str, Any]:
        """Service: return events including uid / recurrence_id."""
        start = dt_util.as_local(start_date_time) if start_date_time else dt_util.now()
        if end_date_time is not None:
            end = dt_util.as_local(end_date_time)
        else:
            end = start + (duration or timedelta(days=1))
        if end <= start:
            raise ServiceValidationError("The end must be after the start")
        events = await self.async_get_events(self.hass, start, end)
        return {"events": [event_as_service_dict(event) for event in events]}

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #
    def _ensure_writable(self) -> None:
        if not self.coordinator.calendar.writable:
            raise ServiceValidationError(
                f"Calendar '{self.coordinator.calendar.summary}' is read-only"
            )

    async def async_create_event(self, **kwargs: Any) -> None:
        """Create a new event in Google Calendar."""
        self._ensure_writable()
        body = build_google_body(kwargs, self._time_zone)
        if rrule := kwargs.get(EVENT_RRULE):
            body["recurrence"] = [f"{RRULE_PREFIX}{rrule}"]
        with self._api_errors("create the event"):
            await self._api.async_insert_event(self._calendar_id, body)
        await self.coordinator.async_refresh()

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Update an event (called by the Home Assistant calendar UI/API).

        Home Assistant passes the complete event, so a missing rrule means
        "not recurring".
        """
        self._ensure_writable()
        body = build_google_body(event, self._time_zone, for_patch=True)
        await self._async_apply_update(
            uid,
            body,
            event.get(EVENT_RRULE) or "",
            recurrence_id,
            recurrence_range,
        )

    async def async_update_event_service(self, **data: Any) -> None:
        """Service: partially update an event (only given fields change)."""
        self._ensure_writable()
        ha_event: dict[str, Any] = {
            key: data[key]
            for key in (ATTR_SUMMARY, ATTR_DESCRIPTION, ATTR_LOCATION)
            if key in data
        }
        start: date | datetime | None = None
        end: date | datetime | None = None
        date_keys = {ATTR_START_DATE, ATTR_END_DATE} & data.keys()
        datetime_keys = {ATTR_START_DATE_TIME, ATTR_END_DATE_TIME} & data.keys()
        if (
            (date_keys and datetime_keys)
            or len(date_keys) == 1
            or len(datetime_keys) == 1
        ):
            raise ServiceValidationError(
                "Start and end must both be given, either as start_date/end_date "
                "or as start_date_time/end_date_time"
            )
        if date_keys:
            start, end = data[ATTR_START_DATE], data[ATTR_END_DATE]
        elif datetime_keys:
            start = dt_util.as_local(data[ATTR_START_DATE_TIME])
            end = dt_util.as_local(data[ATTR_END_DATE_TIME])
        if start is not None and end is not None:
            if end < start:
                raise ServiceValidationError("The end must not be before the start")
            if start == end and not isinstance(start, datetime):
                end = start + timedelta(days=1)
            ha_event["dtstart"] = start
            ha_event["dtend"] = end

        body = build_google_body(ha_event, self._time_zone, for_patch=True)
        rrule: str | None = data.get(ATTR_RRULE)
        if not body and rrule is None:
            raise ServiceValidationError("Nothing to update")
        await self._async_apply_update(
            data[ATTR_UID],
            body,
            rrule,
            data.get(ATTR_RECURRENCE_ID) or None,
            data.get(ATTR_RECURRENCE_RANGE) or None,
        )

    async def async_delete_event_service(self, **data: Any) -> None:
        """Service: delete an event."""
        await self.async_delete_event(
            data[ATTR_UID],
            recurrence_id=data.get(ATTR_RECURRENCE_ID) or None,
            recurrence_range=data.get(ATTR_RECURRENCE_RANGE) or None,
        )

    async def _async_apply_update(
        self,
        uid: str,
        body: dict[str, Any],
        rrule: str | None,
        recurrence_id: str | None,
        recurrence_range: str | None,
    ) -> None:
        """Apply an update.

        rrule: None = keep the current recurrence, "" = not recurring,
        otherwise the new rule.
        """
        with self._api_errors("update the event"):
            if not recurrence_id:
                await self._async_update_series_or_single(uid, body, rrule)
            elif recurrence_range == RANGE_THIS_AND_FUTURE:
                await self._async_update_this_and_future(
                    uid, recurrence_id, body, rrule
                )
            else:
                # Only this occurrence; an instance cannot carry a recurrence
                await self._async_patch_instance(recurrence_id, body)
        self._series_rrules.pop(uid, None)
        await self.coordinator.async_refresh()

    async def _async_patch_instance(
        self, recurrence_id: str, body: dict[str, Any]
    ) -> None:
        if body:
            await self._api.async_patch_event(self._calendar_id, recurrence_id, body)

    async def _async_update_series_or_single(
        self, uid: str, body: dict[str, Any], rrule: str | None
    ) -> None:
        """Update a single event or a complete series."""
        if rrule is not None:
            current = await self._api.async_get_event(self._calendar_id, uid)
            current_recurrence: list[str] = current.get("recurrence") or []
            new_recurrence = replace_rrule(current_recurrence, rrule)
            if new_recurrence != current_recurrence:
                body["recurrence"] = new_recurrence
                if new_recurrence:
                    self._ensure_time_zones(body, current)
        if body:
            await self._api.async_patch_event(self._calendar_id, uid, body)

    def _ensure_time_zones(self, body: dict[str, Any], current: dict[str, Any]) -> None:
        """Recurring timed events need an explicit time zone in start/end."""
        for key in ("start", "end"):
            if key in body:
                continue
            value = current.get(key) or {}
            if (
                value.get("dateTime")
                and not value.get("timeZone")
                and (parsed := parse_google_time(value)) is not None
            ):
                body[key] = build_google_time(parsed, self._time_zone, for_patch=True)

    async def _async_load_series_and_instance(
        self, uid: str, recurrence_id: str
    ) -> tuple[dict[str, Any], date | datetime, bool]:
        """Return (series, original start of instance, is first occurrence)."""
        series, instance = await asyncio.gather(
            self._api.async_get_event(self._calendar_id, uid),
            self._api.async_get_event(self._calendar_id, recurrence_id),
        )
        original = parse_google_time(
            instance.get("originalStartTime") or instance.get("start")
        )
        series_start = parse_google_time(series.get("start"))
        if original is None or series_start is None:
            raise HomeAssistantError("Could not determine the start of the series")
        is_first = _as_local_datetime(original) <= _as_local_datetime(series_start)
        return {**series, "_instance": instance}, original, is_first

    async def _async_update_this_and_future(
        self,
        uid: str,
        recurrence_id: str,
        body: dict[str, Any],
        rrule: str | None,
    ) -> None:
        """Change this and all following occurrences of a series."""
        series, original, is_first = await self._async_load_series_and_instance(
            uid, recurrence_id
        )
        instance: dict[str, Any] = series.pop("_instance")
        series_recurrence: list[str] = series.get("recurrence") or []

        if is_first:
            # The whole series is affected
            await self._async_update_series_or_single(uid, body, rrule)
            return

        if rrule is None:
            rrule = strip_rrule_end(extract_rrule(series_recurrence) or "")

        new_body: dict[str, Any] = series_copy_body(series)
        for key in ("summary", "description", "location", "start", "end"):
            if key in instance:
                new_body[key] = instance[key]
        new_body.update(body)
        for key in ("start", "end"):
            # Remove the explicit "null" fields used for PATCH requests
            new_body[key] = {
                k: v for k, v in (new_body.get(key) or {}).items() if v is not None
            }
            if new_body[key].get("dateTime") and not new_body[key].get("timeZone"):
                new_body[key]["timeZone"] = self._time_zone
        if rrule:
            new_body["recurrence"] = [f"{RRULE_PREFIX}{rrule}"]

        # Create the new series first so that nothing is lost on errors
        created = await self._api.async_insert_event(self._calendar_id, new_body)
        try:
            await self._api.async_patch_event(
                self._calendar_id,
                uid,
                {"recurrence": truncate_recurrence(series_recurrence, original)},
            )
        except GoogleCalendarApiError:
            _LOGGER.warning("Shortening series %s failed, rolling back", uid)
            try:
                await self._api.async_delete_event(self._calendar_id, created["id"])
            except GoogleCalendarApiError as err:
                _LOGGER.error("Rollback of new series failed: %s", err)
            raise

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event, an occurrence or a part of a series."""
        self._ensure_writable()
        with self._api_errors("delete the event"):
            if not recurrence_id:
                await self._api.async_delete_event(self._calendar_id, uid)
            elif recurrence_range == RANGE_THIS_AND_FUTURE:
                series, original, is_first = await self._async_load_series_and_instance(
                    uid, recurrence_id
                )
                if is_first:
                    await self._api.async_delete_event(self._calendar_id, uid)
                else:
                    await self._api.async_patch_event(
                        self._calendar_id,
                        uid,
                        {
                            "recurrence": truncate_recurrence(
                                series.get("recurrence") or [], original
                            )
                        },
                    )
            else:
                await self._api.async_delete_event(self._calendar_id, recurrence_id)
        self._series_rrules.pop(uid, None)
        await self.coordinator.async_refresh()
