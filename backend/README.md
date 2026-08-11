# Backend

FastAPI service for the Gmail AI Reply Reviewer extension. Forwards thread/draft
context to OpenAI for feedback and serves the Gmail DOM selector config.

## Run locally

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and set OPENAI_API_KEY

uvicorn main:app --reload
```

The API is now at `http://127.0.0.1:8000`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deployment (Railway)

- `OPENAI_API_KEY` and `OPENAI_MODEL` are set as environment variables in the
  Railway project dashboard (not committed to the repo).
- Railway uses the `Procfile` (`uvicorn main:app --host 0.0.0.0 --port $PORT`)
  as the start command.
- Pushing to `main` triggers an auto-deploy.
