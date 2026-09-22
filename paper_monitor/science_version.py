"""First-page Science version evidence shared by downloads and Browser capture.

Keep this helper independent of the eagerly loaded download/merge module: the
Browser capture service is loaded on demand, including in an already-open App
after a source update.
"""
from __future__ import annotations

import re


def is_science_first_release_text(text: str) -> bool:
    """Recognize the provisional Science footer, not an online publication date.

    Callers supply only the main PDF's first page. Requiring both the dated
    footer and its non-final pagination notice avoids classifying a final paper
    from an ordinary reference to First Release or from a merged supplement.
    """
    text = re.sub(r"\s+", " ", text or "").casefold()
    return bool(
        re.search(r"\bfirst release\s*:\s*\d{1,2} [a-z]+ \d{4}\b", text)
        and re.search(r"\bpage numbers not final at time of first release\b", text)
        and re.search(r"\bscience\.org\b", text)
    )
