# AGENTS.md — Ask (Documentation) Mode

This file provides guidance to agents when working with code in this repository.

## Non-obvious documentation context

- **Stable public API** is defined in [`bonobo/_api.py`](../../bonobo/_api.py) and re-exported via `bonobo/__init__.py` using `ApiHelper.__all__`. Any symbol not registered through `ApiHelper.register*` is considered internal even if importable.
- **`bonobo.config`** is a second stable public namespace (separate from the root package). Users import `Configurable`, `Option`, `ContextProcessor`, `Service`, `Method`, etc. from `bonobo.config`, not from `bonobo` directly.
- **`Makefile` is generated** — answers about build commands should reference `Projectfile` as the source of truth, not `Makefile` which is a derived artifact.
- **`bonobo/contrib/`** contains optional integrations (e.g., Jupyter). These are not covered by default coverage and have separate optional install groups (`[jupyter]`).
- **`bonobo/ext/`** is for extension points and is also excluded from default test coverage.
- **Service names must be valid Python dotted identifiers** (validated by regex in [`bonobo/config/services.py`](../../bonobo/config/services.py)). This is not documented anywhere obvious.
- **`NOT_MODIFIED`** is an `UnchangedEnvelope` instance (not `None`, not a bool) — returning it passes the input tuple through to downstream nodes unchanged.
