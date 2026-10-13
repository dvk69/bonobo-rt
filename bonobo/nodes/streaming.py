"""
bonobo.nodes.streaming
======================

Streaming source nodes for Bonobo ETL.

Currently provided:

* :class:`FileTailReader` — source node that yields new lines appended to a
  file, similar to ``tail -F``.  Designed to run inside the standard
  ``ThreadPoolExecutorStrategy``; it terminates promptly when the graph stops.
"""

import threading
import time

from bonobo.config import Configurable, ContextProcessor, Option
from bonobo.util.objects import ValueHolder

__all__ = ["FileTailReader"]


class FileTailReader(Configurable):
    """Source node that continuously yields lines appended to *path*, similar
    to ``tail -F``.

    Each new line is yielded as a single-element tuple ``(line,)`` with the
    trailing newline stripped.  The node opens the file, seeks to the end, and
    polls for new data every *poll_interval* seconds.

    **Shutdown**: the node respects the graph lifecycle.  The
    :class:`~bonobo.config.processors.ContextProcessor` sets a
    :class:`threading.Event` that is cleared when the graph teardown runs
    (i.e. after the node's loop exits).  The polling loop checks the event
    every *poll_interval* seconds and exits as soon as it is set — no orphaned
    busy-loop threads.

    Options
    -------
    path
        Path to the file to tail.  **Required.**
    poll_interval
        Seconds to sleep between polls when no new data is available.
        Default: ``0.5``.
    encoding
        Text encoding passed to :func:`open`.  Default: ``"utf-8"``.

    Example
    -------
    .. code-block:: python

        import bonobo

        graph = bonobo.Graph(
            bonobo.FileTailReader("/var/log/app.log"),
            print,
        )
        bonobo.run(graph)
    """

    path = Option(str, positional=True, required=True)
    poll_interval = Option(float, default=0.5, required=False)
    encoding = Option(str, default="utf-8", required=False)

    @ContextProcessor
    def _stop_event(self, context):
        """Provide a threading.Event that signals the polling loop to exit."""
        event = threading.Event()
        yield ValueHolder(event)
        # Teardown: signal the loop to stop.
        event.set()

    def __call__(self, _stop_event):
        """Tail the file, yielding each new line as a 1-tuple.

        The *_stop_event* argument is injected by the :class:`ContextProcessor`
        above.  The loop exits as soon as the event is set (i.e. the graph is
        stopping).
        """
        stop_event = _stop_event.get()

        with open(self.path, encoding=self.encoding) as fh:
            # Seek to the end so we only pick up *new* lines.
            fh.seek(0, 2)

            while not stop_event.is_set():
                line = fh.readline()
                if line:
                    yield (line.rstrip("\n"),)
                else:
                    # No new data — sleep in short slices so we can react
                    # promptly to the stop signal.
                    stop_event.wait(timeout=self.poll_interval)
