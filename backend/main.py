"""
FastAPI backend for the Click Logging System.
Receives tap data from the frontend and stores it in Firebase Firestore.
"""

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from firebase_config import initialize_firebase
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
import json

app = FastAPI(title="Click Logging API", version="1.0.0")

# Allow CORS for GitHub Pages and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your GitHub Pages URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Firestore client
db = initialize_firebase()


@app.get("/")
def root():
    return {"status": "ok", "message": "Click Logging API is running"}


@app.post("/saveTaps")
async def save_taps(
    id: str = Form(...),       # Session identifier (unique per session)
    var: str = Form(...),      # Device platform (android/pc)
    taps: str = Form(...),     # JSON array of tap objects
):
    """
    Receive tap data from the frontend and store each tap record
    in Firebase Firestore collection 'tap_logs'.

    Expected tap object format:
    {
        "tapSequenceNumber": int,
        "startTimestamp": int (ms),
        "endTimestamp": int (ms),
        "interfaceSequence": int,
        "interface": "feedbackshown" | "nofeedback"
    }
    """
    try:
        # Parse the taps JSON array
        tap_list = json.loads(taps)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid taps JSON format")

    if not tap_list:
        raise HTTPException(status_code=400, detail="No tap data provided")

    # Reference to the tap_logs collection
    collection_ref = db.collection("tap_logs")

    # Use a batch write for efficiency
    batch = db.batch()

    for tap_json in tap_list:
        # Parse individual tap if it's a string
        if isinstance(tap_json, str):
            tap = json.loads(tap_json)
        else:
            tap = tap_json

        # Calculate duration (pre-computed for efficient querying)
        start_ts = tap.get("startTimestamp", 0)
        end_ts = tap.get("endTimestamp", 0)
        duration = end_ts - start_ts

        # Build the Firestore document
        doc = {
            "sessionId": str(id),
            "platform": str(var).lower(),
            "tapSequenceNumber": tap.get("tapSequenceNumber", 0),
            "startTimestamp": start_ts,
            "endTimestamp": end_ts,
            "duration": duration,
            "interface": tap.get("interface", "unknown"),
            "interfaceSequence": tap.get("interfaceSequence", 0),
            "createdAt": SERVER_TIMESTAMP,
        }

        # Add to batch
        doc_ref = collection_ref.document()
        batch.set(doc_ref, doc)

    # Commit all writes atomically
    batch.commit()

    return "Data saved successfully"


@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    import os
    # Render sets PORT automatically; default to 8000 for local dev
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
