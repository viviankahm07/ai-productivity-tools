"""FastAPI app entrypoint: instance, CORS, and route registration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import review, selectors

app = FastAPI(title="Gmail AI Reply Reviewer Backend")

# Chrome extensions call from an origin like "chrome-extension://<extension-id>",
# which isn't known ahead of time for an unpacked/dev install, so we allow any
# origin. This backend has no auth/session state, so a permissive CORS policy
# doesn't expose user data to other sites.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(review.router)
app.include_router(selectors.router)


@app.get("/health")
def health():
    """Simple liveness check used to confirm the deploy is up."""
    return {"status": "ok"}
