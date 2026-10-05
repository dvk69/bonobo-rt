# AGENTS.md — Plan (Architecture) Mode

This file provides guidance to agents when working with code in this repository.

## Non-obvious architectural constraints

- **Deferred instantiation is by design**: `Configurable.__new__` intentionally returns a `functools.partial` when options are missing. This enables partial application / currying of transformation nodes before wiring them into a graph. Any new `Configurable` subclass must not break this contract.
- **Option ordering is load-order-stable**: `Option._creation_counter` is a class-level integer incremented at each instantiation; `ConfigurableMeta` uses it to sort options deterministically. Positional options must be declared before keyword options for correct argument binding.
- **`ContextProcessor` is the only approved statefulness mechanism** — any design that requires mutable instance state in a transformation must use `ContextProcessor` instead, or it will break under concurrent execution (the default threadpool strategy runs each node in its own thread).
- **Graph execution is strategy-pluggable**: `create_strategy()` returns a `Strategy` subclass. The default is the threadpool executor. `NaiveStrategy` (single-threaded, synchronous) exists for testing/debugging. New strategies must subclass [`Strategy`](../../bonobo/execution/strategies/base.py).
- **`BEGIN` is not a real node** — it is a sentinel `Token`. The graph connects it as the implicit source; actual data flow starts from nodes connected from `BEGIN`. Treat it as an architectural constant, not a callable.
- **`Service` resolution happens at execution time** via `Container.kwargs_for()` — not at graph build time. Services missing from the container raise `MissingServiceImplementationError` (an `UnrecoverableError`) at runtime, halting the workflow.
- **`Exclusive`** (in `bonobo.config`) provides a re-entrant lock around a service instance — this is the supported mechanism for call-order-sensitive services in multi-threaded strategies. Do not use module-level locks.
- **`NOT_MODIFIED` / `EMPTY` semantics**: returning `NOT_MODIFIED` re-emits the exact input tuple; returning/yielding `EMPTY` (`()`) emits nothing downstream. These are architectural contracts, not just convenience aliases.
