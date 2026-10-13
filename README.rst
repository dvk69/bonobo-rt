==========
🐵  bonobo
==========

Data-processing for humans.

.. image:: https://img.shields.io/pypi/v/bonobo.svg
    :target: https://pypi.python.org/pypi/bonobo
    :alt: PyPI

.. image:: https://img.shields.io/pypi/pyversions/bonobo.svg
    :target: https://pypi.python.org/pypi/bonobo
    :alt: Versions

.. image:: https://readthedocs.org/projects/bonobo/badge/?version=master
    :target: http://docs.bonobo-project.org/
    :alt: Documentation

.. image:: https://github.com/python-bonobo/bonobo/actions/workflows/ci.yml/badge.svg
    :target: https://github.com/python-bonobo/bonobo/actions/workflows/ci.yml
    :alt: CI

Bonobo is an extract-transform-load framework for **Python 3.10+**.

Bonobo uses plain old python objects (functions, generators and iterators), allows them to be linked together in a
directed graph, and then executed using a parallelized strategy, without having to worry about the underlying
complexity.

Developers can focus on writing simple and atomic operations that are easy to unit-test by design, while the
framework handles applying them concurrently to rows of data.

One thing to note: write pure transformations and you'll be safe.

Bonobo is a rewrite of the **rdc.etl** python 2.7 tool that ran millions of transformations per day on production.

----

*Bonobo is under active modernization. Please allow us to reach 1.0 stability and accept our sincere apologies for
anything we break in the process (feel free to open issues).*

----

Quick start
:::::::::::

Install:

.. code-block:: shell-session

    $ pip install --upgrade bonobo

Create a job:

.. code-block:: shell-session

    $ bonobo init my-etl.py

Run it:

.. code-block:: shell-session

    $ python my-etl.py

See :doc:`docs/install` for editable-install and developer setup instructions.

Requirements
::::::::::::

- Python **≥ 3.10**
- See ``pyproject.toml`` for the full dependency list.

Links
:::::

- Homepage: https://www.bonobo-project.org/
- Documentation: http://docs.bonobo-project.org/
- Issues: https://github.com/python-bonobo/bonobo/issues
- `CHANGELOG <CHANGELOG.md>`_
- `Modernization plan <MODERNIZATION_PLAN.md>`_

----

Made with ♥ by `Romain Dorgueil <https://twitter.com/rdorgueil>`_ and `contributors <https://github.com/python-bonobo/bonobo/graphs/contributors>`_.

.. image:: https://img.shields.io/pypi/l/bonobo.svg
    :target: https://pypi.python.org/pypi/bonobo
    :alt: License
