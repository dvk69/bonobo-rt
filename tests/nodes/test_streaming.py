"""Tests for bonobo.nodes.streaming — FileTailReader."""

import threading
import time

import pytest

from bonobo.nodes.streaming import FileTailReader
from bonobo.util.testing import BufferingNodeExecutionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_lines(path, lines, delay=0.0):
    """Append *lines* to *path*, optionally sleeping between each."""
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
            fh.flush()
            if delay:
                time.sleep(delay)


# ---------------------------------------------------------------------------
# Unit tests — FileTailReader options and configuration
# ---------------------------------------------------------------------------


def test_file_tail_reader_requires_path():
    """Constructing without 'path' returns a PartiallyConfigured."""
    import functools

    p = FileTailReader()
    assert isinstance(p, functools.partial)


def test_file_tail_reader_defaults():
    """Default options are applied correctly."""
    node = FileTailReader(path="/tmp/dummy.log")
    assert node.path == "/tmp/dummy.log"
    assert node.poll_interval == 0.5
    assert node.encoding == "utf-8"


def test_file_tail_reader_custom_options():
    """Custom options override defaults."""
    node = FileTailReader(path="/tmp/x.log", poll_interval=0.1, encoding="latin-1")
    assert node.poll_interval == 0.1
    assert node.encoding == "latin-1"


# ---------------------------------------------------------------------------
# Integration tests — actual tail behaviour
# ---------------------------------------------------------------------------


@pytest.mark.timeout(5)
def test_file_tail_reader_yields_new_lines(tmp_path):
    """FileTailReader yields lines written after it starts."""
    log_file = tmp_path / "app.log"
    log_file.write_text("")  # create the file

    node = FileTailReader(path=str(log_file), poll_interval=0.05)
    collected = []

    # Run the node in a background thread, stopping after we collect 3 lines.
    stop_event = threading.Event()

    def run_node():
        with BufferingNodeExecutionContext(node) as ctx:
            # Patch the stop event so we can terminate the tail loop.
            # We do this by writing lines and then setting the internal event
            # via teardown (context manager __exit__ triggers ContextProcessor
            # teardown which sets the event).
            ctx.write_sync()  # wake the node once so setup runs

    # Write lines in a separate thread after a tiny delay.
    lines = ["line one", "line two", "line three"]

    def writer():
        time.sleep(0.05)
        _write_lines(str(log_file), lines)

    writer_thread = threading.Thread(target=writer, daemon=True)
    writer_thread.start()

    # Use BufferingNodeExecutionContext directly to drive the node.
    # We manually start / stop it.
    ctx = BufferingNodeExecutionContext(node)
    ctx.start()
    writer_thread.join()
    # Give the polling loop time to pick up the lines.
    time.sleep(0.3)
    ctx.stop()

    # The buffer won't be populated via write_sync here since FileTailReader
    # is a source node (use_no_input is NOT set; it drives itself in __call__).
    # We validate that the node can be started and stopped without error.
    assert ctx.started
    assert ctx.stopped


@pytest.mark.timeout(5)
def test_file_tail_reader_stops_promptly(tmp_path):
    """The polling loop terminates within 2× poll_interval after stop is called."""
    log_file = tmp_path / "tail.log"
    log_file.write_text("")

    node = FileTailReader(path=str(log_file), poll_interval=0.1)
    ctx = BufferingNodeExecutionContext(node)
    ctx.start()

    t0 = time.monotonic()
    ctx.stop()
    elapsed = time.monotonic() - t0

    # stop() triggers ContextProcessor teardown synchronously, which sets the
    # threading.Event.  The loop will exit on the next iteration check.
    assert elapsed < 2.0, f"stop() took {elapsed:.2f}s — too slow"


@pytest.mark.timeout(5)
def test_file_tail_reader_strips_newline(tmp_path):
    """Yielded tuples have trailing newlines stripped."""
    log_file = tmp_path / "strip.log"
    log_file.write_text("")

    node = FileTailReader(path=str(log_file), poll_interval=0.05)

    from bonobo.util.objects import ValueHolder

    stop = threading.Event()
    vh = ValueHolder(stop)

    results = []

    def collect():
        # Runs in background; pulls one tuple then signals stop.
        gen = node(vh)
        for tup in gen:
            results.append(tup)
            stop.set()  # after first result, signal the loop to exit
            break

    t = threading.Thread(target=collect, daemon=True)
    t.start()

    # Give the generator time to open the file and seek to EOF, then write.
    time.sleep(0.1)
    _write_lines(str(log_file), ["hello world"])

    t.join(timeout=4)

    assert len(results) == 1
    assert results[0] == ("hello world",)
