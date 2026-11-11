"""Receipt verifier: signature, chain integrity, root hash, event count."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from receipt.chain import root_hash, verify_chain
from receipt.session import signing_payload
from receipt.sign import verify_signature


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    events: list[int] = field(default_factory=list)


@dataclass
class Report:
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failing_events(self) -> list[int]:
        return sorted({i for c in self.checks if not c.ok for i in c.events})

    def render(self) -> str:
        lines = [f"RECEIPT {'PASS' if self.ok else 'FAIL'}"]
        for c in self.checks:
            mark = "PASS" if c.ok else "FAIL"
            extra = f" — {c.detail}" if c.detail else ""
            evs = f" (events: {', '.join(map(str, c.events))})" if c.events else ""
            lines.append(f"  [{mark}] {c.name}{extra}{evs}")
        if not self.ok and self.failing_events:
            lines.append(f"  failing event indexes: {self.failing_events}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verdict": "PASS" if self.ok else "FAIL",
            "failing_events": self.failing_events,
            "checks": [c.__dict__ for c in self.checks],
        }


def verify_receipt(receipt: dict[str, Any], expected_key: str | None = None) -> Report:
    checks: list[Check] = []
    events: list[dict[str, Any]] = receipt.get("events", [])
    pub = receipt.get("signer_public_key", "")

    if expected_key is not None and pub != expected_key:
        checks.append(Check("signer key", False, "receipt not signed by the expected key"))
    sig_ok = verify_signature(pub, signing_payload(receipt), receipt.get("signature", ""))
    checks.append(Check("signature", sig_ok, "" if sig_ok else "Ed25519 signature invalid"))

    broken = verify_chain(events)
    checks.append(Check("hash chain", not broken, "" if not broken else "chain broken", broken))

    root_ok = receipt.get("events_root_hash") == root_hash(events)
    checks.append(Check("root hash", root_ok, "" if root_ok else "root hash mismatch"))

    count_ok = receipt.get("event_count") == len(events)
    checks.append(Check("event count", count_ok, "" if count_ok else "event count mismatch"))
    return Report(checks)
