# -*- coding: utf-8 -*-
"""Aru Lite Context: a tiny, evidence-aware ledger for facts that are true *now*.

This module complements long-term memory; it does not replace it. It stores only:
- today: facts that expire at local midnight
- current: temporary cross-day context with an explicit review/expiry time

Every item has a lifecycle state. Plans never silently become completed facts, and
removed/expired items leave tombstones so old chat retrieval cannot revive them.
Standard library only; one JSON file; atomic writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional

PATH = os.environ.get("ARU_LITE_CONTEXT_PATH", "aru_lite_context.json")
TZ_NAME = os.environ.get("ARU_LITE_TIMEZONE", "Asia/Shanghai")
MAX_ACTIVE = int(os.environ.get("ARU_LITE_MAX_ACTIVE", "40"))
MAX_TOMBSTONES = int(os.environ.get("ARU_LITE_MAX_TOMBSTONES", "100"))

SCOPES = {"today", "current"}
STATES = {"planned", "in_progress", "completed", "cancelled", "unknown"}
TERMINAL_STATES = {"completed", "cancelled"}
_LOCK = threading.RLock()


def _tz() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TZ_NAME)
    except Exception:
        return dt.timezone(dt.timedelta(hours=8))


def now() -> dt.datetime:
    return dt.datetime.now(_tz())


def _iso(value: dt.datetime) -> str:
    return value.astimezone(_tz()).isoformat(timespec="seconds")


def _parse(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_tz())
    return parsed.astimezone(_tz())


def _empty() -> Dict[str, Any]:
    return {"version": 1, "items": [], "tombstones": []}


def _load() -> Dict[str, Any]:
    if not os.path.exists(PATH):
        return _empty()
    try:
        with open(PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("version", 1)
        data.setdefault("items", [])
        data.setdefault("tombstones", [])
        return data
    except (OSError, ValueError, TypeError):
        return _empty()


def _save(data: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(PATH))
    os.makedirs(parent, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, PATH)


def _today_expiry(at: dt.datetime) -> dt.datetime:
    tomorrow = at.date() + dt.timedelta(days=1)
    return dt.datetime.combine(tomorrow, dt.time.min, tzinfo=_tz())


def _clean_text(value: Any, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _tombstone(data: Dict[str, Any], item: Dict[str, Any], reason: str, at: dt.datetime) -> None:
    data["tombstones"].append({
        "key": item.get("key"),
        "last_value": item.get("value"),
        "last_state": item.get("state"),
        "reason": reason,
        "ended_at": _iso(at),
        "source_ref": item.get("source_ref", ""),
    })
    data["tombstones"] = data["tombstones"][-MAX_TOMBSTONES:]


def _sweep(data: Dict[str, Any], at: Optional[dt.datetime] = None) -> int:
    at = at or now()
    keep, expired = [], []
    for item in data.get("items", []):
        expiry = _parse(item.get("expires_at"))
        (expired if expiry and expiry <= at else keep).append(item)
    for item in expired:
        _tombstone(data, item, "expired", at)
    data["items"] = keep
    return len(expired)


def set_item(
    key: str,
    value: str,
    *,
    scope: str = "today",
    state: str = "unknown",
    occurred_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    ttl_hours: Optional[int] = None,
    source_ref: str = "",
    evidence: str = "user_stated",
) -> Dict[str, Any]:
    """Create or replace one active item by key.

    `state` is explicit: planned/in_progress/completed/cancelled/unknown. Callers
    must never infer completed merely because time passed. Terminal states are
    recorded as tombstones and do not remain active.
    """
    key = _clean_text(key, "key", 80)
    value = _clean_text(value, "value", 500)
    if scope not in SCOPES:
        raise ValueError("scope must be today or current")
    if state not in STATES:
        raise ValueError("invalid state")
    at = now()
    if expires_at:
        expiry = _parse(expires_at)
    elif ttl_hours is not None:
        ttl = max(1, min(24 * 365, int(ttl_hours)))
        expiry = at + dt.timedelta(hours=ttl)
    elif scope == "today":
        expiry = _today_expiry(at)
    else:
        raise ValueError("current scope requires expires_at or ttl_hours")
    if not expiry or expiry <= at:
        raise ValueError("expiry must be in the future")

    item = {
        "id": uuid.uuid4().hex,
        "key": key,
        "value": value,
        "scope": scope,
        "state": state,
        "observed_at": _iso(at),
        "occurred_at": _iso(_parse(occurred_at)) if occurred_at else None,
        "expires_at": _iso(expiry),
        "source_ref": str(source_ref or "")[:300],
        "evidence": str(evidence or "user_stated")[:80],
    }
    with _LOCK:
        data = _load()
        _sweep(data, at)
        previous = next((x for x in data["items"] if x.get("key") == key), None)
        data["items"] = [x for x in data["items"] if x.get("key") != key]
        if previous:
            _tombstone(data, previous, "superseded", at)
        if state in TERMINAL_STATES:
            _tombstone(data, item, state, at)
        else:
            data["items"].append(item)
            if len(data["items"]) > MAX_ACTIVE:
                overflow = data["items"][:-MAX_ACTIVE]
                data["items"] = data["items"][-MAX_ACTIVE:]
                for old in overflow:
                    _tombstone(data, old, "capacity", at)
        _save(data)
    return item


def set_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convenience batch API. Each entry uses the same fields as set_item."""
    return [set_item(**entry) for entry in items]


def get_active(*, scope: Optional[str] = None) -> List[Dict[str, Any]]:
    if scope is not None and scope not in SCOPES:
        raise ValueError("scope must be today or current")
    with _LOCK:
        data = _load()
        changed = bool(_sweep(data))
        if changed:
            _save(data)
        items = data["items"]
        if scope:
            items = [x for x in items if x.get("scope") == scope]
        return [dict(x) for x in items]


def drop_item(key: str, *, reason: str = "ended") -> int:
    key = _clean_text(key, "key", 80)
    at = now()
    with _LOCK:
        data = _load()
        _sweep(data, at)
        gone = [x for x in data["items"] if x.get("key") == key]
        data["items"] = [x for x in data["items"] if x.get("key") != key]
        for item in gone:
            _tombstone(data, item, str(reason or "ended")[:120], at)
        if gone:
            _save(data)
        return len(gone)


def get_tombstones(*, key: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    with _LOCK:
        data = _load()
        rows = data.get("tombstones", [])
        if key:
            rows = [x for x in rows if x.get("key") == key]
        return [dict(x) for x in rows[-max(1, min(100, int(limit))):]]


def render_context() -> str:
    """Compact model-facing block. It is background, not a topic suggestion."""
    items = get_active()
    if not items:
        return ""
    lines = [
        '<current_state note="temporary facts only; plans are not completed facts">'
    ]
    for item in items:
        lines.append(
            '  <item key="{key}" scope="{scope}" state="{state}" observed_at="{observed}" expires_at="{expires}">{value}</item>'.format(
                key=item["key"].replace('"', "'"),
                scope=item["scope"],
                state=item["state"],
                observed=item["observed_at"],
                expires=item["expires_at"],
                value=item["value"].replace("<", "&lt;").replace(">", "&gt;"),
            )
        )
    lines.append("</current_state>")
    return "\n".join(lines)
