from receipt.client import OtariClient, parse_cost, pick_headers, summarize_tool_calls
from receipt.session import Session


def test_parse_cost_handles_string_and_missing() -> None:
    assert parse_cost("0.000123") == 0.000123
    assert parse_cost(None) == 0.0
    assert parse_cost("n/a") == 0.0


def test_pick_headers_drops_auth() -> None:
    h = {"Otari-Model": "x", "Authorization": "Bearer secret", "Otari-Fallback": "true"}
    assert pick_headers(h) == {"Otari-Model": "x", "Otari-Fallback": "true"}


def test_tool_call_sources_kept() -> None:
    calls = [
        {
            "id": "otari_ws_1",
            "type": "web_search",
            "status": "completed",
            "query": "q",
            "sources": [{"url": "https://a", "title": "A", "published_date": None}],
        }
    ]
    out = summarize_tool_calls(calls)
    assert out[0]["sources"] == [{"url": "https://a", "title": "A"}]


def test_mock_client_records_event() -> None:
    s = Session(agent="t")
    c = OtariClient(s, force_mock=True)
    r = c.chat("mock/m", [{"role": "user", "content": "hi"}], role="researcher")
    assert r.ok and c.mock
    assert s.chain.events[0]["type"] == "llm_call"
    assert s.chain.events[0]["data"]["mock"] is True


def test_timeout_is_chained_not_raised() -> None:
    """Regression: a live APITimeoutError crashed the demo instead of being recorded."""
    import httpx
    from openai import APITimeoutError

    s = Session(agent="t")
    c = OtariClient(s, api_key="test-key-not-real", base_url="http://127.0.0.1:9")

    class Boom:
        def create(self, **_: object) -> None:
            raise APITimeoutError(request=httpx.Request("POST", "http://x"))

    c._sdk.chat.completions.with_raw_response = Boom()  # type: ignore[union-attr]
    r = c.chat("m", [{"role": "user", "content": "x"}])
    assert not r.ok and r.error and r.error["code"] == "timeout"
    assert s.chain.events[-1]["type"] == "llm_error"
