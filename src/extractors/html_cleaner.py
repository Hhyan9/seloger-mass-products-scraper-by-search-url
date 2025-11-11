import logging
import re
from typing import Optional

LOGGER = logging.getLogger("seloger_scraper.html_cleaner")

_WHITESPACE_RE = re.compile(r"\s+")
_INT_RE = re.compile(r"(-?\d[\d\s]*)")
_FLOAT_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)")

def clean_text(value: str) -> str:
    """
    Collapse whitespace and strip text. Safe for None-like input.
    """
    if value is None:
        return ""
    text = str(value)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()

def extract_int(value: str) -> Optional[int]:
    """
    Extract first integer from text.
    """
    if not value:
        return None
    match = _INT_RE.search(str(value))
    if not match:
        return None
    num = match.group(1).replace(" ", "").replace("\u00a0", "")
    try:
        return int(num)
    except ValueError as exc:
        LOGGER.debug("Failed to parse integer from %r: %s", num, exc)
        return None

def extract_float(value: str) -> Optional[float]:
    """
    Extract first float (using dot or comma) from text.
    """
    if not value:
        return None
    match = _FLOAT_RE.search(str(value))
    if not match:
        return None
    num = match.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return float(num)
    except ValueError as exc:
        LOGGER.debug("Failed to parse float from %r: %s", num, exc)
        return None