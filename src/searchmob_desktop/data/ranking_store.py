"""Persist the result-ranking rules as one JSON blob in the encrypted vault.

The rules (per-domain actions, lenses, imported goggles) are private personalization, so they live
in the same encrypted store as the BYO API keys rather than in the plaintext `prefs.json`. Reads
and writes are fail-soft: with no vault (or a locked one) `load_ranking_rules` returns empty rules
and `save_ranking_rules` reports failure, so the search path always has a usable rule set.
"""

from __future__ import annotations

from searchmob_desktop.data.vault_access import open_encrypted_prefs
from searchmob_desktop.engines.rank import RankingRules

# Encrypted-prefs key holding the serialized RankingRules JSON.
RANKING_KEY = "ranking.rules"


def load_ranking_rules() -> RankingRules:
    """Read the saved rules from the vault, or empty rules if none/unavailable."""
    prefs = open_encrypted_prefs()
    if prefs is None:
        return RankingRules()
    try:
        blob = prefs.get(RANKING_KEY)
    except Exception:
        return RankingRules()
    if not blob:
        return RankingRules()
    return RankingRules.from_json(blob)


def save_ranking_rules(rules: RankingRules) -> bool:
    """Persist the rules to the vault. `True` on success, `False` if the vault is unavailable."""
    prefs = open_encrypted_prefs()
    if prefs is None:
        return False
    try:
        prefs.put(RANKING_KEY, rules.to_json())
    except Exception:
        return False
    return True
