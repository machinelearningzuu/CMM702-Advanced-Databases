import firebase_admin
from firebase_admin import credentials, firestore
import os
import json


def _build_credentials_from_env():
    """Build a Firebase credentials object from individual environment
    variables (Render/Railway-style), avoiding the need for a JSON file.

    Expected env vars (mirrors serviceAccountKey.json field names):
      TYPE, PROJECT_ID, PRIVATE_KEY_ID, PRIVATE_KEY,
      CLIENT_EMAIL, CLIENT_ID, AUTH_URI, TOKEN_URI,
      AUTH_PROVIDER_X509_CERT_URL, CLIENT_X509_CERT_URL, UNIVERSE_DOMAIN
    """
    required = ["PROJECT_ID", "PRIVATE_KEY", "CLIENT_EMAIL"]
    if not all(os.getenv(k) for k in required):
        return None  # Not configured via env vars

    # Critical: Render stores the private key either with real newlines
    # or with literal "\n" escape sequences. Normalise both cases.
    private_key = os.environ["PRIVATE_KEY"].replace("\\n", "\n")

    service_account_info = {
        "type": os.getenv("TYPE", "service_account"),
        "project_id": os.environ["PROJECT_ID"],
        "private_key_id": os.getenv("PRIVATE_KEY_ID", ""),
        "private_key": private_key,
        "client_email": os.environ["CLIENT_EMAIL"],
        "client_id": os.getenv("CLIENT_ID", ""),
        "auth_uri": os.getenv(
            "AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
        "token_uri": os.getenv(
            "TOKEN_URI", "https://oauth2.googleapis.com/token"),
        "auth_provider_x509_cert_url": os.getenv(
            "AUTH_PROVIDER_X509_CERT_URL",
            "https://www.googleapis.com/oauth2/v1/certs"),
        "client_x509_cert_url": os.getenv("CLIENT_X509_CERT_URL", ""),
        "universe_domain": os.getenv("UNIVERSE_DOMAIN", "googleapis.com"),
    }
    return credentials.Certificate(service_account_info)


def initialize_firebase():
    """Initialize Firebase Admin SDK.

    Resolution order:
      1. Individual env vars (PROJECT_ID, PRIVATE_KEY, CLIENT_EMAIL, ...)
         — preferred for Render/Railway deployments.
      2. FIREBASE_CREDENTIALS env var holding the full JSON string.
      3. serviceAccountKey.json file on disk (local development).
    """
    if firebase_admin._apps:
        return firestore.client()

    # 1. Individual env vars (Render/Railway)
    cred = _build_credentials_from_env()
    if cred is not None:
        firebase_admin.initialize_app(cred)
        return firestore.client()

    # 2. JSON-blob env var
    cred_env = os.getenv("FIREBASE_CREDENTIALS")
    if cred_env and cred_env.strip().startswith("{"):
        info = json.loads(cred_env)
        info["private_key"] = info["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(info)
        firebase_admin.initialize_app(cred)
        return firestore.client()

    # 3. Local file (development)
    cred_path = cred_env or os.path.join(
        os.path.dirname(__file__), "serviceAccountKey.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    return firestore.client()
