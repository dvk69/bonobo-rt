"""
Entry point for ``python -m bonobo.dashboard``.

Starts the FastAPI dashboard server, reading the port from the ``PORT``
environment variable (default 8000) to satisfy Render's free web service
requirements.

Example::

    python -m bonobo.dashboard
    # → http://localhost:8000/

    PORT=5000 python -m bonobo.dashboard
    # → http://localhost:5000/
"""

import os

import uvicorn

from bonobo.dashboard.app import app, start_demo_pipeline

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    # Seed and start the demo pipeline before accepting requests.
    start_demo_pipeline()

    uvicorn.run(app, host="0.0.0.0", port=port)
