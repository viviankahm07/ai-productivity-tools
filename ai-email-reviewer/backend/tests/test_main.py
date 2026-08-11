"""Basic smoke tests for the backend endpoints.

Run from the backend/ directory (`main.py` imports routers as top-level
packages, so pytest needs backend/ on sys.path):

    cd backend
    pytest
"""

from fastapi.testclient import TestClient

from main import app
from routers import review

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_selectors_returns_gmail_dom_config():
    response = client.get("/selectors")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert "composeBox" in body


def test_review_without_api_key_returns_clear_error(monkeypatch):
    """/review should fail with a helpful message, not a stack trace, when
    the server has no OPENAI_API_KEY configured."""
    monkeypatch.setattr(review.config, "OPENAI_API_KEY", None)
    review._client = None  # reset the cached client so the patched key takes effect

    response = client.post("/review", json={"conversation": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 500
    assert "OPENAI_API_KEY" in response.json()["detail"]
