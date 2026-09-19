"""
LLM-based content categorization.

Assigns a single category label to each processed item using gpt-4o-mini.
"""

import logging

from app.embeddings import get_client

logger = logging.getLogger(__name__)

# The default category set. Easy to extend or override later.
CATEGORIES = [
    "Tech",
    "AI & ML",
    "Business",
    "Science",
    "Culture",
    "Politics",
    "Health",
    "Sports",
    "Opinion",
    "Other",
]

_SYSTEM_PROMPT = (
    "You are a content categorizer for a news briefing app. "
    "Given an article's title and summary, assign exactly ONE category from "
    f"this list: {', '.join(CATEGORIES)}. "
    "Respond with ONLY the category name, nothing else."
)


async def categorize_item(title: str | None, summary: str) -> str:
    """
    Assign a single category label to an item.

    Args:
        title:   Article title (may be None).
        summary: The generated summary text.

    Returns:
        One of the CATEGORIES strings.
    """
    user_msg = ""
    if title:
        user_msg += f"Title: {title}\n\n"
    user_msg += f"Summary: {summary}"

    try:
        client = get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=20,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        category = response.choices[0].message.content.strip()

        # Validate: if the model returned something outside our list, fall back.
        if category not in CATEGORIES:
            # Try a case-insensitive match.
            for cat in CATEGORIES:
                if cat.lower() == category.lower():
                    category = cat
                    break
            else:
                logger.warning(
                    "LLM returned unknown category %r for %r, defaulting to 'Other'",
                    category, title,
                )
                category = "Other"

        logger.info("Categorized %r → %s", title or "(untitled)", category)
        return category

    except Exception as exc:
        logger.warning("Categorization failed for %r, defaulting to 'Other': %s", title, exc)
        return "Other"
