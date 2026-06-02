"""Unit tests for the click-personalization model (pure, no Qt/vault/network).

These pin the math and the safety guardrails so the Android port can be checked against the same
behavior: skip-above counting, the bounded boost, cold-start gating, epsilon exploration, time
decay, eviction caps, and the portable JSON round-trip.
"""

from __future__ import annotations

from searchmob_desktop.engines.rank import personalize as p

_DAY_MS = 86_400_000


def _day(n: int) -> int:
    return n * _DAY_MS


def _train(model: p.PersonalizationModel, hosts: list[str], clicked: int, times: int, now: int):
    for _ in range(times):
        p.update_from_click(model, list(hosts), clicked, p.query_terms("python list"), now)


def test_query_terms_are_ascii_lowercase_distinct_and_capped() -> None:
    assert p.query_terms("Python  list, list!!") == ["python", "list"]
    assert p.query_terms("a I/O of") == ["of"]  # single chars dropped, distinct, lowercased
    assert len(p.query_terms(" ".join(f"term{i}" for i in range(20)))) == 8  # capped


def test_normalize_host_strips_www_and_lowercases() -> None:
    assert p.normalize_host("WWW.Example.COM") == "example.com"
    assert p.normalize_host("sub.example.com") == "sub.example.com"


def test_skip_above_only_counts_hosts_above_the_click() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    hosts = ["a.com", "b.com", "so.com", "c.com"]
    p.update_from_click(m, hosts, 2, [], now)
    # Clicked host gains a click; hosts above gain a skip; the host below is untouched.
    assert m.domains["so.com"].alpha == m.config.alpha_prior + 1
    assert m.domains["a.com"].beta == m.config.beta_prior + 1
    assert m.domains["b.com"].beta == m.config.beta_prior + 1
    assert "c.com" not in m.domains


def test_clicked_host_not_double_counted_when_it_repeats_above() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    # The clicked host also appears above the click; it must not be recorded as its own skip.
    p.update_from_click(m, ["so.com", "a.com", "so.com"], 2, [], now)
    assert m.domains["so.com"].alpha == m.config.alpha_prior + 1
    assert m.domains["so.com"].beta == m.config.beta_prior  # no skip for itself


def test_out_of_range_or_unparsable_click_is_a_no_op() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    p.update_from_click(m, ["a.com"], 5, [], now)  # position out of range
    p.update_from_click(m, [None], 0, [], now)  # unparsable clicked host
    assert m.is_empty()


def test_boost_is_neutral_until_cold_start_threshold_met() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    hosts = ["a.com", "so.com"]
    # Below MIN_SIGNAL_QUERIES clicked queries: no boost at all.
    _train(m, hosts, 1, m.config.min_signal_queries - 1, now)
    assert p.boost(m, "so.com", [], now) == 1.0
    # One more click crosses the threshold and the clicked domain now boosts above 1.0.
    _train(m, hosts, 1, 1, now)
    assert p.boost(m, "so.com", [], now) > 1.0


def test_boost_is_clamped_to_configured_bounds() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    hosts = ["a.com", "so.com"]
    _train(m, hosts, 1, 40, now)  # heavy, lopsided signal
    assert p.boost(m, "so.com", [], now) == m.config.boost_max
    assert p.boost(m, "a.com", [], now) == m.config.boost_min
    # An unseen host is always exactly neutral.
    assert p.boost(m, "never-seen.example", [], now) == 1.0


def test_qt_pair_boost_gated_by_min_impressions() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    hosts = ["a.com", "so.com"]
    # Six clicks: domain gate (3) is met but the qt gate (10) is not, so a query term adds nothing.
    _train(m, hosts, 1, 6, now)
    domain_only = p.boost(m, "so.com", [], now)
    with_terms = p.boost(m, "so.com", p.query_terms("python list"), now)
    assert with_terms == domain_only
    # Past the qt gate the term contributes additional (still clamped) boost.
    _train(m, hosts, 1, 10, now)
    assert p.boost(m, "so.com", p.query_terms("python list"), now) >= domain_only


def test_time_decay_fades_excess_toward_prior() -> None:
    # Raise the clamp so the fade is visible rather than hidden by the boost ceiling.
    cfg = p.PersonalizationConfig(boost_max=100.0, min_signal_queries=1, min_domain_impressions=1)
    m = p.PersonalizationModel(config=cfg)
    start = _day(20000)
    _train(m, ["a.com", "so.com"], 1, 5, start)
    fresh = p.boost(m, "so.com", [], start)
    assert fresh > 1.0
    # One half-life later, the boost has faded toward neutral (but stays >= 1.0 here).
    later = _day(20000 + int(cfg.half_life_days))
    decayed = p.boost(m, "so.com", [], later)
    assert 1.0 <= decayed < fresh


def test_reorder_promotes_learned_domain_within_bounds() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    hosts = ["a.com", "b.com", "so.com", "c.com"]
    _train(m, hosts, 2, 30, now)  # always click so.com, skipping a.com/b.com
    out = p.reorder(list(hosts), lambda h: h, "python list", m, now, rng=lambda: 0.99)
    # so.com rises above the skipped domains; ordering still bounded (engine consensus matters).
    assert out.index("so.com") < out.index("b.com")
    assert set(out) == set(hosts)  # nothing dropped


def test_reorder_bypasses_under_epsilon_and_cold_start() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    hosts = ["a.com", "b.com", "so.com"]
    # Cold start: returns input unchanged regardless of rng.
    assert p.reorder(list(hosts), lambda h: h, "q", m, now, rng=lambda: 0.99) == hosts
    _train(m, hosts, 2, 30, now)
    # Exploration roll below epsilon bypasses personalization entirely.
    assert p.reorder(list(hosts), lambda h: h, "q", m, now, rng=lambda: 0.0) == hosts


def test_eviction_caps_table_size_keeping_most_observed() -> None:
    m = p.PersonalizationModel(config=p.PersonalizationConfig(max_domains=2, max_qt_pairs=2))
    now = _day(20000)
    # Click a distinct host each round so many domains accumulate; the clicked host gets the most
    # observations and must survive eviction down to the cap.
    for i in range(6):
        p.update_from_click(m, [f"h{i}.com", "keep.com"], 1, [], now)
    assert len(m.domains) <= 2
    assert "keep.com" in m.domains  # the most-observed entry is kept


def test_json_round_trip_is_identity() -> None:
    m = p.PersonalizationModel()
    now = _day(20000)
    _train(m, ["a.com", "so.com"], 1, 7, now)
    text = p.to_json(m)
    again = p.from_json(text)
    assert p.to_json(again) == text
    assert again.total_clicked_queries == m.total_clicked_queries


def test_from_json_is_fail_soft() -> None:
    assert p.from_json("not json").is_empty()
    assert p.from_json("[]").is_empty()
    assert p.from_json("{}").is_empty()


def test_reset_clears_counts_but_keeps_config() -> None:
    cfg = p.PersonalizationConfig(epsilon=0.25)
    m = p.PersonalizationModel(config=cfg)
    _train(m, ["a.com", "so.com"], 1, 7, _day(20000))
    cleared = p.reset(m)
    assert cleared.is_empty()
    assert cleared.config.epsilon == 0.25
