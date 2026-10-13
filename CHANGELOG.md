# Changelog

All notable changes to Bonobo are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — 0.8.0

### Breaking changes

- **Python ≥ 3.10 required.** Python 3.5–3.9 are no longer supported or
  tested. The CI matrix covers 3.10, 3.11, and 3.12.

- **`cached-property` removed as a dependency.** The third-party
  `cached-property` package was replaced by the stdlib `functools.cached_property`
  (available since Python 3.8). Projects that `import cached_property` directly
  must update their imports.

- **`graphviz >= 0.20` required.** The private `graphviz.dot.Digraph` import
  path was removed in graphviz 0.20; `bonobo` now imports `Digraph` from the
  top-level `graphviz` package. `Graph._repr_html_()` was updated to call
  `_repr_image_svg_xml()` (replaces the removed `_repr_svg_()` method).

- **`jinja2 >= 3.0` required.** The `InitCommand` `Environment` is now
  constructed with `autoescape=False, keep_trailing_newline=True` explicitly.
  The latter ensures generated `.py` files always end with a trailing newline
  (jinja2 3.x strips it by default).

- **`stevedore >= 5`, `psutil >= 6`, `packaging >= 24`,
  `python-slugify >= 8` required.** Lower bounds were advanced to
  currently-maintained releases.

### Migration: `pkg_resources` removed from bonobo source

All first-party `pkg_resources` usage inside bonobo has been replaced with
`importlib.metadata` (stdlib since Python 3.8):

- `bonobo/util/pkgs.py` — `pkg_resources.working_set` → `packages_distributions()` + `distribution()`
- `bonobo/commands/version.py` — `mod.__version__` lookup now uses the installed distribution object
- `tests/commands/test_clibasics.py` — `iter_entry_points` → `importlib.metadata.entry_points(group=…)`

A compatibility shim (`bonobo/util/_pkg_resources_shim.py`) is installed at
import time via `bonobo/_api.py` to bridge the `fs==2.4.16` library, which
calls `pkg_resources.declare_namespace()` and `iter_entry_points()` at import
time. The shim is a no-op when `pkg_resources` is present (Python ≤ 3.11 with
setuptools < 81); on Python 3.12+ with setuptools ≥ 81 (where `pkg_resources`
was removed), the shim provides the two required APIs via `importlib.metadata`.
The shim includes an exit plan comment — it will be removed when `fs` is
replaced (tracked in MODERNIZATION_PLAN.md Phase 4+).

### Executor race fix (two-layer defence)

A race condition in `ExecutorStrategy.execute()` caused
`RuntimeError: This context cannot be stopped as it never started` on
Python 3.12, making the entire `tests/commands/test_run_environ.py` suite
flaky or deterministically failing.

Root cause: the main thread's `while context.alive` loop could exit before a
submitted worker thread had called `node.start()`. `GraphExecutionContext.stop()`
then called `stop()` on a never-started node, which violated the `Lifecycle`
contract.

Two-layer fix:
1. `ExecutorStrategy.execute()` now calls `concurrent.futures.wait(futures)`
   after the alive-loop, guaranteeing all worker threads have finished before
   `context.stop()` is called.
2. `GraphExecutionContext.stop()` skips `node_context.stop()` for any node
   where `not node_context.started`. The `Lifecycle.stop()` guard contract is
   preserved — it still raises `RuntimeError` when called directly on an
   unstarted context (as tested by `test_node_lifecycle_natural`).

### `_install_requirements` — subprocess replaces `pip.main`

`bonobo/commands/run.py`'s `_install_requirements()` helper replaced the
long-broken `pip.main(["install", ...])` call (removed from pip's public API
in pip 10) with `subprocess.run([sys.executable, "-m", "pip", "install", ...])`.
The `pkg_resources` reload hack following the old call was also removed; only
the `importlib.reload(site)` call was kept to pick up newly installed `.pth`
files.

### Async strategy — `get_event_loop` deprecation fix

`AsyncThreadPoolExecutorStrategy` (experimental, alpha-gated) no longer calls
`asyncio.get_event_loop()` at access time. A private event loop is created with
`asyncio.new_event_loop()` in `__init__` and stored as `self._loop`. The old
call emitted `DeprecationWarning` on Python 3.10+ when no loop was running.
A full async redesign is deferred to Phase 4 (see MODERNIZATION_PLAN.md).

### Packaging modernisation

- `setup.py`, `setup.cfg`, and `Projectfile` (medikit) have been removed.
  The project is now fully described by `pyproject.toml` using
  `setuptools.build_meta`.
- The `Makefile` was stripped of all medikit-generated targets. The remaining
  hand-written targets are `install-dev`, `test`, `clean`, `format`, and `help`.
- CI moved from Travis CI + AppVeyor + Wercker to GitHub Actions
  (`.github/workflows/ci.yml`), running the full test suite across Python
  3.10/3.11/3.12 on ubuntu-latest and macos-latest.
- ReadTheDocs configuration updated from the legacy v1 `.yml` to the v2
  `readthedocs.yaml` format.
- A `Dockerfile` and `.dockerignore` are provided for reproducible dev
  environments and containerised test runs.

### Stdlib modernisation

- `collections.OrderedDict` → `dict` in `bonobo/util/bags.py` and
  `bonobo/nodes/io/json.py`. Plain `dict` preserves insertion order since
  Python 3.7; the change is a no-op for all consumers.

---

## [0.7.0rc2] — 2019-07-20 (last Medikit-managed release)

See [git history](https://github.com/python-bonobo/bonobo/commits/develop)
for changes prior to 0.8.0.
