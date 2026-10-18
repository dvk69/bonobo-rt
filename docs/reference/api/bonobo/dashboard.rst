Dashboard
=========

The **Bonobo Live Dashboard** is a FastAPI-based web application that exposes
real-time pipeline metrics via a browser UI and a Server-Sent Events (SSE)
stream.

.. contents:: On this page
   :local:
   :depth: 2

Overview
--------

The dashboard drives a self-contained demo pipeline:

.. code-block::

    FileTailReader → DataQualityCheck → FileAppendWriter

Lines are seeded into the input file at server startup and a background
thread appends new events every five seconds, so the metrics counter keeps
ticking without any manual intervention.

Starting the dashboard
----------------------

.. code-block:: bash

    python -m bonobo.dashboard

The server reads the ``PORT`` environment variable (default ``8000``):

.. code-block:: bash

    PORT=5000 python -m bonobo.dashboard

HTTP endpoints
--------------

``GET /``
    Serves the live HTML dashboard.  Metrics update in place via
    EventSource without any page reload.

``GET /events``
    Server-Sent Events stream.  Each event carries a JSON object keyed by
    node name::

        data: {"FileTailReader": {"in": 0, "out": 12, "err": 0, "warn": 0},
               "DataQualityCheck": {"in": 12, "out": 12, "err": 0, "warn": 0,
                                    "violations": {"null_empty[0]": 2}},
               "FileAppendWriter": {"in": 12, "out": 0, "err": 0, "warn": 0}}

    The stream opens with ``retry: 3000`` so EventSource clients
    reconnect within three seconds after a spin-down or restart.
    A comment-only ``": ping"`` heartbeat is emitted every ~25 s to
    prevent proxy timeouts.

``GET /health``
    Always returns ``{"status": "ok"}`` with HTTP 200.  Used by the
    keep-warm GitHub Actions schedule.

Render deployment
-----------------

``render.yaml`` at the repo root configures the service as a **free** Render
web service.  Push to your repo, connect it on Render, and the build command
``pip install -e ".[dev]"`` plus the start command
``python -m bonobo.dashboard`` take care of the rest.

The ``PORT`` environment variable is set to ``8000`` in ``render.yaml``; Render
overrides it automatically when the service is bound to a public URL.

Because Render spins free services down after 15 minutes of inactivity,
``.github/workflows/keep-warm.yml`` pings ``/health`` every 10 minutes via a
GitHub Actions cron schedule — no paid Render cron required.

Module reference
----------------

.. automodule:: bonobo.dashboard.app
   :members:
   :undoc-members:
   :show-inheritance:
