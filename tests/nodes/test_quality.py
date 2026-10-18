"""Tests for bonobo.nodes.quality — DataQualityCheck."""

import threading
import warnings

import pytest

from bonobo.nodes.quality import DataQualityCheck
from bonobo.constants import NOT_MODIFIED
from bonobo.util.testing import BufferingNodeExecutionContext


# ---------------------------------------------------------------------------
# Configuration / options
# ---------------------------------------------------------------------------


def test_data_quality_check_defaults():
    """Default options are applied correctly."""
    node = DataQualityCheck()
    assert node.window_size == 1000
    assert node.field_types is None
    assert node.value_ranges is None


def test_data_quality_check_custom_options():
    """Custom options override defaults."""
    node = DataQualityCheck(
        window_size=50,
        field_types={0: int},
        value_ranges={0: (0, 100)},
    )
    assert node.window_size == 50
    assert node.field_types == {0: int}
    assert node.value_ranges == {0: (0, 100)}


# ---------------------------------------------------------------------------
# Pass-through behaviour
# ---------------------------------------------------------------------------


def test_data_quality_check_passes_through_clean_tuple():
    """Clean tuples return NOT_MODIFIED."""
    node = DataQualityCheck()
    with BufferingNodeExecutionContext(node) as ctx:
        ctx.write_sync("hello", "world")
    # Buffer should be empty because NOT_MODIFIED passes the input through
    # in the execution context (nothing new is generated).
    assert ctx.started and ctx.stopped


def test_data_quality_check_returns_not_modified():
    """__call__ always returns NOT_MODIFIED."""
    node = DataQualityCheck()
    from bonobo.util.objects import ValueHolder
    import collections

    window = collections.deque(maxlen=1000)
    result = node(window, "a", "b")
    assert result is NOT_MODIFIED


# ---------------------------------------------------------------------------
# Null / empty checks
# ---------------------------------------------------------------------------


def test_null_value_triggers_warning():
    """None value in any field raises a UserWarning."""
    node = DataQualityCheck()
    from bonobo.util.objects import ValueHolder
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, None, "ok")

    assert len(w) >= 1
    assert any("null or empty" in str(warning.message) for warning in w)


def test_empty_string_triggers_warning():
    """Empty string triggers a UserWarning."""
    node = DataQualityCheck()
    from bonobo.util.objects import ValueHolder
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, "")

    assert len(w) >= 1
    assert any("null or empty" in str(warning.message) for warning in w)


def test_null_increments_violation_counter():
    """Null value increments the violation counter."""
    node = DataQualityCheck()
    from bonobo.util.objects import ValueHolder
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        node(window, None)
        node(window, None)

    counts = node.get_violation_counts()
    assert counts.get("null_empty[0]", 0) == 2


def test_no_warning_for_clean_tuple():
    """No warning is emitted for a clean tuple."""
    node = DataQualityCheck()
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, "hello", 42, True)

    assert len(w) == 0


# ---------------------------------------------------------------------------
# Type conformance checks
# ---------------------------------------------------------------------------


def test_type_violation_triggers_warning():
    """Wrong type raises a UserWarning."""
    node = DataQualityCheck(field_types={0: int})
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, "not_an_int")

    type_warnings = [x for x in w if "expected int" in str(x.message)]
    assert len(type_warnings) >= 1


def test_type_violation_increments_counter():
    """Type violation increments the counter."""
    node = DataQualityCheck(field_types={0: int})
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        node(window, "bad")
        node(window, 42)   # this one is fine

    counts = node.get_violation_counts()
    assert counts.get("type[0]", 0) == 1


def test_type_check_skips_none_values():
    """None values are not type-checked (null check fires instead)."""
    node = DataQualityCheck(field_types={0: int})
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, None)

    # Should get null_empty warning, NOT a type warning
    type_warnings = [x for x in w if "expected int" in str(x.message)]
    null_warnings = [x for x in w if "null or empty" in str(x.message)]
    assert len(type_warnings) == 0
    assert len(null_warnings) >= 1


# ---------------------------------------------------------------------------
# Value range checks
# ---------------------------------------------------------------------------


def test_range_violation_triggers_warning():
    """Out-of-range value raises a UserWarning."""
    node = DataQualityCheck(value_ranges={0: (0, 10)})
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, 999)

    range_warnings = [x for x in w if "outside" in str(x.message)]
    assert len(range_warnings) >= 1


def test_range_violation_increments_counter():
    """Range violation increments the counter."""
    node = DataQualityCheck(value_ranges={0: (0, 10)})
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        node(window, -1)
        node(window, 5)   # in range — no violation
        node(window, 11)

    counts = node.get_violation_counts()
    assert counts.get("range[0]", 0) == 2


def test_range_check_skips_none():
    """None values are not range-checked."""
    node = DataQualityCheck(value_ranges={0: (0, 10)})
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node(window, None)

    range_warnings = [x for x in w if "outside" in str(x.message)]
    assert len(range_warnings) == 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


@pytest.mark.timeout(5)
def test_violation_counter_thread_safe():
    """Concurrent violation recording does not corrupt the counter."""
    node = DataQualityCheck()
    import collections

    window = collections.deque(maxlen=10000)
    n_threads = 10
    n_per_thread = 100

    def spam():
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            for _ in range(n_per_thread):
                node(window, None)

    threads = [threading.Thread(target=spam) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    counts = node.get_violation_counts()
    assert counts["null_empty[0]"] == n_threads * n_per_thread


# ---------------------------------------------------------------------------
# get_violation_counts returns a copy
# ---------------------------------------------------------------------------


def test_get_violation_counts_returns_copy():
    """Mutating the returned dict does not affect the internal counter."""
    node = DataQualityCheck()
    import collections

    window = collections.deque(maxlen=1000)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        node(window, None)

    snapshot = node.get_violation_counts()
    snapshot["null_empty[0]"] = 9999  # mutate the copy

    assert node.get_violation_counts()["null_empty[0]"] == 1


# ---------------------------------------------------------------------------
# Regression: type+range conflict on the same field must not raise TypeError
# ---------------------------------------------------------------------------


def test_range_check_skips_non_numeric_values():
    """Range check is skipped for non-numeric values (no TypeError raised)."""
    import collections

    node = DataQualityCheck(field_types={1: int}, value_ranges={1: (0, 120)})
    window = collections.deque(maxlen=1000)

    # ("carol", "abc"): field 1 is "abc" — wrong type AND non-numeric.
    # Must not raise, must return NOT_MODIFIED, must count only the type
    # violation (not a range violation).
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = node(window, "carol", "abc")

    from bonobo.constants import NOT_MODIFIED

    assert result is NOT_MODIFIED

    counts = node.get_violation_counts()
    assert counts.get("type[1]", 0) == 1
    assert counts.get("range[1]", 0) == 0
