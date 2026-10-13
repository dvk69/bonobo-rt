import logging
from functools import partial
from queue import Empty
from time import sleep

from whistle import EventDispatcher

from bonobo.config import create_container
from bonobo.constants import BEGIN, EMPTY, END
from bonobo.errors import InactiveReadableError
from bonobo.execution import events
from bonobo.execution.contexts.base import BaseContext
from bonobo.execution.contexts.node import AsyncNodeExecutionContext, NodeExecutionContext
from bonobo.execution.contexts.plugin import PluginExecutionContext

logger = logging.getLogger(__name__)


class BaseGraphExecutionContext(BaseContext):
    """
    Stores the actual state of a graph execution, and manages its lifecycle. This is an abstract base class for all
    graph execution contexts, and a few methods should actually be implemented for the child classes to be useable.

    """

    NodeExecutionContextType = NodeExecutionContext
    PluginExecutionContextType = PluginExecutionContext

    TICK_PERIOD = 0.25

    @property
    def started(self):
        if not len(self.nodes):
            return super(BaseGraphExecutionContext, self).started
        return any(node.started for node in self.nodes)

    @property
    def stopped(self):
        if not len(self.nodes):
            return super(BaseGraphExecutionContext, self).stopped
        return all(node.started and node.stopped for node in self.nodes)

    @property
    def alive(self):
        if not len(self.nodes):
            return super(BaseGraphExecutionContext, self).alive
        return any(node.alive for node in self.nodes)

    @property
    def xstatus(self):
        """
        UNIX-like exit status, only coherent if the context has stopped.

        """
        return max(node.xstatus for node in self.nodes) if len(self.nodes) else 0

    def __init__(self, graph, *, plugins=None, services=None, dispatcher=None):
        super(BaseGraphExecutionContext, self).__init__(graph)
        self.dispatcher = dispatcher or EventDispatcher()
        self.graph = graph
        self.nodes = [self.create_node_execution_context_for(node) for node in self.graph]
        self.plugins = [self.create_plugin_execution_context_for(plugin) for plugin in plugins or ()]
        self.services = create_container(services)

        # Probably not a good idea to use it unless you really know what you're doing. But you can access the context.
        self.services["__graph_context"] = self

        for i, node_context in enumerate(self):
            outputs = self.graph.outputs_of(i)
            if len(outputs):
                node_context.outputs = [self[j].input for j in outputs]
            node_context.input.on_begin = partial(node_context._put, BEGIN, _control=True)
            node_context.input.on_end = partial(node_context._put, END, _control=True)
            node_context.input.on_finalize = partial(node_context.stop)

    def __getitem__(self, item):
        return self.nodes[item]

    def __len__(self):
        return len(self.nodes)

    def __iter__(self):
        yield from self.nodes

    def create_node_execution_context_for(self, node):
        return self.NodeExecutionContextType(node, parent=self)

    def create_plugin_execution_context_for(self, plugin):
        if isinstance(plugin, type):
            plugin = plugin()
        return self.PluginExecutionContextType(plugin, parent=self)

    def dispatch(self, name):
        self.dispatcher.dispatch(name, events.ExecutionEvent(self))

    def register_plugins(self):
        for plugin_context in self.plugins:
            plugin_context.register()

    def unregister_plugins(self):
        for plugin_context in self.plugins:
            plugin_context.unregister()


class GraphExecutionContext(BaseGraphExecutionContext):
    """Concrete graph execution context.

    **Per-node metrics** are exposed via :meth:`get_metrics`.

    Design
    ------
    ``NodeExecutionContext`` (a :class:`~bonobo.util.statistics.WithStatistics`
    subclass) already maintains atomic-ish ``statistics`` counters for
    ``"in"``, ``"out"``, ``"err"``, and ``"warn"`` per node.  On CPython these
    ``+= 1`` operations are effectively atomic due to the GIL; the overhead is
    a single dict lookup per row, which is negligible compared to the I/O and
    transformation work in a typical ETL node.

    :meth:`get_metrics` returns a snapshot by iterating over ``self.nodes`` and
    reading each node's ``statistics`` dict.  It is a read-only view — it does
    not hold any lock, so a caller racing with live execution may see slightly
    stale counts, which is acceptable for observability purposes.
    """

    def get_metrics(self) -> dict:
        """Return per-node tuple-in / tuple-out / error counters.

        Returns a dict keyed by the node's ``__name__`` (falling back to its
        repr).  Each value is a dict with keys ``"in"``, ``"out"``, ``"err"``,
        and ``"warn"``.

        Example::

            ctx = bonobo.run(graph)
            for node_name, counts in ctx.get_metrics().items():
                print(node_name, counts)
            # extract  {'in': 0, 'out': 100, 'err': 0, 'warn': 0}
            # transform {'in': 100, 'out': 100, 'err': 0, 'warn': 0}
            # load     {'in': 100, 'out': 0,   'err': 0, 'warn': 0}
        """
        result = {}
        for node_ctx in self.nodes:
            name = node_ctx.__name__
            # Deduplicate names that appear more than once in the graph.
            key = name
            suffix = 2
            while key in result:
                key = f"{name}[{suffix}]"
                suffix += 1
            result[key] = dict(node_ctx.statistics)
        return result

    def start(self, starter=None):
        super(GraphExecutionContext, self).start()

        self.register_plugins()
        self.dispatch(events.START)
        self.tick(pause=False)

        for node in self.nodes:
            if starter is None:
                node.start()
            else:
                starter(node)

        self.dispatch(events.STARTED)

    def tick(self, pause=True):
        self.dispatch(events.TICK)
        if pause:
            sleep(self.TICK_PERIOD)

    def stop(self, stopper=None):
        super(GraphExecutionContext, self).stop()

        self.dispatch(events.STOP)
        for node_context in self.nodes:
            if not node_context.started:
                # A node that was submitted to the thread pool but whose
                # worker thread never ran has no resources to tear down.
                # Skipping it here preserves the Lifecycle contract
                # (stop() on an unstarted context raises RuntimeError)
                # while avoiding the race on Python 3.12+.
                continue
            if stopper is None:
                node_context.stop()
            else:
                stopper(node_context)
        self.tick(pause=False)
        self.dispatch(events.STOPPED)
        self.unregister_plugins()

    def kill(self):
        super(GraphExecutionContext, self).kill()

        self.dispatch(events.KILL)
        for node_context in self.nodes:
            node_context.kill()
        self.tick()

    def write(self, *messages):
        """Push a list of messages in the inputs of this graph's inputs, matching the output of special node "BEGIN" in
        our graph."""

        for i in self.graph.outputs_of(BEGIN):
            for message in messages:
                self[i].write(message)

    def loop(self):
        nodes = set(node for node in self.nodes if node.should_loop)
        while self.should_loop and len(nodes):
            self.tick(pause=False)
            for node in list(nodes):
                try:
                    node.step()
                except Empty:
                    continue
                except InactiveReadableError:
                    nodes.discard(node)

    def run_until_complete(self):
        self.write(BEGIN, EMPTY, END)
        self.loop()


class AsyncGraphExecutionContext(GraphExecutionContext):
    NodeExecutionContextType = AsyncNodeExecutionContext

    def __init__(self, *args, loop, **kwargs):
        self._event_loop = loop
        super().__init__(*args, **kwargs)

    def create_node_execution_context_for(self, node):
        return self.NodeExecutionContextType(node, parent=self, loop=self._event_loop)
