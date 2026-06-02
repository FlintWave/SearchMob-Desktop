"""Persist the learned click-personalization model as one JSON blob in the encrypted vault.

The model encodes which sites the owner tends to click, so it is private personalization and lives
in the same encrypted store as the BYO API keys and ranking rules rather than in plaintext
`prefs.json`. Reads and writes are fail-soft: with no vault (or a locked zero-knowledge one)
`load_personalization` returns an empty model and `save_personalization` reports failure, so the
search path always has a usable model and personalization is simply absent when it cannot be stored.
"""

from __future__ import annotations

from searchmob_desktop.data.vault_access import open_encrypted_prefs
from searchmob_desktop.engines.rank.personalize import (
    PersonalizationModel,
    from_json,
    to_json,
)

# Encrypted-prefs key holding the serialized personalization model JSON.
PERSONALIZATION_KEY = "ranking.personalization"


def load_personalization() -> PersonalizationModel:
    """Read the saved model from the vault, or an empty model if unavailable/locked/absent."""
    prefs = open_encrypted_prefs()
    if prefs is None:
        return PersonalizationModel()
    try:
        blob = prefs.get(PERSONALIZATION_KEY)
    except Exception:
        return PersonalizationModel()
    if not blob:
        return PersonalizationModel()
    return from_json(blob)


def save_personalization(model: PersonalizationModel) -> bool:
    """Persist the model to the vault. `True` on success, `False` if the vault is unavailable."""
    prefs = open_encrypted_prefs()
    if prefs is None:
        return False
    try:
        prefs.put(PERSONALIZATION_KEY, to_json(model))
    except Exception:
        return False
    return True
