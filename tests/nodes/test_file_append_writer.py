"""Tests for bonobo.nodes.streaming — FileAppendWriter."""

import functools
import json
import threading

import pytest

from bonobo.nodes.streaming import FileAppendWriter
from bonobo.util.testing import BufferingNodeExecutionContext


# ---------------------------------------------------------------------------
# Configuration / options
# ---------------------------------------------------------------------------


def test_file_append_writer_requires_path():
    """Constructing without 'path' returns a PartiallyConfigured."""
    p = FileAppendWriter()
    assert isinstance(p, functools.partial)


def test_file_append_writer_defaults(tmp_path):
    """Default encoding is utf-8."""
    node = FileAppendWriter(path=str(tmp_path / "dummy.jsonl"))
    assert node.encoding == "utf-8"


def test_file_append_writer_custom_encoding(tmp_path):
    """Custom encoding option is stored."""
    node = FileAppendWriter(path=str(tmp_path / "out.jsonl"), encoding="latin-1")
    assert node.encoding == "latin-1"


# ---------------------------------------------------------------------------
# Functional tests — via BufferingNodeExecutionContext (single-field tuples)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(2)
def test_file_append_writer_single_field(tmp_path):
    """A single-field tuple is written as a scalar JSON value."""
    out = tmp_path / "out.jsonl"
    node = FileAppendWriter(path=str(out))

    with BufferingNodeExecutionContext(node) as ctx:
        ctx.write_sync("hello world")

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == "hello world"


@pytest.mark.timeout(2)
def test_file_append_writer_multiple_rows(tmp_path):
    """Multiple write_sync calls each produce a separate JSON line."""
    out = tmp_path / "out.jsonl"
    node = FileAppendWriter(path=str(out))

    with BufferingNodeExecutionContext(node) as ctx:
        for i in range(5):
            ctx.write_sync(f"row{i}")

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    for i, line in enumerate(lines):
        assert json.loads(line) == f"row{i}"


@pytest.mark.timeout(2)
def test_file_append_writer_appends_not_overwrites(tmp_path):
    """Each new context appends to an existing file rather than overwriting it."""
    out = tmp_path / "out.jsonl"
    # First context writes one row.
    node = FileAppendWriter(path=str(out))
    with BufferingNodeExecutionContext(node) as ctx:
        ctx.write_sync("first")

    # Second context must append.
    with BufferingNodeExecutionContext(node) as ctx:
        ctx.write_sync("second")

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == "first"
    assert json.loads(lines[1]) == "second"


@pytest.mark.timeout(2)
def test_file_append_writer_non_serialisable_uses_str(tmp_path):
    """Non-JSON-serialisable values fall back to str()."""
    from datetime import date

    out = tmp_path / "out.jsonl"
    node = FileAppendWriter(path=str(out))

    with BufferingNodeExecutionContext(node) as ctx:
        ctx.write_sync(date(2024, 1, 15))

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "2024-01-15" in lines[0]


# ---------------------------------------------------------------------------
# Multi-field tuple serialisation — direct __call__ with injected lock
# ---------------------------------------------------------------------------


@pytest.mark.timeout(2)
def test_file_append_writer_multi_field_serialisation(tmp_path):
    """Multi-field tuples are serialised as JSON arrays."""
    from bonobo.util.objects import ValueHolder

    out = tmp_path / "out.jsonl"

    node = FileAppendWriter(path=str(out))
    lock = threading.Lock()

    # Open the file manually to simulate what the ContextProcessor does.
    with open(str(out), "a", encoding="utf-8") as fh:
        fh_lock = ValueHolder((fh, lock))
        node(fh_lock, "alice", 42, True)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == ["alice", 42, True]


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------


@pytest.mark.timeout(5)
def test_file_append_writer_thread_safe(tmp_path):
    """Concurrent writes from multiple threads do not corrupt the file."""
    from bonobo.util.objects import ValueHolder

    out = tmp_path / "out.jsonl"
    lock = threading.Lock()

    node = FileAppendWriter(path=str(out))

    n_threads = 10
    n_per_thread = 50

    with open(str(out), "a", encoding="utf-8") as fh:
        fh_lock = ValueHolder((fh, lock))

        def write_rows(tid):
            for i in range(n_per_thread):
                node(fh_lock, f"thread-{tid}-row-{i}")

        threads = [threading.Thread(target=write_rows, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    lines = out.read_text(encoding="utf-8").splitlines()
    # Every line must be independently parseable JSON.
    parsed = [json.loads(ln) for ln in lines]
    assert len(parsed) == n_threads * n_per_thread
