"""MockGateway: an offline stand-in for Otari, clearly labelled as a mock.

Used for the pre-Otari baseline, tests, and when OTARI_API_KEY is absent.
Responses mimic the shape of Otari's OpenAI-compatible API, including
Otari-* headers, but every value is fabricated and marked `mock: true`.
"""

from __future__ import annotations

import uuid
from typing import Any

MOCK_PRICE_PER_1K_TOKENS = 0.0002


class MockGateway:
    name = "mock"

    def chat(self, model: str, messages: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        prompt_tokens = sum(len(str(m.get("content", "")).split()) for m in messages) + 5
        text = f"[mock reply from {model}]"
        completion_tokens = len(text.split())
        total = prompt_tokens + completion_tokens
        return {
            "mock": True,
            "status": 200,
            "headers": {
                "Otari-Model": model,
                "Otari-Fallback": "false",
                "Otari-Attempt-Count": "1",
                "Otari-Request-ID": f"mock-{uuid.uuid4().hex[:12]}",
            },
            "model": model,
            "content": text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
                "cost_usd": round(total / 1000 * MOCK_PRICE_PER_1K_TOKENS, 8),
            },
            "otari_tool_calls": [],
        }
