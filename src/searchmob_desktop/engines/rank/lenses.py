"""Built-in example lenses, ready to use and instructive to read.

A lens restricts/filters results by domain and keyword (see `Lens`). Domain matching is by
registrable parent, so a bare TLD-ish entry like ``"edu"`` matches every ``*.edu`` host. These
ship with both apps so a new user can try result personalization immediately and see how lenses
are put together. They are NOT active by default; the user picks one. Keep this list short,
uncontroversial, and broadly useful.
"""

from __future__ import annotations

from searchmob_desktop.engines.rank.model import Lens

DEFAULT_SAMPLE_LENSES: tuple[Lens, ...] = (
    Lens(
        name="Academic & research",
        include_domains=(
            "edu",
            "arxiv.org",
            "nature.com",
            "sciencedirect.com",
            "springer.com",
            "jstor.org",
            "ncbi.nlm.nih.gov",
            "researchgate.net",
            "semanticscholar.org",
        ),
    ),
    Lens(
        name="Developer docs",
        include_domains=(
            "developer.mozilla.org",
            "docs.python.org",
            "stackoverflow.com",
            "github.com",
            "readthedocs.io",
            "devdocs.io",
            "pkg.go.dev",
            "docs.rs",
        ),
    ),
    Lens(
        name="Recipes & cooking",
        include_domains=(
            "seriouseats.com",
            "allrecipes.com",
            "bonappetit.com",
            "epicurious.com",
            "food.com",
            "kingarthurbaking.com",
        ),
    ),
    Lens(
        name="Reference & learning",
        include_domains=(
            "wikipedia.org",
            "britannica.com",
            "khanacademy.org",
            "archive.org",
            "edu",
        ),
    ),
    Lens(
        # An exclude-only lens: keeps everything except a couple of high-volume aggregators.
        name="Less clutter (no Pinterest/Quora)",
        exclude_domains=(
            "pinterest.com",
            "quora.com",
        ),
    ),
)
