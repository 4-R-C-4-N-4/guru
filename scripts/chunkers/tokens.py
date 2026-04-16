"""
Token counter for the chunking pipeline.

Primary: tiktoken with cl100k_base encoding (GPT-3.5/4 compatible).
Fallback: whitespace-word heuristic (warns once at import time).
"""

import logging

logger = logging.getLogger(__name__)

_encoder = None
_using_fallback = False


def _load_encoder():
    global _encoder, _using_fallback
    if _encoder is not None:
        return
    try:
        import tiktoken
        _encoder = tiktoken.get_encoding("cl100k_base")
        logger.debug("Token counter: using tiktoken cl100k_base")
    except ImportError:
        _using_fallback = True
        logger.warning(
            "tiktoken not installed — token counter using whitespace-word heuristic. "
            "Install with: pip install tiktoken"
        )


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """
    Count tokens in text.

    Uses tiktoken cl100k_base by default. Falls back to len(text.split())
    if tiktoken is unavailable, with a one-time warning.

    Args:
        text: Input text to count.
        model: Encoding name (only cl100k_base currently used).

    Returns:
        Integer token count.
    """
    _load_encoder()
    if _using_fallback:
        return len(text.split())
    return len(_encoder.encode(text))
