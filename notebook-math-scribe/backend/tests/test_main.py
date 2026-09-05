"""Basic smoke tests for the backend endpoints.

Run from the backend/ directory (`main.py` imports routers as top-level
packages, so pytest needs backend/ on sys.path):

    cd backend
    pytest
"""

from fastapi.testclient import TestClient

from main import app
from routers import convert

client = TestClient(app)

# A minimal 1x1 PNG, base64-encoded - just needs to be valid base64, since
# OpenAI calls are mocked or never reached in these tests.
SAMPLE_IMAGE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_convert_without_api_key_returns_clear_error(monkeypatch):
    """/convert should fail with a helpful message, not a stack trace, when
    the server has no OPENAI_API_KEY configured."""
    monkeypatch.setattr(convert.config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(convert.config, "API_SHARED_SECRET", None)
    convert._client = None  # reset the cached client so the patched key takes effect

    response = client.post("/convert", json={"image_base64": SAMPLE_IMAGE_BASE64})

    assert response.status_code == 500
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_convert_missing_api_key_header_returns_401(monkeypatch):
    """When API_SHARED_SECRET is configured, a request with no X-API-Key
    header at all must be rejected."""
    monkeypatch.setattr(convert.config, "API_SHARED_SECRET", "test-secret")

    response = client.post("/convert", json={"image_base64": SAMPLE_IMAGE_BASE64})

    assert response.status_code == 401


def test_convert_incorrect_api_key_header_returns_401(monkeypatch):
    """A wrong X-API-Key must also be rejected, not just a missing one."""
    monkeypatch.setattr(convert.config, "API_SHARED_SECRET", "test-secret")

    response = client.post(
        "/convert",
        json={"image_base64": SAMPLE_IMAGE_BASE64},
        headers={"X-API-Key": "wrong-secret"},
    )

    assert response.status_code == 401


def test_convert_happy_path_returns_markdown(monkeypatch):
    """With a valid API key and a mocked OpenAI client, /convert should
    return the model's transcription as-is. The real OpenAI API is never
    called."""
    monkeypatch.setattr(convert.config, "API_SHARED_SECRET", "test-secret")

    class FakeMessage:
        content = "## Step 1\n\n$$e^{i\\pi} + 1 = 0$$"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(convert, "get_client", lambda: FakeClient())

    response = client.post(
        "/convert",
        json={"image_base64": SAMPLE_IMAGE_BASE64},
        headers={"X-API-Key": "test-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"markdown": "## Step 1\n\n$$e^{i\\pi} + 1 = 0$$"}
