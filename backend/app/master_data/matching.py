"""
W0-03C (minimal) — deterministic candidate lookup and duplicate detection.

Answers one question: *which existing Master records could this raw text mean?*
It answers with **candidates**, never with a decision.

Two deterministic signals only:
  * the normalized name is identical;
  * a recorded alias is identical.

There is no fuzzy matching and no threshold, because there is no approved
policy for one (contract Q7b), and because FLOW-032 forbids a merge without
preview and an AuditEvent regardless of how confident a score looks. A score of
1.0 here means "these two strings normalize to the same thing" — it is evidence
for a human, not permission for the machine.
"""
from typing import Any, Dict, List, Optional

from app.master_data.normalize import NORMALIZATION_VERSION, normalize_name

#: Deterministic signals, with the score they report.
MATCH_EXACT_NORMALIZED = "exact_normalized_name"
MATCH_ALIAS = "known_alias"
SCORE_EXACT = 1.0
SCORE_ALIAS = 1.0


def build_candidate(entity_id: str, display_name: str, match_type: str,
                    score: float) -> Dict[str, Any]:
    return {
        "entity_id": entity_id,
        "display_name": display_name,
        "match_type": match_type,
        "score": score,
        "normalization_version": NORMALIZATION_VERSION,
    }


async def find_candidates(repository, *, entity_type: str, raw_value: str,
                          limit: int = 10) -> List[Dict[str, Any]]:
    """Return possible Master records for ``raw_value``, best evidence first.

    Read-only. Creates nothing, links nothing, changes nothing — including when
    a single exact match is found.
    """
    normalized = normalize_name(raw_value)
    if not normalized:
        return []

    seen = set()
    candidates: List[Dict[str, Any]] = []

    for doc in await repository.find_by_normalized(entity_type, normalized, limit=limit):
        if doc["id"] in seen:
            continue
        seen.add(doc["id"])
        candidates.append(build_candidate(doc["id"], doc.get("display_name", ""),
                                          MATCH_EXACT_NORMALIZED, SCORE_EXACT))

    for doc in await repository.find_by_alias(entity_type, normalized, limit=limit):
        if doc["id"] in seen:
            continue
        seen.add(doc["id"])
        candidates.append(build_candidate(doc["id"], doc.get("display_name", ""),
                                          MATCH_ALIAS, SCORE_ALIAS))

    return candidates[:limit]


async def find_duplicates(repository, *, entity_type: str, display_name: str,
                          exclude_id: Optional[str] = None,
                          limit: int = 10) -> List[Dict[str, Any]]:
    """Existing records that would collide with ``display_name``.

    Used to *warn* before a human creates a new Master record — FLOW-032 asks
    that Krum sees "възможни дубликати". It never merges and never blocks
    silently; the caller decides what to do with the answer.
    """
    candidates = await find_candidates(repository, entity_type=entity_type,
                                       raw_value=display_name, limit=limit + 1)
    if exclude_id:
        candidates = [c for c in candidates if c["entity_id"] != exclude_id]
    return candidates[:limit]
