Metrics
=======

Per-node tuple counters are exposed on
:class:`~bonobo.execution.contexts.graph.GraphExecutionContext` via the
:meth:`~bonobo.execution.contexts.graph.GraphExecutionContext.get_metrics`
method.

.. automethod:: bonobo.execution.contexts.graph.GraphExecutionContext.get_metrics

Design notes
------------

``NodeExecutionContext`` (a :class:`~bonobo.util.statistics.WithStatistics`
subclass) already maintains ``statistics`` counters — ``"in"``, ``"out"``,
``"err"``, and ``"warn"`` — that are incremented as rows flow through the node.
On CPython, ``+= 1`` operations on small integers are effectively atomic due to
the GIL, so no additional locking is needed for these read-mostly counters.

:meth:`~bonobo.execution.contexts.graph.GraphExecutionContext.get_metrics`
aggregates these per-node dicts into a single snapshot.  Callers racing with a
live execution may observe slightly stale values, which is acceptable for
monitoring and observability use-cases.

For the :class:`~bonobo.nodes.quality.DataQualityCheck` node's violation
counters, a :class:`threading.Lock` is used because those counters are written
from multiple concurrent node threads and the GIL does not provide sufficient
guarantees for dict mutation patterns.

Example
-------

.. code-block:: python

    import bonobo

    def extract():
        yield ("alice",)
        yield ("bob",)

    def load(*args):
        print(*args)

    ctx = bonobo.run(bonobo.Graph(extract, load))
    for node, counts in ctx.get_metrics().items():
        print(f"{node}: in={counts['in']} out={counts['out']}")
    # extract: in=0  out=2
    # load:    in=2  out=0
