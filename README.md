# CMM702 Advanced Databases — Part B Q2 (Click Logging System)

Monorepo containing the deployable components of the click-logging system.

## Structure

```
├── backend/                 FastAPI service — deployed on Render
│   ├── main.py              POST /saveTaps endpoint
│   ├── firebase_config.py   Credential loader (env vars or JSON)
│   └── requirements.txt     Python dependencies
└── frontend/                Static HTML/CSS/JS — deployed on GitHub Pages
    ├── index.html           Tap capture interface
    ├── index.css            Styling
    └── 2x/                  Retina assets
```

## Architecture

```
Participant device (Android/PC)
          │
          │ POST /saveTaps  (application/x-www-form-urlencoded)
          ▼
FastAPI on Render  ──►  Firebase Firestore  (collection: tap_logs)
```

## Deployments

- **Backend:** https://<your-service>.onrender.com
- **Frontend:** https://machinelearningzuu.github.io/CMM702-Advanced-Databases/frontend/

## Notes for the marker

- Firebase service-account credentials are supplied to Render as environment
  variables (see `backend/firebase_config.py`). The JSON key file itself is
  never committed (enforced by `.gitignore`).
- Render cold-starts take ~30s on first request after 15 min of inactivity.
