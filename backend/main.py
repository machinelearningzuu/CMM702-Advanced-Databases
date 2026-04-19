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
