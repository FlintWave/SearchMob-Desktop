# Design: relevance-ranking

## Where it sits in the pipeline

Adapters -> Aggregator (RRF + URL-dedup) -> **relevance blend (new)** -> `sort_results` ->
`apply_ranking`. The blend changes only the aggregator's final sort key; `sort_results` (which keys
off the resulting index) and the domain-rule pass inherit the improved order unchanged.

## Algorithm

- `content_terms(query)`: Unicode word tokens (`[^\W_]+`), length >= 2, distinct, stopwords removed;
  falls back to all tokens when every token is a stopword.
- `lexical_score(title, snippet, terms)` in [0, 1]: `0.5*coverage + 0.4*title_coverage + 0.1*phrase`,
  on lightly stemmed whole-word membership; halved when the head term is absent everywhere.
- `language_affinity(query, title, snippet)`: 1.0 when the result's dominant script equals the
  query's (or the query has no letters), else 0.4. Script buckets: latin, cyrillic, greek, hebrew,
  arabic, devanagari, thai, cjk, other.
- `blended_score(rrf, lexical, affinity) = rrf * min(1.0, BASE + GAIN*lexical) * affinity`, with
  `BASE=0.5`, `GAIN=1.0`. Capping at 1.0 makes it demotion-only.

## Privacy / owner / parity

- Pure string work on data already fetched. No new outbound calls, no stored state, no vault use.
- Base relevance is identical for the owner and for LAN clients (this is not personalization); it
  does not interact with owner-only gating.
- Parity: `engines/relevance.py` and Android `engine/Relevance.kt` use the same constants and the
  same scoring so both apps rank equivalently. Shared concept, same names.

## Tuning rationale

Verified empirically against live queries (keyboard/news/musical/tie). A first naive multiplicative
blend regressed quality (dropped a relevant result on a plural mismatch, promoted keyword-stuffed
blogspam), which is why the final design is demotion-only and lightly stemmed. The bounded floor
keeps differently-phrased consensus results (e.g. "artificial intelligence" for "ai") alive.

## Multilingual readiness (for the localization pass)

- Tokenizer and affinity are language-agnostic already.
- English stopwords and the ASCII stemmer are the only English-specific pieces; both degrade
  harmlessly and are the documented hooks for per-language stopword/stemmer tables.
- Open follow-up for i18n (tracked separately): make the engine `Accept-Language` reflect the
  selected UI/query language so engines return same-language results in the first place.
