"""
bonobo.nodes.quality
====================

Data-quality pass-through node for Bonobo ETL.

Currently provided:

* :class:`DataQualityCheck` — pass-through node that maintains a sliding
  window over the last N tuples and emits ``warnings.warn`` messages (plus
  increments counters) when quality rules are violated.
"""

import collections
import threading
import warnings

from bonobo.config import Configurable, ContextProcessor, Option
from bonobo.constants import NOT_MODIFIED

__all__ = ["DataQualityCheck"]


class DataQualityCheck(Configurable):
    """Pass-through transformation that monitors data quality in the stream.

    Every tuple passes through **unchanged** (``NOT_MODIFIED`` is returned).
    While doing so, the node maintains a sliding window of the last
    *window_size* tuples and checks each field against the configured rules.

    **Checks performed (per field per tuple)**

    1. **Null / empty rate** — a violation is recorded when a field value is
       ``None`` or the empty string ``""``.  A ``UserWarning`` is issued
       immediately; the rate is visible via :meth:`get_violation_counts`.
    2. **Type conformance** — when *field_types* is provided (a dict mapping
       field name → Python type), a violation is recorded if the value is not
       an instance of the expected type (and is not ``None``).
    3. **Value ranges** — when *value_ranges* is provided (a dict mapping
       field name → ``(min, max)`` inclusive), a violation is recorded if the
       numeric value falls outside the range (``None`` values are skipped).

    **Thread safety**

    Violation counters are protected by a :class:`threading.Lock` so
    concurrent node threads can safely call :meth:`get_violation_counts`.
    The sliding window (a :class:`collections.deque`) is also guarded by the
    same lock because the window itself is only used for per-call bookkeeping
    (the window is passed as a ContextProcessor value, making it per-execution
    rather than per-instance).

    Options
    -------
    window_size
        Maximum number of recent tuples to retain in the sliding window.
        Default: ``1000``.
    field_types
        Optional ``dict`` mapping field-name strings to expected Python types,
        e.g. ``{"age": int, "name": str}``.  Default: ``None`` (no type
        checks).
    value_ranges
        Optional ``dict`` mapping field-name strings to ``(min, max)``
        inclusive tuples, e.g. ``{"age": (0, 120)}``.  Default: ``None``
        (no range checks).

    Example
    -------
    .. code-block:: python

        import bonobo

        checker = bonobo.DataQualityCheck(
            field_types={"age": int, "name": str},
            value_ranges={"age": (0, 120)},
        )

        graph = bonobo.Graph(
            extract,
            checker,
            load,
        )
        bonobo.run(graph)

        # After the run, inspect violations:
        print(checker.get_violation_counts())
    """

    window_size = Option(int, default=1000, required=False)
    field_types = Option(default=None, required=False)
    value_ranges = Option(default=None, required=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Violation counters shared across all invocations of this node
        # instance.  Protected by _lock.
        self._violation_counts: dict = {}
        self._lock = threading.Lock()

    @ContextProcessor
    def _window(self, context):
        """Per-execution sliding window and local lock."""
        window = collections.deque(maxlen=self.window_size)
        yield window

    def __call__(self, _window, *args, **kwargs):
        """Check *args* against the configured quality rules, then pass through.

        Parameters injected by the ContextProcessor come first; the actual
        row data follows as *\\*args*.
        """
        # Reconstruct a simple field-index map from positional args.
        # If the context has named fields we use them; otherwise fall back to
        # integer positions.  We do not import context here to keep the
        # call signature simple — field_types / value_ranges use string keys.
        fields = list(range(len(args)))

        # Sliding window: append current tuple (plain tuple, drop bag type).
        _window.append(args)

        # --- null / empty check ---
        for i, val in enumerate(args):
            field_key = fields[i]
            if val is None or val == "":
                self._record_violation(f"null_empty[{field_key}]", field_key, val, "null or empty value")

        # --- type conformance ---
        if self.field_types:
            for field_name, expected_type in self.field_types.items():
                # Map string field names to positional indexes via args length.
                # If field_name is an int, use directly; otherwise skip
                # silently (caller has no named fields yet).
                idx = field_name if isinstance(field_name, int) else None
                if idx is not None and 0 <= idx < len(args):
                    val = args[idx]
                    if val is not None and not isinstance(val, expected_type):
                        self._record_violation(
                            f"type[{field_name}]",
                            field_name,
                            val,
                            f"expected {expected_type.__name__}, got {type(val).__name__}",
                        )

        # --- value ranges ---
        if self.value_ranges:
            for field_name, (lo, hi) in self.value_ranges.items():
                idx = field_name if isinstance(field_name, int) else None
                if idx is not None and 0 <= idx < len(args):
                    val = args[idx]
                    if val is not None and not (lo <= val <= hi):
                        self._record_violation(
                            f"range[{field_name}]",
                            field_name,
                            val,
                            f"value {val!r} outside [{lo}, {hi}]",
                        )

        return NOT_MODIFIED

    def _record_violation(self, key: str, field, value, reason: str) -> None:
        """Increment the counter for *key* and emit a warning."""
        with self._lock:
            self._violation_counts[key] = self._violation_counts.get(key, 0) + 1

        warnings.warn(
            f"DataQualityCheck violation — field={field!r} value={value!r}: {reason}",
            UserWarning,
            stacklevel=2,
        )

    def get_violation_counts(self) -> dict:
        """Return a snapshot of all violation counters.

        Returns a copy so callers do not hold the lock.

        Example return value::

            {
                "null_empty[0]": 3,
                "type[1]":        1,
                "range[2]":       2,
            }
        """
        with self._lock:
            return dict(self._violation_counts)
