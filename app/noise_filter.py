"""
Two-stage noise filter: cheap heuristics first, then an LLM classification
pass for borderline cases.

Keeps the summarization pipeline focused on substantive content and avoids
wasting OpenAI tokens on teasers, ads, and link-only posts.
"""

import logging
import os
import re

from app.embeddings import get_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Below this length (chars), an item is immediately filtered as a teaser.
_MIN_LENGTH = 150

# Between _MIN_LENGTH and this value the item is "borderline" and gets
# an LLM classification pass.
_BORDERLINE_LENGTH = 500

# Title patterns that strongly signal low-value content.
_LOW_VALUE_TITLE_PATTERNS = re.compile(
    r"(?i)\b(sponsored|advertisement|advertorial|partner\s+content|"
    r"paid\s+post|link\s+roundup|link\s+post|links?\s+of\s+the\s+(day|week)|"
    r"weekly\s+links|open\s+thread|daily\s+links)\b"
)

# ---------------------------------------------------------------------------
# Heuristic stage
# ---------------------------------------------------------------------------


def _heuristic_filter(text: str, title: str | None) -> tuple[bool, str | None]:
    """
    Fast, no-cost heuristic check.

    Returns (passed, reason).  If passed is False, reason explains why.
    """
    if not text or not text.strip():
        return False, "Empty content after extraction"

    if len(text.strip()) < _MIN_LENGTH:
        return False, f"Content too short ({len(text.strip())} chars) — likely a teaser or placeholder"

    if title and _LOW_VALUE_TITLE_PATTERNS.search(title):
        return False, f"Title matches low-value pattern: {title!r}"

    return True, None


# ---------------------------------------------------------------------------
# LLM stage (borderline items only)
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT = """\
You are a content quality classifier for a news briefing app.

Classify the following article as either "substantive" or "low_value".

- "substantive": Contains original reporting, analysis, opinion, tutorial, \
  or any content worth summarizing for a reader.
- "low_value": A teaser or stub with no real content, a sponsored/ad post, \
  a link-only roundup with no original commentary, a repost or syndication \
  with near-zero original content, or boilerplate (cookie notices, etc.).

Respond with EXACTLY one JSON object:
{"classification": "substantive" | "low_value", "reason": "<brief explanation>"}
"""


async def _llm_classify(text: str, title: str | None) -> tuple[bool, str | None]:
    """
    Call gpt-4o-mini to classify borderline content.

    Returns (passed, reason).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or "your_openai_api_key_here" in api_key or not api_key.startswith("sk-"):
        return True, None

    user_msg = ""
    if title:
        user_msg += f"Title: {title}\n\n"
    # Send only first 1500 chars to keep cost low.
    user_msg += f"Content:\n{text[:1500]}"

    try:
        client = get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=120,
            messages=[
                {"role": "system", "content": _CLASSIFICATION_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        reply = response.choices[0].message.content.strip()
        # Parse the JSON response.
        import json
        result = json.loads(reply)
        classification = result.get("classification", "substantive")
        reason = result.get("reason", "")

        if classification == "low_value":
            return False, f"LLM classified as low-value: {reason}"
        return True, None

    except Exception as exc:
        # On LLM failure, let the item through — fail open.
        logger.warning("LLM noise classification failed, allowing item: %s", exc)
        return True, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def noise_filter(text: str, title: str | None) -> tuple[bool, str | None]:
    """
    Run the two-stage noise filter on an item.

    Returns:
        (passed, reason) — passed=True means the item should be summarized.
        If passed=False, reason explains why it was filtered.
    """
    passed, reason = _heuristic_filter(text, title)
    if not passed:
        logger.info("Item filtered (heuristic): %s — %s", title or "(no title)", reason)
        return False, reason

    # Borderline items get an LLM check.
    text_len = len(text.strip())
    if text_len <= _BORDERLINE_LENGTH:
        passed, reason = await _llm_classify(text, title)
        if not passed:
            logger.info("Item filtered (LLM): %s — %s", title or "(no title)", reason)
            return False, reason

    return True, None
