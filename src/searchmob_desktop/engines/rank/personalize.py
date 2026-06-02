"""On-device click personalization: a Beta-Bernoulli learning layer over the ranking pass.

This learns a bounded ranking adjustment from the owner's own clicks and applies it as a pass
between the relevance sort and `apply_ranking` (so explicit pin/raise/lower/block rules always win).
It is the desktop half of a feature kept at parity with the Android app; the JSON model format
(`beta_bernoulli_v1`) is shared so a profile exported on one device imports on the other.

The signal is "click greater-than skip-above": when the owner clicks the result at displayed
position p, the clicked host gains a click and each distinct host shown above p that was skipped
gains a skip; hosts below p are ignored (the user may never have examined them). Each host keeps a
Beta(alpha, beta) belief about how often it is clicked when seen; the boost is the posterior mean
over a neutral baseline, clamped so personalization nudges ranking rather than dominating it.

Everything here is pure: no GUI, no vault, no persistence, no network. It is fail-soft like the rest
of the rank package; any unexpected error in scoring or reordering returns the input unchanged.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, TypeVar

T = TypeVar("T")

SCHEMA = "beta_bernoulli_v1"
VERSION = 1
_DAY_MS = 86_400_000
_MAX_QUERY_TERMS = 8  # cap tokens per query so a pathological query stays cheap and bounded

# A non-alphanumeric splitter kept deliberately ASCII so Python and Kotlin tokenize identically.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class PersonalizationConfig:
    """Tunables for the learning model. Stored in the JSON so the model is self-describing.

    `global_mu` is the neutral baseline click rate; it equals the prior mean so an unseen or
    at-prior host scores a boost of exactly 1.0 (no effect). The prior is a weak `Beta(2, 18)`.
    """

    alpha_prior: float = 2.0
    beta_prior: float = 18.0
    global_mu: float = 0.10  # alpha_prior / (alpha_prior + beta_prior)
    boost_min: float = 0.5
    boost_max: float = 2.0
    epsilon: float = 0.10
    half_life_days: float = 60.0
    min_signal_queries: int = 5
    min_domain_impressions: int = 3
    min_qt_impressions: int = 10
    max_domains: int = 2000
    max_qt_pairs: int = 10000


@dataclass(frozen=True, slots=True)
class KeyStats:
    """Beta counts for one key (a host, or a `term:host` pair), with the day it last changed.

    `alpha`/`beta` include the prior, so a fresh key is `(alpha_prior, beta_prior)`.
    `last_seen_days` is integer epoch days, used to fade the excess over the prior over time.
    """

    alpha: float
    beta: float
    last_seen_days: int


@dataclass
class PersonalizationModel:
    """The whole learned state: per-domain and per-(term, host) Beta counts, plus config.

    Mutable on purpose: learning updates the counters in place. `total_clicked_queries` gates
    cold start (no personalization until enough click signal has accumulated). Reads (`boost`,
    `reorder`) never mutate.
    """

    config: PersonalizationConfig = field(default_factory=PersonalizationConfig)
    domains: dict[str, KeyStats] = field(default_factory=dict)
    qt_pairs: dict[str, KeyStats] = field(default_factory=dict)
    total_clicked_queries: int = 0

    def is_empty(self) -> bool:
        """True when nothing has been learned yet (a freshly reset or never-used model)."""
        return not self.domains and not self.qt_pairs and self.total_clicked_queries == 0


# --- key construction (must stay byte-identical to the Kotlin port) ------------------------------


def normalize_host(host: str) -> str:
    """Lowercase, NFC-normalize, and strip a leading ``www.`` from a host."""
    return unicodedata.normalize("NFC", host.strip()).lower().removeprefix("www.")


def qt_key(term: str, host: str) -> str:
    """The per-(term, host) key: ``"<term>:<host>"`` with both parts normalized."""
    return f"{term}:{normalize_host(host)}"


def query_terms(query: str) -> list[str]:
    """Tokenize a query into distinct lowercase alphanumeric terms (length >= 2), capped.

    ASCII-only on purpose: a conservative tokenizer is trivially identical across Python and Kotlin,
    which matters because the same `term:host` keys must be produced on both platforms.
    """
    norm = unicodedata.normalize("NFC", query).lower()
    out: list[str] = []
    for token in _TOKEN_RE.findall(norm):
        if len(token) >= 2 and token not in out:
            out.append(token)
            if len(out) >= _MAX_QUERY_TERMS:
                break
    return out


# --- math ----------------------------------------------------------------------------------------


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _decay(stats: KeyStats, now_days: int, cfg: PersonalizationConfig) -> tuple[float, float]:
    """Return (alpha, beta) with the excess over the prior faded toward the prior by age."""
    age = now_days - stats.last_seen_days
    if age <= 0:
        return stats.alpha, stats.beta
    factor = 0.5 ** (age / cfg.half_life_days)
    alpha = cfg.alpha_prior + (stats.alpha - cfg.alpha_prior) * factor
    beta = cfg.beta_prior + (stats.beta - cfg.beta_prior) * factor
    return alpha, beta


def _key_boost(
    table: dict[str, KeyStats],
    key: str,
    min_impressions: int,
    now_days: int,
    cfg: PersonalizationConfig,
) -> float:
    """The per-key boost, or 1.0 below the cold-start impression gate or when the key is unseen."""
    stats = table.get(key)
    if stats is None:
        return 1.0
    alpha, beta = _decay(stats, now_days, cfg)
    observed = (alpha - cfg.alpha_prior) + (beta - cfg.beta_prior)
    if observed < min_impressions:
        return 1.0
    mu = alpha / (alpha + beta)
    return _clip(mu / cfg.global_mu, cfg.boost_min, cfg.boost_max)


def boost(model: PersonalizationModel, host: str | None, terms: list[str], now_ms: int) -> float:
    """The combined, bounded boost for `host` under `terms`. 1.0 (neutral) during cold start."""
    cfg = model.config
    if host is None or model.total_clicked_queries < cfg.min_signal_queries:
        return 1.0
    norm = normalize_host(host)
    if not norm:
        return 1.0
    now_days = now_ms // _DAY_MS
    factor = _key_boost(model.domains, norm, cfg.min_domain_impressions, now_days, cfg)
    for term in terms:
        factor *= _key_boost(
            model.qt_pairs, f"{term}:{norm}", cfg.min_qt_impressions, now_days, cfg
        )
    return _clip(factor, cfg.boost_min, cfg.boost_max)


# --- learning ------------------------------------------------------------------------------------


def _bump(
    table: dict[str, KeyStats], key: str, *, click: bool, now_days: int, cfg: PersonalizationConfig
) -> None:
    """Apply one observation to `key`: decay the existing counts, then add a click or a skip."""
    stats = table.get(key)
    if stats is None:
        alpha, beta = cfg.alpha_prior, cfg.beta_prior
    else:
        alpha, beta = _decay(stats, now_days, cfg)
    if click:
        alpha += 1.0
    else:
        beta += 1.0
    table[key] = KeyStats(alpha=alpha, beta=beta, last_seen_days=now_days)


def _evict(table: dict[str, KeyStats], cap: int) -> None:
    """Trim `table` to `cap` entries, dropping the least-observed (lowest alpha+beta) first."""
    if len(table) <= cap:
        return
    ordered = sorted(table.items(), key=lambda kv: kv[1].alpha + kv[1].beta, reverse=True)
    table.clear()
    table.update(ordered[:cap])


def update_from_click(
    model: PersonalizationModel,
    ordered_hosts: list[str | None],
    clicked_pos: int,
    terms: list[str],
    now_ms: int,
) -> None:
    """Learn from one click: the clicked host gains a click, each skipped-above host gains a skip.

    `ordered_hosts` is the final displayed order (hosts may be None for unparsable URLs).
    `clicked_pos` indexes into it. Hosts below the click are ignored. Mutates `model` in place;
    a malformed call (out-of-range position, unparsable clicked host) is a safe no-op.
    """
    if clicked_pos < 0 or clicked_pos >= len(ordered_hosts):
        return
    raw = ordered_hosts[clicked_pos]
    clicked = normalize_host(raw) if raw else ""
    if not clicked:
        return
    cfg = model.config
    now_days = now_ms // _DAY_MS

    skipped: list[str] = []
    for raw_above in ordered_hosts[:clicked_pos]:
        host = normalize_host(raw_above) if raw_above else ""
        if host and host != clicked and host not in skipped:
            skipped.append(host)

    _bump(model.domains, clicked, click=True, now_days=now_days, cfg=cfg)
    for host in skipped:
        _bump(model.domains, host, click=False, now_days=now_days, cfg=cfg)
    for term in terms:
        _bump(model.qt_pairs, f"{term}:{clicked}", click=True, now_days=now_days, cfg=cfg)
        for host in skipped:
            _bump(model.qt_pairs, f"{term}:{host}", click=False, now_days=now_days, cfg=cfg)

    model.total_clicked_queries += 1
    _evict(model.domains, cfg.max_domains)
    _evict(model.qt_pairs, cfg.max_qt_pairs)


# --- apply pass ----------------------------------------------------------------------------------


def reorder(  # noqa: UP047
    items: list[T],
    host_of: Callable[[T], str | None],
    query: str,
    model: PersonalizationModel,
    now_ms: int,
    *,
    rng: Callable[[], float] | None = None,
) -> list[T]:
    """Re-order `items` by a learned, bounded boost on the relevance-rank base score.

    `items` is assumed already in relevance order. With probability `epsilon` (exploration) or in
    cold start, the input is returned unchanged. Otherwise each item's weight is
    ``1/(rank+1) * boost(host)`` and the list is stable-sorted by weight, so the clamped boost can
    move an item at most a rank or two. Fail-soft: any error returns `items`.
    """
    cfg = model.config
    if not items or model.total_clicked_queries < cfg.min_signal_queries:
        return items
    roll = rng() if rng is not None else random.random()
    if roll < cfg.epsilon:
        return items
    try:
        terms = query_terms(query)
        weights = [
            (1.0 / (rank + 1)) * boost(model, host_of(item), terms, now_ms)
            for rank, item in enumerate(items)
        ]
        order = sorted(range(len(items)), key=lambda i: weights[i], reverse=True)
        return [items[i] for i in order]
    except Exception:
        return items


# --- serialization (beta_bernoulli_v1) -----------------------------------------------------------


def _round(value: float) -> float:
    return round(float(value), 6)


def _stats_to_dict(stats: KeyStats) -> dict[str, Any]:
    return {
        "alpha": _round(stats.alpha),
        "beta": _round(stats.beta),
        "lastSeenEpochDays": int(stats.last_seen_days),
    }


def _config_to_dict(cfg: PersonalizationConfig) -> dict[str, Any]:
    return {
        "alphaPrior": _round(cfg.alpha_prior),
        "betaPrior": _round(cfg.beta_prior),
        "globalMu": _round(cfg.global_mu),
        "boostMin": _round(cfg.boost_min),
        "boostMax": _round(cfg.boost_max),
        "epsilon": _round(cfg.epsilon),
        "halfLifeDays": _round(cfg.half_life_days),
        "minSignalQueries": int(cfg.min_signal_queries),
        "minDomainImpressions": int(cfg.min_domain_impressions),
        "minQtImpressions": int(cfg.min_qt_impressions),
        "maxDomains": int(cfg.max_domains),
        "maxQtPairs": int(cfg.max_qt_pairs),
    }


def to_dict(model: PersonalizationModel) -> dict[str, Any]:
    """Serialize to the camelCase dict shared with the Android client."""
    return {
        "version": VERSION,
        "schema": SCHEMA,
        "config": _config_to_dict(model.config),
        "totalClickedQueries": int(model.total_clicked_queries),
        "domains": {key: _stats_to_dict(stats) for key, stats in model.domains.items()},
        "qtPairs": {key: _stats_to_dict(stats) for key, stats in model.qt_pairs.items()},
    }


def to_json(model: PersonalizationModel) -> str:
    """Serialize to a JSON string. Fail-soft: returns ``"{}"`` on error."""
    try:
        return json.dumps(to_dict(model), ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _f(data: Any, key: str, default: float) -> float:
    value = data.get(key) if isinstance(data, dict) else None
    return float(value) if isinstance(value, (int, float)) else default


def _i(data: Any, key: str, default: int) -> int:
    value = data.get(key) if isinstance(data, dict) else None
    return int(value) if isinstance(value, (int, float)) else default


def _config_from_dict(data: Any) -> PersonalizationConfig:
    d = PersonalizationConfig()
    if not isinstance(data, dict):
        return d
    return PersonalizationConfig(
        alpha_prior=_f(data, "alphaPrior", d.alpha_prior),
        beta_prior=_f(data, "betaPrior", d.beta_prior),
        global_mu=_f(data, "globalMu", d.global_mu),
        boost_min=_f(data, "boostMin", d.boost_min),
        boost_max=_f(data, "boostMax", d.boost_max),
        epsilon=_f(data, "epsilon", d.epsilon),
        half_life_days=_f(data, "halfLifeDays", d.half_life_days),
        min_signal_queries=_i(data, "minSignalQueries", d.min_signal_queries),
        min_domain_impressions=_i(data, "minDomainImpressions", d.min_domain_impressions),
        min_qt_impressions=_i(data, "minQtImpressions", d.min_qt_impressions),
        max_domains=_i(data, "maxDomains", d.max_domains),
        max_qt_pairs=_i(data, "maxQtPairs", d.max_qt_pairs),
    )


def _stats_table(raw: Any) -> dict[str, KeyStats]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, KeyStats] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        alpha = entry.get("alpha")
        beta = entry.get("beta")
        if not isinstance(alpha, (int, float)) or not isinstance(beta, (int, float)):
            continue
        out[key] = KeyStats(
            alpha=float(alpha),
            beta=float(beta),
            last_seen_days=_i(entry, "lastSeenEpochDays", 0),
        )
    return out


def from_dict(data: Any) -> PersonalizationModel:
    """Build a model from a parsed dict. Fail-soft: anything unexpected yields an empty model."""
    if not isinstance(data, dict):
        return PersonalizationModel()
    try:
        return PersonalizationModel(
            config=_config_from_dict(data.get("config")),
            domains=_stats_table(data.get("domains")),
            qt_pairs=_stats_table(data.get("qtPairs")),
            total_clicked_queries=_i(data, "totalClickedQueries", 0),
        )
    except Exception:
        return PersonalizationModel()


def from_json(text: str) -> PersonalizationModel:
    """Parse a model from a JSON string. Fail-soft: malformed JSON yields an empty model."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return PersonalizationModel()
    return from_dict(data)


def reset(model: PersonalizationModel) -> PersonalizationModel:
    """Return a fresh empty model that keeps the existing config."""
    return replace(PersonalizationModel(), config=model.config)
