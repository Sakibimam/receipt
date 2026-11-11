"""Canonical JSON and the append-only, hash-chained event log."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

GENESIS_HASH = "0" * 64


def canonical(obj: Any) -> str:
    """Deterministic JSON used for every hash and signature."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event_body(event: dict[str, Any]) -> dict[str, Any]:
    """The hashed part of an event: everything except prev_hash and hash."""
    return {k: v for k, v in event.items() if k not in ("prev_hash", "hash")}


def compute_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return sha256_hex(prev_hash + canonical(body))


class Chain:
    """Append-only list of events where each event commits to the previous one."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    @property
    def head(self) -> str:
        return self.events[-1]["hash"] if self.events else GENESIS_HASH

    def append(self, type_: str, data: dict[str, Any], ts: str | None = None) -> dict[str, Any]:
        body = {"index": len(self.events), "ts": ts or now_iso(), "type": type_, "data": data}
        # Round-trip through canonical JSON so stored data is exactly what was hashed.
        body = json.loads(canonical(body))
        prev = self.head
        event = {**body, "prev_hash": prev, "hash": compute_hash(prev, body)}
        self.events.append(event)
        return event


def verify_chain(events: list[dict[str, Any]]) -> list[int]:
    """Return indexes of events that break the chain (empty list = intact)."""
    bad: list[int] = []
    prev = GENESIS_HASH
    for pos, event in enumerate(events):
        body = event_body(event)
        ok = (
            event.get("index") == pos
            and event.get("prev_hash") == prev
            and event.get("hash") == compute_hash(prev, body)
        )
        if not ok:
            bad.append(pos)
        prev = event.get("hash", "")
    return bad


def root_hash(events: list[dict[str, Any]]) -> str:
    return events[-1]["hash"] if events else GENESIS_HASH
