"""
bonobo.dashboard.app
====================

FastAPI application exposing a live metrics dashboard for Bonobo pipelines.

Public surface
--------------
``app`` — the FastAPI application object (importable for ASGI servers).
``start_demo_pipeline()`` — starts the background demo graph and returns the
    ``GraphExecutionContext`` so the SSE endpoint can poll metrics.
"""

import asyncio
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import bonobo
from bonobo.nodes.quality import DataQualityCheck
from bonobo.nodes.streaming import FileAppendWriter, FileTailReader
from bonobo.structs.graphs import Graph

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Bonobo Live Dashboard", version="0.1.0")

# Global state — set by start_demo_pipeline() at startup.
_demo_ctx = None
_demo_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Demo pipeline helpers
# ---------------------------------------------------------------------------

_SEED_LINES = [
    '{"event": "order_created", "amount": 42.5, "user_id": 1001}',
    '{"event": "order_shipped", "amount": 0, "user_id": 1002}',
    '{"event": "order_created", "amount": null, "user_id": null}',
    '{"event": "payment_failed", "amount": -9.99, "user_id": 1003}',
    '{"event": "order_created", "amount": 120.0, "user_id": 1004}',
    '{"event": "signup",         "amount": "",    "user_id": 1005}',
    '{"event": "order_refunded", "amount": 30.0,  "user_id": 1006}',
    '{"event": "order_created",  "amount": 5.0,   "user_id": 1007}',
]

# Temp-dir references kept alive for the process lifetime.
_tmp_dir_obj = None
_input_path: str = ""
_output_path: str = ""


def _seed_input_file(path: str) -> None:
    """Write seed lines to *path* so the demo has something to process."""
    with open(path, "w", encoding="utf-8") as fh:
        for line in _SEED_LINES:
            fh.write(line + "\n")
            fh.flush()


def _append_loop(path: str, stop_event: threading.Event) -> None:
    """Background thread: appends a new event every 5 s so the dashboard
    shows live rows even after the initial seed is consumed."""
    import random

    amounts = [12.0, 99.5, 0.0, -1.0, 200.0, None, ""]
    users = [1001, 1002, None, 1004, 1005]
    i = 0
    while not stop_event.wait(5):
        payload = json.dumps(
            {
                "event": "live_tick",
                "amount": random.choice(amounts),
                "user_id": random.choice(users),
                "seq": i,
            }
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
        i += 1


def _parse_line(line: str):
    """Parse a JSON log line into an (event, amount, user_id) tuple.

    Unparseable lines are silently dropped (generator yields nothing),
    so a malformed row never crashes the pipeline.
    """
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return  # drop unparseable lines
    yield (
        obj.get("event", ""),
        obj.get("amount"),
        obj.get("user_id"),
    )


def start_demo_pipeline() -> None:
    """Initialise the demo graph and start it in background threads.

    Safe to call multiple times — subsequent calls are no-ops.
    The graph runs in a daemon thread so it does not block the ASGI server.
    """
    global _demo_ctx, _tmp_dir_obj, _input_path, _output_path

    with _demo_lock:
        if _demo_ctx is not None:
            return

        # Create temp files that survive for the process lifetime.
        _tmp_dir_obj = tempfile.TemporaryDirectory()
        tmp = Path(_tmp_dir_obj.name)
        _input_path = str(tmp / "input.log")
        _output_path = str(tmp / "output.jsonl")

        # Pre-create both files so the nodes can open them immediately.
        Path(_input_path).write_text("", encoding="utf-8")
        Path(_output_path).write_text("", encoding="utf-8")

        # Seed the input file before the reader seeks to EOF.
        _seed_input_file(_input_path)

        checker = DataQualityCheck(
            # Negative amounts (e.g. -9.99) violate this range.
            # Null/empty amounts and null user_ids are caught by the built-in
            # null/empty check on all fields.
            value_ranges={1: (0, 10000)},
        )

        graph = Graph(
            FileTailReader(_input_path, poll_interval=0.25),
            _parse_line,
            checker,
            FileAppendWriter(_output_path),
        )

        # Start the graph in background threads and keep a reference to the
        # GraphExecutionContext so the SSE endpoint can poll its metrics.
        from concurrent.futures import ThreadPoolExecutor
        from bonobo.constants import BEGIN, END
        from bonobo.execution.contexts.graph import GraphExecutionContext

        ctx = GraphExecutionContext(graph, services=None, plugins=[])
        _demo_ctx = ctx

        def _run_graph():
            """Drive the graph until it stops naturally (or the process exits)."""
            executor = ThreadPoolExecutor(max_workers=len(graph))
            futures = []

            def _make_runner(node):
                import functools

                @functools.wraps(node)
                def _runner():
                    try:
                        with node:
                            node.loop()
                    except Exception:
                        pass

                return _runner

            ctx.write(BEGIN, (), END)
            ctx.start(lambda node: futures.append(executor.submit(_make_runner(node))))

            # Tick until all nodes are done (FileTailReader runs until stopped).
            import time as _time

            while ctx.alive:
                ctx.tick()

            for f in futures:
                f.result()
            ctx.stop()
            executor.shutdown(wait=False)

        graph_thread = threading.Thread(target=_run_graph, daemon=True)
        graph_thread.start()

        # Background appender keeps the stream alive.
        stop_ev = threading.Event()
        t = threading.Thread(target=_append_loop, args=(_input_path, stop_ev), daemon=True)
        t.start()


def get_demo_ctx():
    """Return the running GraphExecutionContext, starting the demo if needed."""
    if _demo_ctx is None:
        start_demo_pipeline()
    return _demo_ctx


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    """Simple health check — always returns HTTP 200."""
    return JSONResponse({"status": "ok"})


@app.get("/events")
async def events():
    """Server-Sent Events stream of metrics snapshots.

    Emits a ``retry: 3000`` directive on connect so EventSource clients
    reconnect within 3 s after a proxy or spin-down disconnect.

    Sends a comment-only heartbeat (``": ping"``) every ~25 s so proxies
    that would otherwise close idle connections leave the stream open.
    """
    ctx = get_demo_ctx()

    async def generate():
        # Reconnect hint: clients will retry after 3 s.
        yield "retry: 3000\n\n"

        last_heartbeat = time.monotonic()
        try:
            while True:
                metrics = ctx.get_metrics() if ctx is not None else {}
                data = json.dumps(metrics)
                yield f"data: {data}\n\n"

                # Heartbeat every 25 s to keep proxies happy.
                now = time.monotonic()
                if now - last_heartbeat >= 25:
                    yield ": ping\n\n"
                    last_heartbeat = now

                await asyncio.sleep(1)
        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected — exit cleanly.
            return

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the live dashboard HTML page."""
    html = _build_dashboard_html()
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

_DASHBOARD_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Bonobo Live Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      background: #f7f8fa;
      color: #1f2328;
    }}
    header {{
      background: #1f2328;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
    #status {{
      margin-left: auto;
      font-size: 12px;
      padding: 3px 8px;
      border-radius: 12px;
      background: #57606a;
      color: #fff;
    }}
    #status.connected {{ background: #1a7f37; }}
    #status.error {{ background: #cf222e; }}
    main {{
      max-width: 860px;
      margin: 24px auto;
      padding: 0 16px;
    }}
    h2 {{
      font-size: 15px;
      font-weight: 600;
      margin: 0 0 12px;
      color: #57606a;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    #grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 16px;
    }}
    .card-title {{
      font-weight: 600;
      font-size: 13px;
      margin-bottom: 10px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: #3b82d4;
    }}
    .counters {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
    }}
    .counter {{
      display: flex;
      flex-direction: column;
    }}
    .counter-label {{
      font-size: 11px;
      color: #57606a;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .counter-value {{
      font-size: 22px;
      font-weight: 700;
      color: #1f2328;
    }}
    .counter-value.err  {{ color: #cf222e; }}
    .counter-value.warn {{ color: #bf8700; }}
    .violations {{
      margin-top: 10px;
      border-top: 1px solid #e5e7eb;
      padding-top: 8px;
      font-size: 12px;
    }}
    .violations summary {{
      cursor: pointer;
      color: #57606a;
    }}
    .violations pre {{
      margin: 6px 0 0;
      background: #f7f8fa;
      padding: 6px 8px;
      border-radius: 4px;
      overflow: auto;
      max-height: 120px;
      font-size: 11px;
    }}
    #last-update {{
      font-size: 12px;
      color: #57606a;
      margin-top: 16px;
      text-align: right;
    }}
    footer {{
      margin-top: 48px;
      padding: 16px;
      text-align: center;
      font-size: 12px;
      color: #57606a;
      border-top: 1px solid #e5e7eb;
    }}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F34C; Bonobo Live Dashboard</h1>
    <span id="status">Connecting&hellip;</span>
  </header>
  <main>
    <h2>Pipeline Nodes</h2>
    <div id="grid"><p style="color:#57606a">Waiting for first metrics snapshot&hellip;</p></div>
    <p id="last-update"></p>
  </main>
  <footer>Made with IBM Bob</footer>

  <script>
    const grid = document.getElementById('grid');
    const statusEl = document.getElementById('status');
    const lastUpdate = document.getElementById('last-update');

    function fmt(n) {{ return (n == null) ? '—' : n; }}

    function renderMetrics(metrics) {{
      const nodes = Object.entries(metrics);
      if (nodes.length === 0) {{
        grid.innerHTML = '<p style="color:#57606a">No nodes yet.</p>';
        return;
      }}
      grid.innerHTML = nodes.map(([name, m]) => {{
        const vKeys = m.violations ? Object.keys(m.violations) : [];
        const vSection = vKeys.length ? `
          <details class="violations">
            <summary>Violations (${{vKeys.length}} type${{vKeys.length>1?'s':''}})</summary>
            <pre>${{JSON.stringify(m.violations, null, 2)}}</pre>
          </details>` : '';
        return `<div class="card">
          <div class="card-title" title="${{name}}">${{name}}</div>
          <div class="counters">
            <div class="counter">
              <span class="counter-label">In</span>
              <span class="counter-value">${{fmt(m['in'])}}</span>
            </div>
            <div class="counter">
              <span class="counter-label">Out</span>
              <span class="counter-value">${{fmt(m['out'])}}</span>
            </div>
            <div class="counter">
              <span class="counter-label">Errors</span>
              <span class="counter-value err">${{fmt(m['err'])}}</span>
            </div>
            <div class="counter">
              <span class="counter-label">Warnings</span>
              <span class="counter-value warn">${{fmt(m['warn'])}}</span>
            </div>
          </div>
          ${{vSection}}
        </div>`;
      }}).join('');
    }}

    const es = new EventSource('/events');

    es.addEventListener('open', () => {{
      statusEl.textContent = 'Connected';
      statusEl.className = 'connected';
    }});

    es.addEventListener('message', (e) => {{
      try {{
        const metrics = JSON.parse(e.data);
        renderMetrics(metrics);
        lastUpdate.textContent = 'Last update: ' + new Date().toLocaleTimeString();
      }} catch(err) {{
        console.error('Parse error', err);
      }}
    }});

    es.addEventListener('error', () => {{
      statusEl.textContent = 'Reconnecting\u2026';
      statusEl.className = 'error';
    }});
  </script>
</body>
</html>
"""


def _build_dashboard_html() -> str:
    return _DASHBOARD_HTML_TEMPLATE
