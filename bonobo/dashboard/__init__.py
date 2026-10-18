"""
bonobo.dashboard
================

FastAPI-based live metrics dashboard for Bonobo ETL pipelines.

Usage::

    python -m bonobo.dashboard

This starts a web server (default port 8000, or ``$PORT``) that:

* Serves an HTML dashboard at ``GET /``
* Streams per-node metrics via Server-Sent Events at ``GET /events``
* Exposes a health check at ``GET /health``

The dashboard drives a self-contained demo pipeline:

    :class:`~bonobo.nodes.streaming.FileTailReader` →
    :class:`~bonobo.nodes.quality.DataQualityCheck` →
    :class:`~bonobo.nodes.streaming.FileAppendWriter`

Lines are seeded into the input file at startup so the demo is live from
the first request, without requiring any pre-existing files on disk.
"""
