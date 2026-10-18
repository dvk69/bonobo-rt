"""Tests for bonobo.dashboard FastAPI endpoints."""

import json
from unittest.mock import MagicMock, patch

import pytest

# httpx is required for FastAPI's TestClient; skip gracefully if not installed.
pytest.importorskip("httpx")
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fake metrics payload returned by the mock context.
_FAKE_METRICS = {
    "FileTailReader": {"in": 0, "out": 5, "err": 0, "warn": 0},
    "DataQualityCheck": {
        "in": 5,
        "out": 5,
        "err": 0,
        "warn": 0,
        "violations": {"null_empty[0]": 1},
    },
    "FileAppendWriter": {"in": 5, "out": 0, "err": 0, "warn": 0},
}


def _mock_ctx():
    """Return a mock GraphExecutionContext that returns _FAKE_METRICS."""
    ctx = MagicMock()
    ctx.get_metrics.return_value = _FAKE_METRICS
    return ctx


def _get_client():
    """Return a TestClient wired to the dashboard app with the demo pipeline mocked."""
    from bonobo.dashboard import app as dashboard_module
    from bonobo.dashboard.app import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def test_health_returns_200():
    """/health returns HTTP 200."""
    client = _get_client()
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_ok_json():
    """/health body contains {"status": "ok"}."""
    client = _get_client()
    data = client.get("/health").json()
    assert data == {"status": "ok"}


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------


def test_dashboard_root_returns_200():
    """GET / returns HTTP 200."""
    client = _get_client()
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_root_content_type_is_html():
    """GET / returns text/html."""
    client = _get_client()
    response = client.get("/")
    assert "text/html" in response.headers["content-type"]


def test_dashboard_contains_sse_connect():
    """The dashboard HTML includes the /events EventSource URL."""
    client = _get_client()
    body = client.get("/").text
    assert "/events" in body


def test_dashboard_contains_pipeline_title():
    """The dashboard HTML includes the title text."""
    client = _get_client()
    body = client.get("/").text
    assert "Bonobo" in body


# ---------------------------------------------------------------------------
# SSE /events endpoint — test the generator directly to avoid streaming hang
# ---------------------------------------------------------------------------


def _collect_sse_chunks(n=3):
    """Run the SSE generator and collect *n* chunks synchronously.

    ``asyncio.sleep`` is patched to be instantaneous so tests run in <1 ms.
    """
    import asyncio
    from bonobo.dashboard.app import events

    async def _run():
        response = await events()
        # StreamingResponse.body_iterator is the async generator.
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
            if len(chunks) >= n:
                break
        return chunks

    # Patch asyncio.sleep so the 1-second interval doesn't slow tests.
    async def _instant_sleep(_):
        return

    with patch("bonobo.dashboard.app.asyncio.sleep", side_effect=_instant_sleep):
        return asyncio.run(_run())


def test_events_route_returns_streaming_response():
    """events() returns a StreamingResponse with SSE content type."""
    from fastapi.responses import StreamingResponse

    with patch("bonobo.dashboard.app.get_demo_ctx", return_value=_mock_ctx()):
        from bonobo.dashboard.app import events
        import asyncio

        response = asyncio.run(events())
        assert isinstance(response, StreamingResponse)
        assert "text/event-stream" in response.media_type


def test_events_first_chunk_is_retry_directive():
    """The first SSE chunk is the retry directive."""
    with patch("bonobo.dashboard.app.get_demo_ctx", return_value=_mock_ctx()):
        chunks = _collect_sse_chunks(1)

    assert len(chunks) >= 1
    assert "retry:" in chunks[0]


def test_events_emits_data_with_json():
    """SSE stream emits a data: line containing valid JSON metrics."""
    with patch("bonobo.dashboard.app.get_demo_ctx", return_value=_mock_ctx()):
        chunks = _collect_sse_chunks(3)

    all_text = "".join(chunks)
    data_lines = [ln[len("data:"):].strip() for ln in all_text.splitlines() if ln.startswith("data:")]
    assert len(data_lines) >= 1
    parsed = json.loads(data_lines[0])
    assert isinstance(parsed, dict)
    assert "FileTailReader" in parsed


def test_events_includes_violations_in_metrics():
    """SSE metrics include the 'violations' key for DQC nodes."""
    with patch("bonobo.dashboard.app.get_demo_ctx", return_value=_mock_ctx()):
        chunks = _collect_sse_chunks(3)

    all_text = "".join(chunks)
    data_lines = [ln[len("data:"):].strip() for ln in all_text.splitlines() if ln.startswith("data:")]
    assert len(data_lines) >= 1
    parsed = json.loads(data_lines[0])
    dqc = parsed.get("DataQualityCheck", {})
    assert "violations" in dqc


def test_events_route_media_type_is_sse():
    """The StreamingResponse has text/event-stream media type."""
    import asyncio
    from fastapi.responses import StreamingResponse

    with patch("bonobo.dashboard.app.get_demo_ctx", return_value=_mock_ctx()):
        from bonobo.dashboard.app import events

        response = asyncio.run(events())
        assert "text/event-stream" in response.media_type


# ---------------------------------------------------------------------------
# Public API export
# ---------------------------------------------------------------------------


def test_file_append_writer_in_bonobo_namespace():
    """FileAppendWriter is accessible as bonobo.FileAppendWriter."""
    import bonobo

    assert hasattr(bonobo, "FileAppendWriter")


def test_file_append_writer_in_all():
    """FileAppendWriter appears in bonobo.__all__."""
    import bonobo

    assert "FileAppendWriter" in bonobo.__all__


# ---------------------------------------------------------------------------
# Demo pipeline: _parse_line + checker produces violations on seed data
# ---------------------------------------------------------------------------


def test_demo_pipeline_violations_fire_on_seed_data():
    """Processing the seed lines produces a non-empty violations dict.

    Dirty seed rows:
      - amount=null   → null_empty violation on field 1
      - amount=""     → null_empty violation on field 1
      - amount=-9.99  → range[1] violation (outside (0, 10000))
      - user_id=null  → null_empty violation on field 2
    """
    import collections
    import warnings

    from bonobo.dashboard.app import _SEED_LINES, _parse_line
    from bonobo.nodes.quality import DataQualityCheck
    from bonobo.constants import NOT_MODIFIED

    checker = DataQualityCheck(value_ranges={1: (0, 10000)})
    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        for raw_line in _SEED_LINES:
            for row in _parse_line(raw_line):
                checker(window, *row)

    counts = checker.get_violation_counts()
    assert counts, "expected at least one violation from the seed data"

    # null/empty amount (null and "") → null_empty[1]
    assert counts.get("null_empty[1]", 0) >= 2, f"expected >=2 null_empty[1], got {counts}"
    # null user_id → null_empty[2]
    assert counts.get("null_empty[2]", 0) >= 1, f"expected >=1 null_empty[2], got {counts}"
    # negative amount (-9.99) → range[1]
    assert counts.get("range[1]", 0) >= 1, f"expected >=1 range[1], got {counts}"


def test_parse_line_yields_tuple_from_valid_json():
    """_parse_line yields a 3-tuple (event, amount, user_id) for valid JSON."""
    from bonobo.dashboard.app import _parse_line

    results = list(_parse_line('{"event": "order_created", "amount": 42.5, "user_id": 1001}'))
    assert results == [("order_created", 42.5, 1001)]


def test_parse_line_drops_invalid_json():
    """_parse_line silently drops lines that are not valid JSON."""
    from bonobo.dashboard.app import _parse_line

    assert list(_parse_line("not json at all")) == []
    assert list(_parse_line("")) == []
    assert list(_parse_line("{bad}")) == []


def test_parse_line_handles_null_fields():
    """_parse_line passes None through for null JSON values."""
    from bonobo.dashboard.app import _parse_line

    results = list(_parse_line('{"event": "order_created", "amount": null, "user_id": null}'))
    assert results == [("order_created", None, None)]
