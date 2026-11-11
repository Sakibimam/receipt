"""Receipt verifier: integrity (signature, chain, totals) and compliance (mandate)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from receipt.chain import canonical, root_hash, verify_chain
from receipt.mandate import Mandate
from receipt.model import Receipt, derive
from receipt.session import signing_payload
from receipt.sign import verify_signature

DERIVED_FIELDS = ("totals", "tool_calls", "fallbacks", "violations", "verdict")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    events: list[int] = field(default_factory=list)


@dataclass
class Report:
    checks: list[Check]
    violations: list[dict[str, Any]] = field(default_factory=list)

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
        for v in self.violations:
            lines.append(f"    ! event {v['event_index']}: {v['rule']} — {v['detail']}")
        if not self.ok and self.failing_events:
            lines.append(f"  failing event indexes: {self.failing_events}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verdict": "PASS" if self.ok else "FAIL",
            "failing_events": self.failing_events,
            "violations": self.violations,
            "checks": [c.__dict__ for c in self.checks],
        }


def verify_receipt(
    receipt: dict[str, Any], expected_key: str | None = None, witness: bool = False
) -> Report:
    checks: list[Check] = []
    try:
        Receipt.model_validate(receipt)
        checks.append(Check("schema", True))
    except ValidationError as exc:
        checks.append(Check("schema", False, f"{exc.error_count()} schema error(s)"))
        return Report(checks)

    events: list[dict[str, Any]] = receipt["events"]
    pub = receipt["signer_public_key"]

    if expected_key is not None:
        same = pub == expected_key
        checks.append(Check("signer key", same, "" if same else "not the expected signer"))
    sig_ok = verify_signature(pub, signing_payload(receipt), receipt["signature"])
    checks.append(Check("signature", sig_ok, "" if sig_ok else "Ed25519 signature invalid"))

    broken = verify_chain(events)
    checks.append(Check("hash chain", not broken, "" if not broken else "chain broken", broken))

    root_ok = receipt["events_root_hash"] == root_hash(events)
    checks.append(Check("root hash", root_ok, "" if root_ok else "root hash mismatch"))

    count_ok = receipt["event_count"] == len(events)
    checks.append(Check("event count", count_ok, "" if count_ok else "event count mismatch"))

    mandate = Mandate.model_validate(receipt["mandate"])
    m_ok = mandate.digest() == receipt["mandate_hash"]
    checks.append(Check("mandate hash", m_ok, "" if m_ok else "embedded mandate was altered"))

    derived = derive(events, mandate)
    bad_fields = [f for f in DERIVED_FIELDS if canonical(derived[f]) != canonical(receipt[f])]
    checks.append(
        Check(
            "recomputed totals",
            not bad_fields,
            "" if not bad_fields else "differs: " + ", ".join(bad_fields),
        )
    )

    violations = derived["violations"]
    idx = sorted({v["event_index"] for v in violations})
    checks.append(
        Check(
            "within mandate",
            not violations,
            f"mandate '{mandate.name}'" if not violations else f"{len(violations)} violation(s)",
            idx,
        )
    )
    if witness:
        from receipt.witness import witness_events

        rows = witness_events(events)
        bad = [r["event_index"] for r in rows if r["status"] != "matched"]
        live = len(rows)
        detail = f"{live - len(bad)}/{live} calls match Otari's ledger" if live else "no live calls"
        checks.append(Check("otari ledger witness", not bad, detail, bad))
    return Report(checks, violations)
