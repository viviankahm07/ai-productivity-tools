"""The /convert endpoint: transcribes a math screenshot into Jupyter markdown."""

import openai
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config

router = APIRouter()

_client: openai.OpenAI | None = None


def get_client() -> openai.OpenAI:
    """Lazily construct the OpenAI client so the app can still start (and
    /health can still respond) when OPENAI_API_KEY isn't set yet."""
    global _client
    if _client is None:
        if not config.OPENAI_API_KEY:
            raise HTTPException(
                status_code=500,
                detail="Server is missing OPENAI_API_KEY. Set it in backend/.env.",
            )
        _client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


SYSTEM_PROMPT = """\
You transcribe screenshots of math/CS equations, proofs, and derivations \
into clean, well-structured Jupyter Notebook markdown. Use $...$ for inline \
math and $$...$$ for display math. Preserve any step numbering, bullet \
structure, and bold/italic annotations visible in the image. Do not wrap \
your answer in a code fence - output raw markdown ready to paste directly \
into a markdown cell. If the image contains handwriting or is ambiguous, \
make your best-effort transcription and do not add commentary about \
uncertainty.
"""


class ConvertRequest(BaseModel):
    image_base64: str


class ConvertResponse(BaseModel):
    markdown: str


def _as_data_url(image_base64: str) -> str:
    """Accepts either a raw base64 string or an already-formed data URL and
    returns a data URL, since that's the form the OpenAI image_url field
    expects."""
    if image_base64.startswith("data:"):
        return image_base64
    return f"data:image/png;base64,{image_base64}"


@router.post("/convert", response_model=ConvertResponse)
def convert(request: ConvertRequest):
    image_url = _as_data_url(request.image_base64)

    try:
        completion = get_client().chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
        )
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {e}") from e

    return ConvertResponse(markdown=completion.choices[0].message.content)
