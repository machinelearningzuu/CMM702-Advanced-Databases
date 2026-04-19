"""
FastAPI backend for the Click Logging System.
Receives tap data from the frontend and stores it in Firebase Firestore.
"""

import json
import logging
import traceback

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
