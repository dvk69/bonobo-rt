"""Tests for the DataQualityCheck violations merge in GraphExecutionContext.get_metrics()."""

import warnings

import pytest
from unittest.mock import patch

import bonobo
from bonobo.nodes.quality import DataQualityCheck
from bonobo.structs.graphs import Graph
from bonobo.util.testing import BufferingGraphExecutionContext


def _make_ctx(*nodes):
    g = Graph(*nodes)
    return BufferingGraphExecutionContext(g)


# ---------------------------------------------------------------------------
# Non-DQC nodes should NOT have a "violations" key
# ---------------------------------------------------------------------------


def test_get_metrics_no_violations_for_plain_node():
    """Plain nodes do not get a 'violations' key in their metrics."""
    def fn():
        pass

    ctx = _make_ctx(fn)
    metrics = ctx.get_metrics()
    assert "violations" not in metrics["fn"]


# ---------------------------------------------------------------------------
# DQC node should have "violations" key (empty when no violations occurred)
# ---------------------------------------------------------------------------


def test_get_metrics_violations_key_present_for_dqc():
    """DataQualityCheck nodes get a 'violations' key in their metrics."""
    checker = DataQualityCheck()
    ctx = _make_ctx(checker)
    metrics = ctx.get_metrics()
    assert "DataQualityCheck" in metrics
    assert "violations" in metrics["DataQualityCheck"]
    assert isinstance(metrics["DataQualityCheck"]["violations"], dict)


def test_get_metrics_violations_empty_when_no_violations():
    """violations dict is empty when no rules have been broken."""
    checker = DataQualityCheck()
    ctx = _make_ctx(checker)
    metrics = ctx.get_metrics()
    assert metrics["DataQualityCheck"]["violations"] == {}


# ---------------------------------------------------------------------------
# violations dict reflects actual violation counts
# ---------------------------------------------------------------------------


def test_get_metrics_violations_reflect_actual_counts():
    """violations dict mirrors DataQualityCheck.get_violation_counts()."""
    import collections

    checker = DataQualityCheck()
    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        checker(window, None)
        checker(window, None)
        checker(window, "")

    ctx = _make_ctx(checker)
    metrics = ctx.get_metrics()
    v = metrics["DataQualityCheck"]["violations"]
    # null_empty[0] should be 3 (two None + one empty string)
    assert v.get("null_empty[0]", 0) == 3


# ---------------------------------------------------------------------------
# violations is a snapshot (copy), not a live reference
# ---------------------------------------------------------------------------


def test_get_metrics_violations_is_snapshot():
    """Mutating the returned violations dict does not affect the node."""
    import collections

    checker = DataQualityCheck()
    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        checker(window, None)

    ctx = _make_ctx(checker)
    m1 = ctx.get_metrics()
    m1["DataQualityCheck"]["violations"]["null_empty[0]"] = 9999

    m2 = ctx.get_metrics()
    assert m2["DataQualityCheck"]["violations"].get("null_empty[0]") == 1


# ---------------------------------------------------------------------------
# Integration — violations survive a real bonobo.run()
# ---------------------------------------------------------------------------


@pytest.mark.timeout(2)
def test_violations_in_metrics_after_run():
    """After bonobo.run(), violations are visible in get_metrics()."""
    checker = DataQualityCheck()

    def extract():
        yield (None,)        # triggers null_empty[0]
        yield ("hello",)     # clean

    with patch("bonobo._api._is_interactive_console", return_value=False):
        ctx = bonobo.run(Graph(extract, checker))

    metrics = ctx.get_metrics()
    assert "DataQualityCheck" in metrics
    v = metrics["DataQualityCheck"]["violations"]
    assert v.get("null_empty[0]", 0) == 1
