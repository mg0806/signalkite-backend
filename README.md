# SignalKite Backend

FastAPI backend, notification gateway, workers, migrations, and deployment config for SignalKite.

## Local Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m alembic upgrade head
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Health checks:

```text
GET /health
GET /ready
GET /version
GET /metrics
```

## Render

This repo includes `render.yaml`. Deploy it as a Render Blueprint or create only the `signalkite-api` web service manually.

For a backend-only web service:

```text
Runtime: Docker
Dockerfile Path: ./backend/Dockerfile
Docker Context: ./backend
Health Check Path: /health
```

Required secrets include:

```text
KITE_API_KEY
KITE_API_SECRET
KITE_REDIRECT_URL
JWT_SECRET
BROKER_TOKEN_ENCRYPTION_KEY
CORS_ORIGINS
EMAIL_WEBHOOK_URL
ALERT_EMAIL_TO
SMTP_USER
SMTP_PASS
SMTP_FROM
```

Set Zerodha redirect URL to:

```text
https://YOUR-BACKEND-DOMAIN/auth/kite/callback
```

After deploy, use the backend base URL in the mobile app's `EXPO_PUBLIC_API_URL`.
