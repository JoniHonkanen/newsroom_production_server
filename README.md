# News Production Backend

FastAPI + Strawberry GraphQL backend for news. Includes Twilio call integration (for interviews) (OpenAI Realtime) and PostgreSQL.

## This is part of newsroom project
There is (currently) three components in newsroom project
1. Generating news -> Application that runs every x minutes to generate news
2. Backend server -> Serving content to frontend, phone interviews
3. Frontend -> UI for news

THIS IS THE PART 2 - BACKEND SERVER

## Installation

- Requirements: Python 3.11+, PostgreSQL
- Install dependencies (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a .env in the project root and set at least (check example .env_example):

- DB_HOST, DB_PORT=5432, DB_NAME, DB_USER, DB_PASSWORD
- HOST=0.0.0.0, PORT=4000, STATIC_FILE_PATH=C:\\path\\to\\images
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
- OPENAI_API_KEY, LOCALTUNNEL_URL=<https://your-tunnel.example>
- (optional) WHERE_TO_CALL=+358...

## Run

```powershell
python main.py
```

- Health: <http://localhost:4000/health>
- GraphQL: <http://localhost:4000/graphql> (GraphiQL UI)
- Docs: <http://localhost:4000/docs>

## GraphQL

- The GraphQL API is served by Strawberry at `/graphql`.
- Schema in `schema.py`, resolvers in `resolvers.py`.

## Twilio testing (requires a local tunnel)

Twilio needs a public HTTPS/WSS URL. Open a tunnel to port 4000 and set `LOCALTUNNEL_URL` in `.env`.

```powershell
npx localtunnel --port 4000
# or (if lt is installed)
lt --port 4000
```

Test call:

- POST <http://localhost:4000/start-interview> with body

```json
{
  "phone_number": "+358401234567",
  "article_id": 123,
  "phone_script_json": {
    "language": "fi",
    "voice": "shimmer",
    "temperature": 0.8,
    "instructions": "Start a friendly interview..."
  }
}
```

- Or POST `/trigger-call` (uses WHERE_TO_CALL).

Twilio fetches TwiML from `${LOCALTUNNEL_URL}/incoming-call` and streams audio over WSS to `/media-stream`.
