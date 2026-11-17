"""One-way mirroring of a calendar into a Google calendar (pure logic)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any

from homeassistant.components.calendar import CalendarEvent
from homeassistant.exceptions import ServiceValidationError

from .const import PROP_HASH, PROP_KEY, PROP_SOURCE
from .convert import build_google_body


@dataclass(frozen=True, slots=True)
class SyncOptions:
    """Options controlling what is mirrored."""

    include_description: bool = True
    include_location: bool = True
    include_all_day: bool = True
    include_regex: re.Pattern[str] | None = None
    exclude_regex: re.Pattern[str] | None = None


@dataclass(slots=True)
class SyncPlan:
    """Operations required to bring the target in line with the source."""

    # (summary, insert body)
    create: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # (summary, target event id, patch body)
    update: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    # (summary, target event id)
    delete: list[tuple[str, str]] = field(default_factory=list)
    unchanged: int = 0


def compile_regex(value: str | None, field_name: str) -> re.Pattern[str] | None:
    """Compile a user supplied regular expression (case-insensitive)."""
    if not value:
        return None
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as err:
        raise ServiceValidationError(
            f"Invalid regular expression in {field_name}: {err}"
        ) from err


def event_is_selected(event: CalendarEvent, options: SyncOptions) -> bool:
    """Return True if the source event should be mirrored."""
    if event.all_day and not options.include_all_day:
        return False
    title = event.summary or ""
    if options.exclude_regex is not None and options.exclude_regex.search(title):
        return False
    return options.include_regex is None or bool(options.include_regex.search(title))


def _digest(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()


def assign_keys(events: list[CalendarEvent]) -> dict[str, CalendarEvent]:
    """Return a stable key for every source event.

    The key is based on uid (+ recurrence_id) so that a moved event is updated
    instead of deleted and recreated. If a calendar returns several events with
    the same uid (expanded series without recurrence_id) the start is added.
    Events without uid are identified by title and start.
    """
    base: list[tuple[str, CalendarEvent]] = []
    for event in events:
        if event.uid:
            base.append((f"uid|{event.uid}|{event.recurrence_id or ''}", event))
        else:
            base.append((f"nouid|{event.summary}|{event.start.isoformat()}", event))

    counts: dict[str, int] = defaultdict(int)
    for key, _ in base:
        counts[key] += 1

    result: dict[str, CalendarEvent] = {}
    for key, event in base:
        if counts[key] > 1:
            key = f"{key}|{event.start.isoformat()}"  # noqa: PLW2901
        # Identical duplicates (same key, same start) collapse into one mirror
        result.setdefault(_digest(key), event)
    return result


def _project(event: CalendarEvent, options: SyncOptions) -> dict[str, Any]:
    """Return the Home Assistant style data of the mirror."""
    return {
        "summary": event.summary or "",
        # A disabled field is written as empty string, so the value is also
        # removed from mirrors that were created with the field enabled.
        "description": (event.description or "") if options.include_description else "",
        "location": (event.location or "") if options.include_location else "",
        "dtstart": event.start,
        "dtend": event.end,
    }


def plan_sync(
    source_events: list[CalendarEvent],
    target_items: list[dict[str, Any]],
    source_id: str,
    options: SyncOptions,
    time_zone: str,
) -> SyncPlan:
    """Compare source events and existing mirrors and return the operations."""
    plan = SyncPlan()
    wanted = assign_keys([e for e in source_events if event_is_selected(e, options)])

    existing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in target_items:
        private = (item.get("extendedProperties") or {}).get("private") or {}
        if private.get(PROP_SOURCE) != source_id:
            # Not created by this sync relation - never touch it
            continue
        existing[private.get(PROP_KEY, "")].append(item)

    for key, event in wanted.items():
        data = _project(event, options)
        insert_body = build_google_body(data, time_zone)
        content_hash = hashlib.sha1(
            json.dumps(insert_body, sort_keys=True).encode()
        ).hexdigest()
        properties = {
            "private": {PROP_SOURCE: source_id, PROP_KEY: key, PROP_HASH: content_hash}
        }
        mirrors = existing.pop(key, [])
        if not mirrors:
            plan.create.append(
                (
                    data["summary"],
                    {
                        **insert_body,
                        "reminders": {"useDefault": False, "overrides": []},
                        "extendedProperties": properties,
                    },
                )
            )
            continue

        current, *duplicates = mirrors
        plan.delete.extend((dup.get("summary", ""), dup["id"]) for dup in duplicates)
        current_hash = (
            (current.get("extendedProperties") or {}).get("private") or {}
        ).get(PROP_HASH)
        if current_hash == content_hash:
            plan.unchanged += 1
            continue
        plan.update.append(
            (
                data["summary"],
                current["id"],
                {
                    **build_google_body(data, time_zone, for_patch=True),
                    "reminders": {"useDefault": False, "overrides": []},
                    "extendedProperties": properties,
                },
            )
        )

    # Mirrors whose source event no longer exists or is no longer selected
    for items in existing.values():
        plan.delete.extend((item.get("summary", ""), item["id"]) for item in items)
    return plan
