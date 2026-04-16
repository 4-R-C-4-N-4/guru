"""
guru/preferences.py — UserPreferences dataclass + filtering logic.

Controls which traditions and texts are included/excluded from retrieval.
Applied both as a vector-store filter (pre-retrieval) and as a post-retrieval
allow-list check (belt-and-suspenders).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports


@dataclass
class UserPreferences:
    """
    Encapsulates user inclusion/exclusion preferences for traditions and texts.

    Modes:
      "all"       — every chunk allowed; no vector filter applied
      "whitelist" — only chunks from whitelisted traditions/texts
      "blacklist" — all chunks except blacklisted traditions/texts
    """
    mode: str = "all"
    blacklisted_traditions: list[str] = field(default_factory=list)
    blacklisted_texts: list[str] = field(default_factory=list)
    whitelisted_traditions: list[str] = field(default_factory=list)
    whitelisted_texts: list[str] = field(default_factory=list)

    # ── factory methods ─────────────────────────────────────────────────────

    @classmethod
    def allow_all(cls) -> UserPreferences:
        return cls(mode="all")

    @classmethod
    def from_dict(cls, d: dict) -> UserPreferences:
        return cls(
            mode=d.get("mode", "all"),
            blacklisted_traditions=list(d.get("blacklisted_traditions", [])),
            blacklisted_texts=list(d.get("blacklisted_texts", [])),
            whitelisted_traditions=list(d.get("whitelisted_traditions", [])),
            whitelisted_texts=list(d.get("whitelisted_texts", [])),
        )

    @classmethod
    def from_toml(cls, path: str | Path) -> UserPreferences:
        import tomllib
        with open(path, "rb") as f:
            d = tomllib.load(f)
        return cls.from_dict(d.get("preferences", {}))

    # ── filtering logic ─────────────────────────────────────────────────────

    def is_chunk_allowed(self, tradition: str, text_id: str = "") -> bool:
        """
        Return True if a chunk from this tradition/text is allowed.
        Used as a post-retrieval guard.
        """
        if self.mode == "all":
            return True

        if self.mode == "blacklist":
            if tradition in self.blacklisted_traditions:
                return False
            if text_id and text_id in self.blacklisted_texts:
                return False
            return True

        if self.mode == "whitelist":
            if tradition in self.whitelisted_traditions:
                return True
            if text_id and text_id in self.whitelisted_texts:
                return True
            return False

        return True  # unknown mode: allow

    def to_vector_filters(self) -> dict | None:
        """
        Produce a ChromaDB-compatible where-clause dict, or None if no filter.

        ChromaDB filter syntax:
          {"tradition": {"$ne": "gnosticism"}}           — single exclusion
          {"$and": [{"tradition": {"$ne": "A"}}, ...]}   — multiple exclusions
          {"tradition": {"$in": ["A", "B"]}}             — whitelist
        """
        if self.mode == "all":
            return None

        if self.mode == "blacklist":
            conditions = []
            for trad in self.blacklisted_traditions:
                conditions.append({"tradition": {"$ne": trad}})
            for text_id in self.blacklisted_texts:
                conditions.append({"text_id": {"$ne": text_id}})
            if not conditions:
                return None
            if len(conditions) == 1:
                return conditions[0]
            return {"$and": conditions}

        if self.mode == "whitelist":
            # ChromaDB $in operator
            conditions = []
            if self.whitelisted_traditions:
                conditions.append({"tradition": {"$in": self.whitelisted_traditions}})
            if self.whitelisted_texts:
                conditions.append({"text_id": {"$in": self.whitelisted_texts}})
            if not conditions:
                return None
            if len(conditions) == 1:
                return conditions[0]
            return {"$or": conditions}

        return None

    def active_tradition_summary(self) -> str:
        """Human-readable summary of what's currently active."""
        if self.mode == "all":
            return "All traditions"
        if self.mode == "blacklist":
            if self.blacklisted_traditions:
                return f"All except: {', '.join(self.blacklisted_traditions)}"
            return "All traditions (blacklist empty)"
        if self.mode == "whitelist":
            included = self.whitelisted_traditions or ["(none set)"]
            return f"Only: {', '.join(included)}"
        return f"Mode '{self.mode}'"
