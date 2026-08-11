"""The /review endpoint: forwards a Gmail draft-review conversation to OpenAI."""

from typing import Literal

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
You are a conversational email-writing coach. You are shown a Gmail thread \
for context and a draft reply the user is about to send. Give feedback on \
the draft's tone, clarity, and completeness, and answer any follow-up \
questions the user has about it.

Whenever you suggest a rewritten version of the draft, wrap the full \
rewritten text in these exact markers so it can be extracted programmatically:
---REVISED DRAFT---
<rewritten draft text>
---END---

Only include a revised draft when a rewrite is warranted; do not use the \
markers for plain feedback with no suggested rewrite.
"""


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ReviewRequest(BaseModel):
    conversation: list[Message]


class ReviewResponse(BaseModel):
    reply: str


@router.post("/review", response_model=ReviewResponse)
def review(request: ReviewRequest):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        message.model_dump() for message in request.conversation
    ]

    try:
        completion = get_client().chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
        )
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {e}") from e

    return ReviewResponse(reply=completion.choices[0].message.content)
