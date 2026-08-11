"""Serves the Gmail DOM selector config the extension scrapes with.

Kept as a static endpoint (rather than baked into the extension) so selectors
can be updated when Gmail changes its markup, without shipping a new
extension version.
"""

from fastapi import APIRouter

router = APIRouter()

GMAIL_SELECTORS = {
    "version": 1,
    "threadContainer": "[role='main']",
    "messageItem": "[role='listitem'][data-message-id]",
    "collapsedIndicator": "[aria-expanded='false']",
    "senderEmailAttr": "email",
    "messageBody": "PLACEHOLDER",
    "composeBox": "div[aria-label='Message Body'][contenteditable='true']",
    "expandTrigger": "PLACEHOLDER",
}


@router.get("/selectors")
def get_selectors():
    return GMAIL_SELECTORS
