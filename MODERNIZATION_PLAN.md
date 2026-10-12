# Bonobo Modernization Plan

> **Scope:** Migrate the Bonobo 0.7.0rc2 ETL framework from its 2019-era Python 3.5 baseline to a
> production-ready state on Python 3.12+. No source-logic regressions. New streaming and
> real-time data-quality features are layered on top after the core is stabilized.

---

## Architecture Map

### What Bonobo Is

Bonobo is a **graph-oriented, stream-processing ETL framework**. You declare transformations as
plain callables (or `Configurable` subclasses), wire them into a directed acyclic `Graph`, and
execute the graph via a pluggable `Strategy`. Data flows through in-memory queues as tuples;
each node consumes a tuple from its input queue, optionally yields one or more tuples, and those
are pushed onto all downstream queues automatically.

---

### Subsystem Overview

#### 1. Config subsystem — `bonobo/config/`

The configuration system is the DI backbone of every user-facing node.

- **`ConfigurableMeta`** (metaclass, [`configurables.py`](bonobo/config/configurables.py)) — scans
  the class MRO at class-creation time, collects all `Option` descriptors into a sorted list
  (`__options`), and wires them so that `Configurable.__new__` can decide at instantiation time
  whether all required options are present.

- **`Configurable.__new__`** — if any required `Option` is missing it returns a
  `PartiallyConfigured` (`functools.partial` subclass) instead of a real instance. This is the
  "deferred instantiation / currying" contract that the entire graph-building API relies on.

- **`Option`** (descriptor, [`options.py`](bonobo/config/options.py)) — each field on a
  `Configurable` is an `Option`. An `_creation_counter` class-level integer stamps each `Option`
  at definition time; `ConfigurableMeta` sorts by it to guarantee stable, positional-first
  ordering regardless of load order.

- **`ContextProcessor`** (subclass of `Option`, [`processors.py`](bonobo/config/processors.py))
  — a generator-based setup/teardown hook. Yield once to produce a value that is injected as an
  extra positional argument into `__call__` for the lifetime of execution. This is the **only**
  approved way to carry mutable state across calls (e.g. open files, DB connections).

- **`Service`** + **`Container`** ([`services.py`](bonobo/config/services.py)) — a `Service`
  descriptor declares an external dependency by name. `Container.kwargs_for()` resolves those
  names from the registry at execution start. `Exclusive` wraps a service in an `RLock` for
  call-order-sensitive multi-threaded access.

#### 2. Graph subsystem — `bonobo/structs/`

- **`Graph`** ([`graphs.py`](bonobo/structs/graphs.py)) — an adjacency-list directed graph. Nodes
  are stored by integer index in `self.nodes`; edges live in `self.edges` as `{index: set(indices)}`.
  The sentinel `BEGIN` (a `Token`, not a callable) is the implicit source node; all "extractor"
  nodes connect from it. `topologically_sorted_indexes` drives execution ordering.

- **`GraphCursor`** — provides the `>>` operator syntax (`graph.get_cursor() >> node_a >> node_b`)
  for ergonomic graph building without manual `add_chain` calls.

- **`Input`** queue ([`inputs.py`](bonobo/structs/inputs.py)) — a `Queue` subclass that
  counts active `BEGIN`/`END` tokens as a reference-counted *runlevel*. A node's input becomes
  "inactive" (raises `InactiveReadableError`) when the runlevel reaches zero, which is the signal
  for the node loop to terminate naturally.

#### 3. Execution subsystem — `bonobo/execution/`

The execution subsystem implements the runtime lifecycle.

- **`Lifecycle`** ([`contexts/base.py`](bonobo/execution/contexts/base.py)) — a state machine with
  four boolean flags: `_started`, `_stopped`, `_killed`, `_defunct`. The derived properties
  `alive` and `should_loop` gate the main processing loops.

- **`NodeExecutionContext`** ([`contexts/node.py`](bonobo/execution/contexts/node.py)) — wraps a
  single callable node. Its `start()` method builds a `ContextCurrifier` stack (services + context
  processors). Its `loop()` / `step()` / `_step()` methods pull from the `Input` queue, invoke the
  stack, and push results to all output queues. Generator-based nodes are iterated to exhaustion
  per input tuple.

- **`GraphExecutionContext`** ([`contexts/graph.py`](bonobo/execution/contexts/graph.py)) — owns
  a `NodeExecutionContext` for each graph node and wires up the inter-node queues during `__init__`
  by linking `node_context.outputs` to downstream `node.input` references. Dispatches lifecycle
  events (`START`, `STARTED`, `TICK`, `STOP`, `STOPPED`, `KILL`) via a `whistle.EventDispatcher`.

- **`Strategy`** / **`ExecutorStrategy`** ([`strategies/`](bonobo/execution/strategies/)) — the
  strategy pattern decouples *how* nodes are scheduled from the rest of the runtime:
  - `NaiveStrategy` — single-threaded, synchronous; used for testing.
  - `ThreadPoolExecutorStrategy` (default) — each node runs in its own thread via
    `concurrent.futures.ThreadPoolExecutor`.
  - `AsyncThreadPoolExecutorStrategy` — experimental (`ALPHA=True` required); uses
    `asyncio.get_event_loop()` (deprecated call in 3.10+).
  - `ProcessPoolExecutorStrategy` — process-based parallelism (pickling constraints apply).

#### 4. Node library — `bonobo/nodes/`

Built-in transformations (`CsvReader`, `CsvWriter`, `JsonReader`, `LdjsonWriter`, `Filter`,
`Limit`, `FixedWindow`, `RateLimited`, …) are all `Configurable` subclasses. I/O nodes use
`ContextProcessor` to open/close file handles around the execution window.

#### 5. Plugin system — `bonobo/plugins/` + `stevedore`

Plugins (e.g. `ConsoleOutputPlugin`, `JupyterOutputPlugin`) attach to `GraphExecutionContext`
lifecycle events. They are discovered via `stevedore` entry-points — the `bonobo.commands`
entry-point group drives the CLI.

---

### Component Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                         bonobo public API                            │
│  bonobo.run()  bonobo.Graph  bonobo.CsvReader  bonobo.Filter  …      │
└────────────────────────┬─────────────────────────────────────────────┘
                         │
          ┌──────────────▼──────────────┐
          │       Execution Engine      │
          │  Strategy ──► GraphContext  │
          │              │              │
          │         NodeContext[]       │
          │         Input queues        │
          └──┬──────────────────────┬───┘
             │                      │
    ┌────────▼────────┐   ┌─────────▼────────┐
    │  Config / DI    │   │  Graph / Structs  │
    │  Configurable   │   │  Graph            │
    │  Option         │   │  GraphCursor      │
    │  ContextProc.   │   │  Input queue      │
    │  Service        │   │  Token / Flag     │
    │  Container      │   └──────────────────┘
    └─────────────────┘
             │
    ┌────────▼────────────────────────────────┐
    │           Built-in Nodes                │
    │  CsvReader/Writer  JsonReader/Writer     │
    │  FileReader/Writer  Filter  Limit  …     │
    └─────────────────────────────────────────┘
             │
    ┌────────▼────────┐
    │    Plugins      │
    │  Console        │
    │  Jupyter        │
    │  Sentry         │
    └─────────────────┘
```

---

## Dependency Audit

### Core runtime dependencies (declared in `setup.py`, pinned in `requirements.txt`)

| Package | Pinned Version | Current Latest | Status / Issue |
|---|---|---|---|
| `cached-property` | `~= 1.4` (1.5.1) | 1.5.2 | **Dead** — `functools.cached_property` ships in stdlib 3.8+; drop this entirely |
| `fs` | `~= 2.0` (2.4.8) | 2.4.16 | Still maintained; minor pin bump needed |
| `graphviz` | `>= 0.8, < 0.9` (0.8.4) | 0.20+ | **Severely outdated** — `graphviz.dot.Digraph` import path changed; API has breaking changes |
| `jinja2` | `~= 2.9` (2.10.1) | 3.x | **Major version gap** — 2.x is EOL; security CVEs; must upgrade to 3.x |
| `mondrian` | `~= 0.8` (0.8.0) | 0.8.x | Low-activity; used for terminal formatting |
| `packaging` | `~= 19.0` (19.0) | 24.x | Safe to upgrade; API stable |
| `psutil` | `~= 5.4` (5.6.3) | 6.x | Upgrade to 6.x for 3.12 support |
| `python-slugify` | `~= 1.2.0` (1.2.6) | 8.x | **Major version gap** — API stable but must drop strict pin |
| `requests` | `~= 2.0` (2.22.0) | 2.32.x | Safe upgrade; security patches important |
| `stevedore` | `~= 1.27` (1.30.1) | 5.x | **Major version gap**; must upgrade for modern `importlib.metadata` internals |
| `whistle` | `~= 1.0` (1.0.1) | 1.0.1 | Dormant; no 3.12 issues found; consider inlining if abandoned |

### Dev dependencies

| Package | Pinned Version | Status |
|---|---|---|
| `coverage` | `~= 4.5` | **Dead** — upgrade to 7.x |
| `pytest` | `~= 4.6` | **Severely outdated** — upgrade to 8.x |
| `pytest-cov` | `~= 2.7` | Upgrade to 5.x |
| `pytest-timeout` | `>= 1, < 2` | Upgrade to 2.x |
| `sphinx` | `~= 1.7` | **Dead** — upgrade to 7.x or 8.x |
| `sphinx-sitemap` | `>= 0.2, < 0.3` | Upgrade |
| `cookiecutter` | `>= 1.5, < 1.6` | **Dead** — upgrade to 2.x |
| `typing` | `3.7.4` | **Remove** — `typing` is stdlib since 3.5 |

### Deprecated API patterns in source

| Pattern | File(s) | Issue |
|---|---|---|
| `asyncio.get_event_loop()` | [`strategies/executor.py:96`](bonobo/execution/strategies/executor.py) | Deprecated in 3.10, raises `DeprecationWarning` in 3.12; use `asyncio.new_event_loop()` or `asyncio.run()` |
| `pip.main(...)` + `pip.utils.pkg_resources` | [`commands/run.py:63,67`](bonobo/commands/run.py) | `pip.main` removed in pip 10 (2018); this code is broken on any current pip |
| `pkg_resources.working_set` | [`util/pkgs.py:5`](bonobo/util/pkgs.py) | `pkg_resources` is deprecated; replace with `importlib.metadata` (3.8+ stdlib) |
| `cached_property` (third-party) | [`strategies/executor.py:7`](bonobo/execution/strategies/executor.py) | Replace with `functools.cached_property` (3.8+ stdlib) |
| `collections.OrderedDict` | [`util/bags.py`](bonobo/util/bags.py), [`nodes/io/json.py`](bonobo/nodes/io/json.py) | Plain `dict` preserves insertion order since 3.7; `OrderedDict` fine but unnecessary |
| `from graphviz.dot import Digraph` | [`structs/graphs.py:7`](bonobo/structs/graphs.py) | Private import path; changed in graphviz 0.14+ |
| `execfile` polyfill | [`setup.py:12-18`](setup.py) | Python 2 compat dead code; entire `setup.py` to be replaced |
| `six` (transitive dep) | `requirements.txt` | Remove; Python 2/3 compat layer no longer needed |

### CI / packaging infrastructure

| Artifact | Issue |
|---|---|
| `.travis.yml` | Tests only Python 3.5–3.7; 3.8 commented out; Travis CI free tier discontinued for open source |
| `appveyor.yml`, `wercker.yml` | Unused CI configs for defunct/irrelevant platforms |
| `setup.py` (Medikit-generated) | PEP 517/518 non-compliant; "All changes will be overridden" comment; no `pyproject.toml` |
| `Makefile` (Medikit-generated) | Same — do not hand-edit; must migrate off Medikit |
| `Projectfile` | Medikit DSL; becomes obsolete once we migrate to `pyproject.toml` |
| `setup.cfg` | Contains only `[bdist_wheel] universal=1` (wrong — this is a Python 3-only package) |
| `readthedocs.yml` | Old RTD v1 config format; needs `readthedocs.yaml` v2 |

---

## Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | `graphviz` API breaking change | High | Medium | Audit `_repr_dot_` and `_repr_html_` against graphviz 0.20 changelog; isolate behind adapter |
| R-02 | `jinja2` 3.x breaking change | Medium | Medium | `Undefined` strictness and `Environment` defaults changed; test all template rendering paths |
| R-03 | `stevedore` 5.x drops Python 3.5 compat shims | Low | Low | API surface used is stable (`ExtensionManager`); test after upgrade |
| R-04 | `AsyncThreadPoolExecutorStrategy` relies on deprecated `asyncio.get_event_loop()` | High | High | Rewrite or remove; if keeping async strategy, use `asyncio.run()` + task-based design |
| R-05 | `pip.main()` call is already broken on modern pip | High | Low | The `--install` flag is a niche feature; replace with `subprocess` or remove |
| R-06 | `cached-property` third-party removal touches `executor.py` | Low | Low | One-line swap to `functools.cached_property` |
| R-07 | `PartiallyConfigured` relies on `_functools` C extension internals | Medium | High | The `_functools.partial` subclass accesses internal `__options_values` — verify behavior unchanged under 3.12; add explicit tests |
| R-08 | Thread-safety in `NodeExecutionContext` with 3.12 GIL changes | Low | Medium | 3.12 introduced `PYTHONFREETHREAD` but default GIL still present; monitor for 3.13 free-thread builds |
| R-09 | `whistle` library is dormant | Low | Low | Inline the `EventDispatcher` (~50 LOC) if the library stops building |
| R-10 | No `pyproject.toml` means no PEP 660 editable installs | Medium | Low | Required for modern `pip install -e .` to work without legacy mode |

---

## Execution Plan

The work is divided into four self-contained phases. Each phase is independently reviewable and
deployable. Phases 3 and 4 depend on Phase 2 being complete.

---

### Phase 1 — Packaging & CI

**Intent:** Replace the Medikit-generated build system with a modern `pyproject.toml`-based setup,
upgrade all pinned dependency bounds, and replace Travis CI with GitHub Actions. This phase touches
no runtime logic — only packaging and developer tooling.

**Expected Outcomes:**
- `pip install -e .` and `pip install bonobo` both work on Python 3.12 with no deprecation warnings from pip
- `pytest` suite runs and passes under GitHub Actions on Python 3.10, 3.11, 3.12
- `mypy --strict` (or `pyright`) can be invoked as a CI step without crashing on import
- `readthedocs.yaml` v2 config present and RTD preview builds succeed

**Todo List:**
- [ ] Create `pyproject.toml` with `[build-system]`, `[project]`, `[project.optional-dependencies]`, and `[project.entry-points]` sections, replacing `setup.py` / `setup.cfg` / `Projectfile`
- [ ] Set `requires-python = ">=3.10"` as the new minimum (3.10 brings `match`, structural pattern matching; 3.12 is the primary target)
- [ ] Upgrade all `install_requires` pins: drop `cached-property`, loosen `graphviz` to `>= 0.20`, `jinja2 >= 3.0`, `packaging >= 24`, `psutil >= 6`, `python-slugify >= 8`, `stevedore >= 5`
- [ ] Upgrade `[project.optional-dependencies].dev`: `pytest >= 8`, `pytest-cov >= 5`, `pytest-timeout >= 2`, `coverage >= 7`, `sphinx >= 7`, drop `typing`, upgrade `cookiecutter >= 2`
- [ ] Remove `setup.py`, `setup.cfg`, `Projectfile`; keep `Makefile` with hand-written targets only (no Medikit regeneration)
- [ ] Fix `setup.cfg` `universal=1` wheel flag — remove it (Python-3-only package)
- [ ] Add `.github/workflows/ci.yml` with matrix over Python 3.10 / 3.11 / 3.12 and OS linux / macos; steps: install, lint, test, coverage upload
- [ ] Remove `.travis.yml`, `appveyor.yml`, `wercker.yml`
- [ ] Update `readthedocs.yml` → `readthedocs.yaml` v2 format
- [ ] Verify `bonobo --version` entry-point works after packaging migration

**Relevant Context:**
- [`setup.py`](setup.py) — to be deleted
- [`setup.cfg`](setup.cfg) — to be deleted
- [`Projectfile`](Projectfile) — to be deleted
- [`Makefile`](Makefile) — strip Medikit targets, keep `test`, `format`, `clean`, `install-dev`
- [`requirements.txt`](requirements.txt), [`requirements-dev.txt`](requirements-dev.txt) — regenerate from `pyproject.toml` via `pip-compile` or keep inline
- [`bonobo/commands/version.py`](bonobo/commands/version.py) — ensure version reads from `importlib.metadata` after packaging change

**Status:** `[ ] pending`

---

### Phase 2 — Core Engine on Modern Python

**Intent:** Fix every deprecated or broken runtime API call so the framework runs correctly on
Python 3.12 with no `DeprecationWarning`s from the stdlib or third-party packages. Sub-tasks
within this phase should be tackled in dependency order (stdlib swaps first, then broken external
calls, then the async strategy).

**Expected Outcomes:**
- Full test suite passes on Python 3.12 with zero `DeprecationWarning`s
- `PYTHONWARNINGS=error pytest` exits 0
- `AsyncThreadPoolExecutorStrategy` either works correctly or is clearly marked removed/deferred
- No references to `pkg_resources`, `cached_property` (third-party), or `pip.main`

**Todo List:**

*2a — Stdlib API swaps (zero behavior change, low risk)*
- [ ] Replace `from cached_property import cached_property` with `from functools import cached_property` in [`strategies/executor.py`](bonobo/execution/strategies/executor.py)
- [ ] Replace `pkg_resources.working_set` in [`util/pkgs.py`](bonobo/util/pkgs.py) with `importlib.metadata.packages_distributions()` (3.11+) or iterate `importlib.metadata.distributions()`
- [ ] Remove the `typing==3.7.4` entry from dev requirements (stdlib since 3.5)
- [ ] Replace `from graphviz.dot import Digraph` with `from graphviz import Digraph` (public API) in [`structs/graphs.py`](bonobo/structs/graphs.py)
- [ ] Replace `collections.OrderedDict` with plain `dict` in [`util/bags.py`](bonobo/util/bags.py) and [`nodes/io/json.py`](bonobo/nodes/io/json.py)

*2b — Broken external calls (requires functional testing)*
- [ ] Rewrite `_install_requirements()` in [`commands/run.py`](bonobo/commands/run.py) to use `subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements])` and remove the `pip.utils.pkg_resources` reload hack
- [ ] Test `bonobo run --install <path>` end-to-end after the fix

*2c — graphviz API upgrade*
- [ ] Audit `Graph.graphviz`, `_repr_dot_()`, and `_repr_html_()` in [`structs/graphs.py`](bonobo/structs/graphs.py) against graphviz 0.20 changelog
- [ ] Fix any changed constructor signatures or render-path calls
- [ ] Add/update tests in `tests/structs/test_graphs.py` to cover the graphviz output paths

*2d — jinja2 3.x upgrade*
- [ ] Identify all `jinja2.Environment` / `Template` usages in [`bonobo/commands/`](bonobo/commands/) and [`bonobo/contrib/`](bonobo/contrib/)
- [ ] Audit against jinja2 3.x migration guide (particularly `autoescape` defaults and `Undefined` strictness)
- [ ] Update usages and add regression tests

*2e — Async strategy (highest risk)*
- [ ] Replace deprecated `asyncio.get_event_loop()` call in [`strategies/executor.py:96`](bonobo/execution/strategies/executor.py) with `asyncio.new_event_loop()` stored as instance state, or restructure `AsyncThreadPoolExecutorStrategy.execute()` to use `asyncio.run()`
- [ ] Verify `AioInput` ([`structs/inputs.py`](bonobo/structs/inputs.py)) works with the updated event loop
- [ ] Add integration test that exercises the async strategy end-to-end
- [ ] If the async strategy cannot be made correct without a larger redesign, mark it `NotImplementedError` with a clear deprecation message and open a tracked issue

*2f — PartiallyConfigured stability check*
- [ ] Write explicit tests for `PartiallyConfigured._options_values` behavior under Python 3.12 (specifically the `_functools.partial` C extension subclassing path in [`configurables.py:76`](bonobo/config/configurables.py))
- [ ] Confirm `__getattr__` delegation works correctly with the updated interpreter

**Relevant Context:**
- [`bonobo/execution/strategies/executor.py`](bonobo/execution/strategies/executor.py) — `cached_property`, `asyncio.get_event_loop`
- [`bonobo/util/pkgs.py`](bonobo/util/pkgs.py) — `pkg_resources`
- [`bonobo/commands/run.py`](bonobo/commands/run.py) — `pip.main`
- [`bonobo/structs/graphs.py`](bonobo/structs/graphs.py) — `graphviz.dot.Digraph`
- [`bonobo/config/configurables.py`](bonobo/config/configurables.py) — `_functools.partial` subclass

**Status:** `[ ] pending`

---

### Phase 3 — Tests & Documentation

**Intent:** Raise test coverage to a meaningful baseline for a modernized codebase, add type
annotations to the public API surface, and refresh the documentation so it accurately describes
the current architecture.

**Expected Outcomes:**
- Statement coverage ≥ 85% on `bonobo/` (excluding `bonobo/examples/` and `bonobo/ext/` as per `.coveragerc`)
- All public symbols in `bonobo/_api.py` have type annotations
- `mypy --strict bonobo/_api.py` passes
- Sphinx docs build without warnings and accurately reflect Phase 1–2 changes
- `CHANGELOG.md` entry for the 0.8.0 release covering all breaking changes

**Todo List:**

*3a — Type annotations*
- [ ] Add type annotations to all symbols exported from [`bonobo/_api.py`](bonobo/_api.py)
- [ ] Annotate `Configurable`, `Option`, `ContextProcessor`, `Service`, `Container` in [`bonobo/config/`](bonobo/config/)
- [ ] Annotate `Graph`, `GraphCursor`, `Input` in [`bonobo/structs/`](bonobo/structs/)
- [ ] Annotate `NodeExecutionContext`, `GraphExecutionContext`, strategy classes in [`bonobo/execution/`](bonobo/execution/)
- [ ] Add `py.typed` marker file to the package root

*3b — Test coverage gaps*
- [ ] Add tests for the `--install` flag fix from Phase 2b
- [ ] Add tests covering `Exclusive` thread-safety in [`config/services.py`](bonobo/config/services.py)
- [ ] Add tests for `ProcessPoolExecutorStrategy` (currently untested)
- [ ] Add tests for `FixedWindow`, `RateLimited`, `UnpackItems` in [`nodes/basics.py`](bonobo/nodes/basics.py)
- [ ] Add integration test: full graph execution (extractor → transform → loader) under `ThreadPoolExecutorStrategy` with service injection
- [ ] Add integration test: `NOT_MODIFIED` and `EMPTY` semantics in a multi-node graph

*3c — Documentation*
- [ ] Update `README.rst` with Python 3.10+ requirement and updated installation instructions
- [ ] Rewrite architecture overview in docs to match the component map in this document
- [ ] Add migration guide section: what changes for users upgrading from 0.7.x
- [ ] Update `readthedocs.yaml` v2 config to use `mamba`/`mambaforge` or a plain `pip` install
- [ ] Add `CHANGELOG.md` with 0.8.0 breaking changes section

**Relevant Context:**
- [`bonobo/_api.py`](bonobo/_api.py) — public API surface
- [`tests/`](tests/) — existing test layout to extend
- [`docs/`](docs/) — Sphinx sources

**Status:** `[ ] pending`

---

### Phase 4 — Streaming & Real-Time Data Quality Features

**Intent:** Extend the core with two new capabilities that are natural fits for the Bonobo graph
model: (1) a proper async/streaming mode that does not require `ALPHA=True`, built on
`asyncio` task-per-node with backpressure-aware queues; (2) a composable data-quality layer
that lets users declare schema expectations on edges and get per-edge validation metrics.

These features must not break the existing synchronous `ThreadPoolExecutorStrategy` path.

**Expected Outcomes:**
- `AsyncStrategy` (new name) replaces `AsyncThreadPoolExecutorStrategy` and works without any env flag
- `Edge(schema=...)` declaration syntax allows attaching a Pydantic / attrs validator to any graph edge
- Failed validation emits a structured warning (not an exception) by default; can be upgraded to `UnrecoverableError` via policy
- New `bonobo.metrics` module exposes per-edge in/out/validation-failure counters
- All new features covered by tests; documented with examples

**Todo List:**

*4a — Native async strategy*
- [ ] Design `AsyncStrategy` API: determine whether it replaces the thread-pool node model or layers `asyncio.Queue` over existing `Input` queues
- [ ] Implement `AsyncStrategy.execute()` using `asyncio.run()` + `asyncio.gather()` (one coroutine per node)
- [ ] Implement async-native `AsyncNodeExecutionContext` using `asyncio.Queue` instead of `threading.Queue`
- [ ] Ensure `ContextProcessor` teardown runs correctly inside `async with` semantics
- [ ] Add `bonobo.run_async(graph, ...)` to `_api.py` and document it
- [ ] Add integration tests and examples

*4b — Data quality / schema validation layer*
- [ ] Research integration points: edge metadata on `Graph.edges`, validation hooks in `NodeExecutionContext._put`
- [ ] Design `Edge` descriptor / `SchemaOption` API for declaring field types on a `Configurable`'s output
- [ ] Implement validation call in `NodeExecutionContext._put` (zero-cost when no schema declared)
- [ ] Implement `ValidationWarning` emission path (structured log, not raised exception, by default)
- [ ] Implement `bonobo.metrics` module with `EdgeMetrics` namedtuple and `GraphMetrics` aggregate
- [ ] Expose metrics via `GraphExecutionContext.metrics` property
- [ ] Add `bonobo inspect --metrics` CLI subcommand
- [ ] Document with end-to-end example

**Relevant Context:**
- Phase 2e (async strategy rewrite) is a prerequisite for 4a
- [`bonobo/structs/graphs.py`](bonobo/structs/graphs.py) — edge metadata extension point
- [`bonobo/execution/contexts/node.py`](bonobo/execution/contexts/node.py) — `_put` method is the natural validation hook
- [`bonobo/errors.py`](bonobo/errors.py) — extend with `ValidationWarning`
- [`bonobo/_api.py`](bonobo/_api.py) — new exports: `run_async`, `EdgeMetrics`, `GraphMetrics`

**Status:** `[ ] pending`

---

## Appendix — Key Files Quick Reference

| File | Role |
|---|---|
| [`bonobo/_api.py`](bonobo/_api.py) | Public API surface — all exports |
| [`bonobo/config/configurables.py`](bonobo/config/configurables.py) | `ConfigurableMeta`, `PartiallyConfigured`, `Configurable` |
| [`bonobo/config/options.py`](bonobo/config/options.py) | `Option`, `RemovedOption`, `RenamedOption`, `Method` |
| [`bonobo/config/processors.py`](bonobo/config/processors.py) | `ContextProcessor`, `ContextCurrifier` |
| [`bonobo/config/services.py`](bonobo/config/services.py) | `Service`, `Container`, `Exclusive`, `create_container` |
| [`bonobo/structs/graphs.py`](bonobo/structs/graphs.py) | `Graph`, `GraphCursor`, `PartialGraph`, `GraphRange` |
| [`bonobo/structs/inputs.py`](bonobo/structs/inputs.py) | `Input`, `AioInput`, `Readable`, `Writable` |
| [`bonobo/constants.py`](bonobo/constants.py) | `BEGIN`, `END`, `NOT_MODIFIED`, `EMPTY`, `TICK_PERIOD` |
| [`bonobo/errors.py`](bonobo/errors.py) | Full exception hierarchy |
| [`bonobo/execution/contexts/base.py`](bonobo/execution/contexts/base.py) | `Lifecycle`, `BaseContext` |
| [`bonobo/execution/contexts/node.py`](bonobo/execution/contexts/node.py) | `NodeExecutionContext` |
| [`bonobo/execution/contexts/graph.py`](bonobo/execution/contexts/graph.py) | `GraphExecutionContext`, `AsyncGraphExecutionContext` |
| [`bonobo/execution/strategies/executor.py`](bonobo/execution/strategies/executor.py) | `ThreadPoolExecutorStrategy`, `AsyncThreadPoolExecutorStrategy` |
| [`bonobo/execution/strategies/naive.py`](bonobo/execution/strategies/naive.py) | `NaiveStrategy` |
| [`bonobo/util/pkgs.py`](bonobo/util/pkgs.py) | `bonobo_packages` registry (uses `pkg_resources`) |
| [`bonobo/commands/run.py`](bonobo/commands/run.py) | `RunCommand`, broken `pip.main` usage |
| [`setup.py`](setup.py) | Medikit-generated; to be replaced |
