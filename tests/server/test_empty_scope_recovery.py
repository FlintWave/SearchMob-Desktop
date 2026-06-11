"""Served results page: when an active scope filters every result out, the owner must still see the
scope (so they know what hid the results) and a one-click way to clear it. Without this the page
looked like a blank fresh search and the active scope was neither visible nor clearable from it.
"""

from __future__ import annotations

from searchmob_desktop.engines.rank import Lens, RankingRules
from searchmob_desktop.server.templates import render_results_page


def _is_safe(_url: str) -> bool:
    return True


_RULES = RankingRules(lenses=(Lens(name="Recipes & cooking"),), active_lens="Recipes & cooking")


def test_empty_results_under_active_scope_show_scope_and_clear_for_owner() -> None:
    html = render_results_page("threejs", [], _is_safe, rules=_RULES, editable=True)
    # The scope bar is rendered so the owner can switch scopes...
    assert 'class="scopebar"' in html
    # ...the emptiness is attributed to the scope, not the query...
    assert "No results match the" in html
    assert "Recipes &amp; cooking" in html
    # ...and a one-click Clear scope control posts an empty lens to recover the results.
    assert 'class="clearscope"' in html
    assert 'action="/scope"' in html
    assert "Clear scope" in html


def test_empty_results_without_active_scope_keep_the_plain_message() -> None:
    html = render_results_page("threejs", [], _is_safe, rules=RankingRules(), editable=True)
    assert "No results for" in html
    assert 'class="clearscope"' not in html


def test_empty_results_for_a_network_visitor_get_no_scope_controls() -> None:
    # A non-owner page is read-only: no scope bar or clear control even with an active scope.
    html = render_results_page("threejs", [], _is_safe, rules=_RULES, editable=False)
    assert 'class="clearscope"' not in html
    assert 'class="scopebar"' not in html
    assert "No results for" in html
