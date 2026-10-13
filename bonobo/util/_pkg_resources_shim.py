"""
Shim that installs a minimal ``pkg_resources`` stub into ``sys.modules`` when
the real package is absent (setuptools >= 81 removed it).

WHY THIS EXISTS
---------------
``fs==2.4.16`` (the last release; project abandoned in 2021) calls
``__import__("pkg_resources").declare_namespace(__name__)`` at import time in
``fs/__init__.py`` and ``fs/opener/__init__.py``, and uses
``pkg_resources.iter_entry_points("fs.opener")`` in ``fs/opener/registry.py``.
On Python 3.12+ with setuptools >= 81, ``pkg_resources`` is no longer shipped,
so any import of ``fs`` raises ``ModuleNotFoundError``.

WHAT THE SHIM DOES
------------------
* ``declare_namespace(name)`` — no-op.  Python 3.3+ implicit namespace
  packages handle everything ``pkg_resources.declare_namespace`` used to do.
* ``iter_entry_points(group, name=None)`` — delegates to
  ``importlib.metadata.entry_points`` (stdlib since 3.9) and returns the
  matching ``EntryPoint`` objects.

EXIT PLAN
---------
Remove this file (and the call-site in ``bonobo/_api.py``) once ``fs`` is
replaced with a maintained alternative (tracked in MODERNIZATION_PLAN.md,
Slice 3+).
"""

import sys
import types
from importlib.metadata import entry_points


def ensure_pkg_resources_shim() -> bool:
    """Install the pkg_resources shim if the real package is unavailable.

    Returns True when the shim was installed, False when pkg_resources already
    exists and no action was taken.
    """
    try:
        import pkg_resources  # noqa: F401 — probe only

        return False  # real package present; nothing to do
    except ImportError:
        pass

    mod = types.ModuleType("pkg_resources")
    mod.__doc__ = "pkg_resources compatibility shim — see bonobo/util/_pkg_resources_shim.py"

    def declare_namespace(name: str) -> None:  # noqa: ANN001
        """No-op: Python 3.3+ implicit namespace packages supersede this."""

    def iter_entry_points(group: str, name: str = None):
        """Yield EntryPoint objects for *group*, optionally filtered by *name*."""
        eps = entry_points(group=group)
        if name is not None:
            eps = [ep for ep in eps if ep.name == name]
        return iter(eps)

    mod.declare_namespace = declare_namespace
    mod.iter_entry_points = iter_entry_points

    sys.modules["pkg_resources"] = mod
    return True
