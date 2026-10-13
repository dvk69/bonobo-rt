.. _migrate-0.7-to-0.8:

Migrating from 0.7.x to 0.8.0
==============================

This page summarises every breaking and behavioral change introduced in the
0.8.0 modernisation work. See ``CHANGELOG.md`` in the repository root for the
full narrative.


Python version
--------------

**Python ≥ 3.10 is now required.** Python 3.5–3.9 are no longer supported or
tested. Drop the ``python_requires`` floor in your own project metadata if you
were targeting those older versions.


Packaging
---------

The project no longer uses `Medikit <https://github.com/python-medikit/medikit>`_.
``setup.py``, ``setup.cfg``, and ``Projectfile`` are gone; everything is
described in ``pyproject.toml``.

If you consume Bonobo as a library, nothing changes. If you were patching or
extending the build toolchain, update your workflow to use the standard
``pip install -e ".[dev]"`` editable install.


Removed dependency: ``cached-property``
----------------------------------------

The third-party ``cached-property`` package has been removed. If you imported
it through Bonobo's dependencies, add it explicitly to your own project or
switch to ``functools.cached_property`` (available since Python 3.8).


Updated dependency lower bounds
--------------------------------

+------------------+-----------+-----------+
| Package          | Old bound | New bound |
+==================+===========+===========+
| graphviz         | >=0.8     | >=0.20    |
+------------------+-----------+-----------+
| jinja2           | ~=2.9     | >=3.0     |
+------------------+-----------+-----------+
| stevedore        | ~=1.27    | >=5       |
+------------------+-----------+-----------+
| psutil           | ~=5.4     | >=6       |
+------------------+-----------+-----------+
| packaging        | ~=19.0    | >=24      |
+------------------+-----------+-----------+
| python-slugify   | ~=1.2     | >=8       |
+------------------+-----------+-----------+


graphviz 0.20
-------------

``Graph._repr_html_()`` previously called ``graphviz.Digraph._repr_svg_()``.
That method was removed in graphviz 0.20; it is now ``_repr_image_svg_xml()``.
If you subclassed ``Graph`` and called ``_repr_svg_()`` directly, update to
``_repr_image_svg_xml()``.


jinja2 3.x
----------

``InitCommand.create_file_from_template()`` now passes
``autoescape=False, keep_trailing_newline=True`` to ``jinja2.Environment``
explicitly. The behavior for ``autoescape`` is unchanged (always ``False`` —
templates produce Python source, not HTML). The ``keep_trailing_newline``
change means generated ``.py`` files now correctly end with a trailing newline.


``pkg_resources`` removed from bonobo source
---------------------------------------------

All internal uses of ``pkg_resources`` have been replaced with
``importlib.metadata`` (stdlib). A thin compatibility shim
(``bonobo.util._pkg_resources_shim``) is installed at import time via
``bonobo._api`` to satisfy the abandoned ``fs==2.4.16`` library, which calls
``pkg_resources.declare_namespace()`` at import time.

If you were relying on ``bonobo.util.pkgs.bonobo_packages`` values being
``pkg_resources.Distribution`` objects, they are now
``importlib.metadata.Distribution`` objects. The key API difference:

- **Old:** ``dist.location`` (string path)
- **New:** ``str(dist.locate_file("."))`` (equivalent path via stdlib API)


Executor race condition
-----------------------

A race in ``ExecutorStrategy`` could cause
``RuntimeError: This context cannot be stopped as it never started``
on fast machines or Python 3.12. This is now fixed. No API changes — the fix
is internal to the execution engine.


``bonobo run --install`` / ``_install_requirements``
-----------------------------------------------------

The ``--install`` flag on ``bonobo run`` now installs dependencies via
``subprocess.run([sys.executable, "-m", "pip", "install", ...])`` instead of
the long-removed ``pip.main()`` API. Behavior is unchanged.
