# AGENTS.md — Agent (Coding) Mode

This file provides guidance to agents when working with code in this repository.

## Critical coding rules

- **Do NOT edit `Makefile`** — it is auto-generated from `Projectfile` by medikit. Edit `Projectfile` and run `make update` to regenerate.
- **`Configurable.__new__` returns `PartiallyConfigured` when options are missing** — this is intentional. Tests that assert on partial instances must use `inspect_node(instance).partial`, not `isinstance` checks.
- **`Option` descriptors store values in `inst._options_values`**, not as plain instance attributes. Do not bypass the descriptor (e.g., no `object.__setattr__`).
- **`ContextProcessor` must yield exactly once** — yielding more raises `RuntimeError` in teardown. The generator contract is: setup code → `yield value` → teardown code.
- **Transformations must be stateless** — persistent state belongs exclusively in `ContextProcessor` yielded values (e.g., `ValueHolder`).
- **`UnrecoverableError` (and its subclasses) stops the entire workflow**; plain exceptions only skip the current input row.
- **`isort` treats `mondrian` and `whistle` as third-party** — don't place them in stdlib or first-party sections. The `known_third_party` list is in `.isort.cfg`.
- **Black line length is 120** — do not use the default 88.
- **Test timeout**: any test exercising actual graph execution must be decorated `@pytest.mark.timeout(2)`.
- **`bonobo/examples/` and `bonobo/ext/` are excluded from coverage** — don't add coverage pragmas there expecting them to count.
