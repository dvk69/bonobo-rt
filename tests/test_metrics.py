"""Tests for GraphExecutionContext.get_metrics()."""

import pytest
from unittest.mock import patch

import bonobo
from bonobo.execution.contexts.graph import GraphExecutionContext
from bonobo.structs.graphs import Graph
from bonobo.util.testing import BufferingGraphExecutionContext


# ---------------------------------------------------------------------------
# Unit tests — get_metrics() on a BufferingGraphExecutionContext
# ---------------------------------------------------------------------------


def _make_ctx(*nodes):
    """Build a simple graph context from *nodes* and return it pre-started."""
    g = Graph(*nodes)
    return BufferingGraphExecutionContext(g)


def test_get_metrics_returns_dict():
    """get_metrics() returns a dict."""
    def extract():
        yield ("hello",)
        yield ("world",)

    ctx = _make_ctx(extract)
    assert isinstance(ctx.get_metrics(), dict)


def test_get_metrics_keys_are_node_names():
    """Keys are the wrapped callable's __name__."""
    def my_node():
        pass

    ctx = _make_ctx(my_node)
    metrics = ctx.get_metrics()
    assert "my_node" in metrics


def test_get_metrics_has_required_counter_keys():
    """Each node entry has 'in', 'out', 'err', 'warn' counters."""
    def fn():
        pass

    ctx = _make_ctx(fn)
    metrics = ctx.get_metrics()
    node_metrics = metrics["fn"]
    for key in ("in", "out", "err", "warn"):
        assert key in node_metrics, f"missing key {key!r}"


def test_get_metrics_counts_zero_before_execution():
    """All counters are zero before any execution."""
    def fn():
        pass

    ctx = _make_ctx(fn)
    metrics = ctx.get_metrics()
    assert all(v == 0 for v in metrics["fn"].values())


def test_get_metrics_deduplicates_same_named_nodes():
    """Two nodes with the same __name__ get deduplicated keys."""
    # Use lambdas — they all have __name__ == '<lambda>'
    a = lambda x: x
    b = lambda x: x

    g = Graph()
    g.add_chain(a)
    g.add_chain(b, _input=None)
    ctx = BufferingGraphExecutionContext(g)
    metrics = ctx.get_metrics()

    # Both should appear, not overwriting each other
    assert len(metrics) == 2
    keys = list(metrics.keys())
    assert keys[0] != keys[1]


# ---------------------------------------------------------------------------
# Integration test — counters reflect actual execution
# ---------------------------------------------------------------------------


@pytest.mark.timeout(2)
def test_get_metrics_after_graph_run():
    """After bonobo.run(), 'out' for the source node equals its yield count."""
    results = []

    def extract():
        yield ("a",)
        yield ("b",)
        yield ("c",)

    def collect(*args):
        results.append(args)

    with patch("bonobo._api._is_interactive_console", return_value=False):
        ctx = bonobo.run(Graph(extract, collect))

    metrics = ctx.get_metrics()
    assert isinstance(metrics, dict)

    # extract yields 3 tuples → out=3
    assert metrics["extract"]["out"] == 3
    # collect receives 3 → in=3
    assert metrics["collect"]["in"] == 3


@pytest.mark.timeout(2)
def test_get_metrics_returns_snapshot():
    """get_metrics() returns a fresh copy each call (not a live view)."""
    def fn():
        pass

    ctx = _make_ctx(fn)
    m1 = ctx.get_metrics()
    m2 = ctx.get_metrics()

    # Both are equal (same zero values) but different objects
    assert m1 == m2
    assert m1 is not m2
    assert m1["fn"] is not m2["fn"]
