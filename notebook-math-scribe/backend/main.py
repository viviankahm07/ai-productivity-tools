"""FastAPI app entrypoint: instance, CORS, and route registration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import convert

app = FastAPI(title="Notebook Math Scribe Backend")

# Chrome extensions call from an origin like "chrome-extension://<extension-id>",
# which isn't known ahead of time for an unpacked/dev install, so we allow any
# origin. Requests to /convert are still gated by the X-API-Key check in
# routers/convert.py.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(convert.router)


@app.get("/health")
def health():
    """Simple liveness check used to confirm the deploy is up."""
    return {"status": "ok"}
