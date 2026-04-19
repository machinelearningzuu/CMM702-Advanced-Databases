"""
FastAPI backend for the Click Logging System.
Receives tap data from the frontend and stores it in Firebase Firestore.
"""

import json
import logging
import traceback

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from firebase_config import initialize_firebase
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

# ---------------------------------------------------------------------------
# Logging — send INFO+ to stdout so Render's log viewer picks it up
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("clicklogs")

app = FastAPI(title="Click Logging API", version="1.0.0")

# Allow CORS for GitHub Pages and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Initialise Firestore at startup. If credentials are bad, fail loud and early
# so the problem shows up in Render's deploy logs rather than as a silent 500
# on the first request.
# ---------------------------------------------------------------------------
try:
    db = initialize_firebase()
    logger.info("Firestore client initialised successfully")
except Exception as exc:  # noqa: BLE001 — log anything so deploy logs show it
    logger.error("Firestore initialisation failed: %s", exc)
    logger.error(traceback.format_exc())
    raise


@app.get("/")
def root():
    return {"status": "ok", "message": "Click Logging API is running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Live HTML dashboard — visual overview of the tap-log collection.

    Uses Chart.js from CDN for bar charts; everything else is inline CSS.
    Auto-refreshes every 30 seconds so it stays current as new sessions
    stream in. Designed to be screenshot-friendly for the Q2 write-up.
    """
    try:
        from collections import defaultdict

        docs = [d.to_dict() for d in db.collection("tap_logs").stream()]
        total_taps = len(docs)

        # Per-session breakdown
        by_session = defaultdict(list)
        for d in docs:
            by_session[d.get("sessionId", "unknown")].append(d)

        # Filter real sessions (>=25 taps) from incidental test requests
        real_sessions = {
            sid: taps for sid, taps in by_session.items() if len(taps) >= 25
        }
        completed_both = sum(
            1 for taps in real_sessions.values()
            if len({t.get("interfaceSequence") for t in taps}) >= 2
        )

        # Platform aggregates
        by_platform = defaultdict(list)
        for d in docs:
            by_platform[d.get("platform", "unknown")].append(d.get("duration", 0))
        platform_stats = {
            p: {
                "count": len(v),
                "mean": round(sum(v) / len(v), 2) if v else 0,
                "min": min(v) if v else 0,
                "max": max(v) if v else 0,
            } for p, v in sorted(by_platform.items())
        }

        # Interface aggregates
        by_interface = defaultdict(list)
        for d in docs:
            by_interface[d.get("interface", "unknown")].append(d.get("duration", 0))
        interface_stats = {
            k: {
                "count": len(v),
                "mean": round(sum(v) / len(v), 2) if v else 0,
            } for k, v in sorted(by_interface.items())
        }

        # Per-session rows for the table
        session_rows = []
        for sid, taps in sorted(real_sessions.items()):
            platforms = sorted({t.get("platform") for t in taps})
            seqs = sorted({t.get("interfaceSequence") for t in taps if t.get("interfaceSequence")})
            durations = [t.get("duration", 0) for t in taps]
            session_rows.append({
                "sid": sid,
                "platform": ", ".join(platforms),
                "taps": len(taps),
                "seqs": ",".join(str(s) for s in seqs),
                "mean": round(sum(durations) / len(durations), 1) if durations else 0,
                "completed": len(seqs) >= 2,
            })

        # Build rows HTML
        rows_html = "\n".join(
            f'''<tr>
              <td class="sid">{r["sid"]}</td>
              <td><span class="pill pill-{r["platform"]}">{r["platform"]}</span></td>
              <td class="num">{r["taps"]}</td>
              <td>{r["seqs"]}</td>
              <td class="num">{r["mean"]} ms</td>
              <td>{"✅" if r["completed"] else "⚠️"}</td>
            </tr>'''
            for r in session_rows
        )

        # Platform chart data
        platform_labels = list(platform_stats.keys())
        platform_means = [platform_stats[p]["mean"] for p in platform_labels]
        platform_counts = [platform_stats[p]["count"] for p in platform_labels]

        # Interface chart data
        interface_labels = list(interface_stats.keys())
        interface_means = [interface_stats[k]["mean"] for k in interface_labels]
        interface_counts = [interface_stats[k]["count"] for k in interface_labels]

        completion_rate = (
            round(100 * completed_both / len(real_sessions), 1)
            if real_sessions else 0
        )

        html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CMM702 Click-Log Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    margin: 0;
    padding: 24px;
    line-height: 1.5;
  }}
  h1 {{ margin: 0 0 4px 0; font-weight: 600; letter-spacing: -0.02em; }}
  .subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 32px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .metric {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px;
  }}
  .metric .label {{
    color: #94a3b8;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 8px;
  }}
  .metric .value {{
    font-size: 40px;
    font-weight: 700;
    line-height: 1;
    color: #f8fafc;
  }}
  .metric .unit {{ color: #64748b; font-size: 16px; font-weight: 400; }}
  .charts {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .chart-card {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px;
  }}
  .chart-card h2 {{
    margin: 0 0 16px 0;
    font-size: 16px;
    font-weight: 600;
    color: #cbd5e1;
  }}
  .chart-card canvas {{ max-height: 240px; }}
  .table-card {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 32px;
  }}
  .table-card h2 {{
    margin: 0 0 16px 0;
    font-size: 16px;
    font-weight: 600;
    color: #cbd5e1;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid #334155;
    color: #94a3b8;
    font-weight: 500;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  td {{
    padding: 12px;
    border-bottom: 1px solid #1e293b;
    color: #e2e8f0;
  }}
  td.num {{ font-variant-numeric: tabular-nums; }}
  td.sid {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #94a3b8; }}
  .pill {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
  }}
  .pill-pc       {{ background: #1e3a8a; color: #93c5fd; }}
  .pill-android  {{ background: #14532d; color: #86efac; }}
  footer {{
    color: #64748b;
    font-size: 12px;
    text-align: center;
    margin-top: 48px;
    padding-top: 24px;
    border-top: 1px solid #1e293b;
  }}
  footer a {{ color: #94a3b8; text-decoration: none; }}
  footer a:hover {{ color: #cbd5e1; }}
  .refresh-note {{ color: #64748b; font-size: 12px; margin-top: 8px; }}
</style>
</head>
<body>

<h1>CMM702 Click-Log Dashboard</h1>
<div class="subtitle">
  Live data from Firebase Firestore collection <code>tap_logs</code>.
  Project <code>cmm702-clicklogs-2418250</code>, Render backend on EU Frankfurt.
</div>

<div class="grid">
  <div class="metric">
    <div class="label">Total Tap Records</div>
    <div class="value">{total_taps:,}</div>
  </div>
  <div class="metric">
    <div class="label">Real Sessions</div>
    <div class="value">{len(real_sessions)}</div>
  </div>
  <div class="metric">
    <div class="label">Completed Both Variations</div>
    <div class="value">{completed_both}<span class="unit"> / {len(real_sessions)}</span></div>
  </div>
  <div class="metric">
    <div class="label">Completion Rate</div>
    <div class="value">{completion_rate}<span class="unit">%</span></div>
  </div>
</div>

<div class="charts">
  <div class="chart-card">
    <h2>Query (a) — Mean tap duration: Android vs PC</h2>
    <canvas id="platformChart"></canvas>
    <div class="refresh-note">Bars show mean tap duration (ms); taps per platform labelled above bars.</div>
  </div>
  <div class="chart-card">
    <h2>Query (b) — Mean tap duration: feedbackshown vs nofeedback</h2>
    <canvas id="interfaceChart"></canvas>
    <div class="refresh-note">Bars show mean tap duration (ms); taps per interface labelled above bars.</div>
  </div>
</div>

<div class="table-card">
  <h2>Per-Session Breakdown (Query c — Completion Analysis)</h2>
  <table>
    <thead>
      <tr>
        <th>Session ID</th>
        <th>Platform</th>
        <th>Taps</th>
        <th>Variations</th>
        <th>Mean Duration</th>
        <th>Both Variations?</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>

<footer>
  <a href="/docs">API Docs (Swagger)</a> &middot;
  <a href="/summary">Raw Summary JSON</a> &middot;
  <a href="/analysis">Analysis JSON</a> &middot;
  <a href="/sample_docs">Raw Documents</a>
  <br><br>
  Auto-refreshes every 30 seconds. Last loaded: <span id="ts"></span>
</footer>

<script>
  // Render charts
  const platformCtx = document.getElementById('platformChart').getContext('2d');
  new Chart(platformCtx, {{
    type: 'bar',
    data: {{
      labels: {platform_labels!r},
      datasets: [{{
        label: 'Mean duration (ms)',
        data: {platform_means!r},
        backgroundColor: ['#3b82f6', '#10b981', '#f59e0b'],
        borderRadius: 6,
      }}]
    }},
    options: {{
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            afterLabel: function(ctx) {{
              const counts = {platform_counts!r};
              return 'Taps: ' + counts[ctx.dataIndex];
            }}
          }}
        }}
      }},
      scales: {{
        y: {{ beginAtZero: true, grid: {{ color: '#334155' }}, ticks: {{ color: '#94a3b8' }} }},
        x: {{ grid: {{ display: false }}, ticks: {{ color: '#cbd5e1', font: {{ size: 13 }} }} }}
      }}
    }}
  }});

  const interfaceCtx = document.getElementById('interfaceChart').getContext('2d');
  new Chart(interfaceCtx, {{
    type: 'bar',
    data: {{
      labels: {interface_labels!r},
      datasets: [{{
        label: 'Mean duration (ms)',
        data: {interface_means!r},
        backgroundColor: ['#8b5cf6', '#ec4899'],
        borderRadius: 6,
      }}]
    }},
    options: {{
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            afterLabel: function(ctx) {{
              const counts = {interface_counts!r};
              return 'Taps: ' + counts[ctx.dataIndex];
            }}
          }}
        }}
      }},
      scales: {{
        y: {{ beginAtZero: true, grid: {{ color: '#334155' }}, ticks: {{ color: '#94a3b8' }} }},
        x: {{ grid: {{ display: false }}, ticks: {{ color: '#cbd5e1', font: {{ size: 13 }} }} }}
      }}
    }}
  }});

  document.getElementById('ts').textContent = new Date().toLocaleString();
  setTimeout(function() {{ window.location.reload(); }}, 30000);
</script>

</body>
</html>"""
        return HTMLResponse(content=html)
    except Exception as exc:  # noqa: BLE001
        logger.error("Dashboard failed: %s", exc)
        return HTMLResponse(
            status_code=500,
            content=f"<h1>Dashboard error</h1><pre>{type(exc).__name__}: {exc}</pre>",
        )


@app.get("/sample_docs")
def sample_docs(n: int = 3):
    """Return N raw Firestore documents exactly as stored in the `tap_logs`
    collection. Proves the document-per-tap storage model described in the
    assessment. No aggregation — these are the actual persisted objects."""
    try:
        docs = []
        for doc_snapshot in db.collection("tap_logs").limit(n).stream():
            d = doc_snapshot.to_dict()
            # Convert the Firestore timestamp for JSON serialisation
            if "createdAt" in d and hasattr(d["createdAt"], "isoformat"):
                d["createdAt"] = d["createdAt"].isoformat()
            docs.append({"firestore_document_id": doc_snapshot.id, **d})
        return {
            "collection": "tap_logs",
            "note": "Each tap is persisted as its own document (document-per-tap storage model).",
            "sample_count": len(docs),
            "documents": docs,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Sample docs failed: %s", exc)
        return {"error_type": type(exc).__name__, "error_message": str(exc)}


@app.get("/analysis")
def analysis():
    """Run the three Q2 assessment queries against live Firestore data.

    Returns:
      a) Mean tap duration: Android vs PC (per-tap averages, not session-avg)
      b) Mean tap duration: feedbackshown vs nofeedback
      c) Users who completed both interface variations vs dropped off
    """
    try:
        from collections import defaultdict

        docs = [d.to_dict() for d in db.collection("tap_logs").stream()]
        if not docs:
            return {"message": "No data yet"}

        # ---- (a) by platform -------------------------------------------------
        by_platform = defaultdict(list)
        for d in docs:
            by_platform[d.get("platform", "unknown")].append(d.get("duration", 0))
        q_a = {
            p: {
                "tap_count": len(vals),
                "mean_duration_ms": round(sum(vals) / len(vals), 2) if vals else 0,
                "min_duration_ms": min(vals) if vals else 0,
                "max_duration_ms": max(vals) if vals else 0,
            }
            for p, vals in sorted(by_platform.items())
        }

        # ---- (b) by interface ------------------------------------------------
        by_interface = defaultdict(list)
        for d in docs:
            by_interface[d.get("interface", "unknown")].append(d.get("duration", 0))
        q_b = {
            k: {
                "tap_count": len(vals),
                "mean_duration_ms": round(sum(vals) / len(vals), 2) if vals else 0,
            }
            for k, vals in sorted(by_interface.items())
        }

        # ---- (c) sessions completed vs dropped -------------------------------
        by_session_seqs = defaultdict(set)
        by_session_tapcount = defaultdict(int)
        for d in docs:
            sid = d.get("sessionId", "unknown")
            by_session_seqs[sid].add(d.get("interfaceSequence"))
            by_session_tapcount[sid] += 1

        # Only count sessions with a meaningful number of taps (>= 25) as real
        # participants — this filters out incidental test requests.
        real_sessions = {
            sid: seqs for sid, seqs in by_session_seqs.items()
            if by_session_tapcount[sid] >= 25
        }
        completed = sum(1 for seqs in real_sessions.values() if len(seqs) >= 2)
        dropped = len(real_sessions) - completed
        q_c = {
            "completed_both": completed,
            "dropped_off_after_first": dropped,
            "completion_rate_pct": (
                round(100 * completed / len(real_sessions), 1)
                if real_sessions else 0
            ),
            "real_sessions_considered": len(real_sessions),
        }

        return {
            "total_documents": len(docs),
            "query_a_mean_duration_by_platform": q_a,
            "query_b_mean_duration_by_interface": q_b,
            "query_c_completion_analysis": q_c,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Analysis failed: %s", exc)
        return {"error_type": type(exc).__name__, "error_message": str(exc)}


@app.get("/summary")
def summary():
    """Live summary of current tap_logs data.

    Returns counts by platform, interface, and interfaceSequence, plus
    per-session breakdown. Useful for monitoring incoming participant data
    during the experiment without needing to open the Firebase Console.
    """
    try:
        from collections import defaultdict

        docs = [d.to_dict() for d in db.collection("tap_logs").stream()]
        if not docs:
            return {"total_taps": 0, "sessions": 0, "message": "No data yet"}

        by_session = defaultdict(list)
        for d in docs:
            by_session[d.get("sessionId", "unknown")].append(d)

        # Per-session breakdown
        sessions = {}
        for sid, taps in by_session.items():
            platforms = sorted({t.get("platform") for t in taps})
            interfaces = sorted({t.get("interface") for t in taps if t.get("interface")})
            seqs = sorted({t.get("interfaceSequence") for t in taps if t.get("interfaceSequence")})
            total_duration = sum(t.get("duration", 0) for t in taps)
            sessions[sid] = {
                "tap_count": len(taps),
                "platforms": platforms,
                "interfaces": interfaces,
                "interfaceSequences": seqs,
                "avg_duration_ms": round(total_duration / len(taps), 1) if taps else 0,
                "completed_both_variations": len(seqs) >= 2,
            }

        # Aggregate stats
        platform_counts = defaultdict(int)
        interface_counts = defaultdict(int)
        for d in docs:
            platform_counts[d.get("platform", "unknown")] += 1
            interface_counts[d.get("interface", "unknown")] += 1

        completed_both = sum(1 for s in sessions.values() if s["completed_both_variations"])

        return {
            "total_taps": len(docs),
            "sessions": len(sessions),
            "sessions_completed_both_variations": completed_both,
            "sessions_dropped_off": len(sessions) - completed_both,
            "tap_counts_by_platform": dict(platform_counts),
            "tap_counts_by_interface": dict(interface_counts),
            "per_session": sessions,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Summary failed: %s", exc)
        return {"error_type": type(exc).__name__, "error_message": str(exc)}


@app.get("/diagnostics")
def diagnostics():
    """Quick sanity check — tries a trivial Firestore operation and reports
    which credentials path was used. Useful for debugging auth issues without
    needing a full round-trip through /saveTaps."""
    try:
        # Try listing collections — cheapest possible Firestore read.
        collections = [c.id for c in db.collections()]
        return {
            "firestore_ok": True,
            "project_id": db.project,
            "existing_collections": collections,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Diagnostics failed: %s", exc)
        return {
            "firestore_ok": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }


@app.post("/saveTaps")
async def save_taps(
    id: str = Form(...),       # Session identifier (unique per session)
    var: str = Form(...),      # Device platform (android/pc)
    taps: str = Form(...),     # JSON array of tap objects
):
    """
    Receive tap data from the frontend and store each tap record
    in Firebase Firestore collection 'tap_logs'.
    """
    # --- 1. Parse inbound JSON ------------------------------------------------
    try:
        tap_list = json.loads(taps)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid taps JSON: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid taps JSON: {exc}")

    if not tap_list:
        raise HTTPException(status_code=400, detail="No tap data provided")

    # --- 2. Build the batch ---------------------------------------------------
    try:
        collection_ref = db.collection("tap_logs")
        batch = db.batch()

        for tap_json in tap_list:
            tap = json.loads(tap_json) if isinstance(tap_json, str) else tap_json

            start_ts = tap.get("startTimestamp", 0)
            end_ts = tap.get("endTimestamp", 0)

            doc = {
                "sessionId": str(id),
                "platform": str(var).lower(),
                "tapSequenceNumber": tap.get("tapSequenceNumber", 0),
                "startTimestamp": start_ts,
                "endTimestamp": end_ts,
                "duration": end_ts - start_ts,
                "interface": tap.get("interface", "unknown"),
                "interfaceSequence": tap.get("interfaceSequence", 0),
                "createdAt": SERVER_TIMESTAMP,
            }

            doc_ref = collection_ref.document()
            batch.set(doc_ref, doc)

        batch.commit()
        logger.info(
            "Saved %d tap(s) for session=%s platform=%s",
            len(tap_list), id, var,
        )
        return {"status": "ok", "saved": len(tap_list)}

    except Exception as exc:  # noqa: BLE001 — surface the real cause as JSON
        logger.error("Firestore write failed: %s", exc)
        logger.error(traceback.format_exc())
        # Return structured error so the browser / curl shows the real reason
        raise HTTPException(
            status_code=500,
            detail={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
