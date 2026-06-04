#!/usr/bin/env python3
"""Author the per-locale UI string catalogs offline with the local `translategemma` model.

SearchMob's interface uses the gettext model: code wraps an English literal in `tr("...")` (or
`trc(context, "...")` to disambiguate, or `trn(n, "one", "other")` for counts), and a per-locale
JSON catalog supplies the translation at runtime (English is the fallback). Translations are
authored ONCE here and committed; the app never calls a model at runtime, keeping the offline /
store-nothing posture and shipping no model in the binary.

Two subcommands, both run from the repo root:

* `extract` parses the source tree (via `ast`) for `tr` / `trc` / `trn` calls and writes the source
  manifests: `locales/en.json` (`key -> source`, where a key may be a `context`+`source` composite)
  and `locales/en.plurals.json` (`key -> {"one": ..., "other": ...}`).

* `translate` fills in any not-yet-translated entry for each target locale by calling the local
  Ollama server (`translategemma:27b` by default). For plurals it authors every CLDR form the target
  language uses (Arabic has six: zero/one/two/few/many/other), prompting with a representative count
  so the model produces the right grammatical form. It is INCREMENTAL and RESUMABLE: existing
  translations are kept, only missing ones are fetched, and progress is flushed as it goes.

  Usage:
    python tools/i18n_author.py extract
    python tools/i18n_author.py translate                 # all nine target locales
    python tools/i18n_author.py translate --locale es ar  # just these
    python tools/i18n_author.py translate --model translategemma:12b

`{name}`-style placeholders are preserved: the prompt asks the model to keep them verbatim, and any
translation that drops or mangles one is rejected (the English source is kept) so a localized format
string can never raise at runtime.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from searchmob_desktop.i18n.catalog import CONTEXT_SEP
from searchmob_desktop.i18n.plurals import (
    plural_categories,
    plural_category,
    representative_count,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src" / "searchmob_desktop"
_LOCALES_DIR = _SRC_DIR / "i18n" / "locales"
_OLLAMA_URL = "http://localhost:11434/api/generate"
_DEFAULT_MODEL = "translategemma:27b"

# (tag, English name) for the nine authored locales. English is the source, never translated.
_TARGETS: tuple[tuple[str, str], ...] = (
    ("zh", "Chinese (Simplified)"),
    ("hi", "Hindi"),
    ("es", "Spanish"),
    ("ar", "Arabic"),
    ("fr", "French"),
    ("bn", "Bengali"),
    ("pt", "Portuguese"),
    ("id", "Indonesian"),
    ("ur", "Urdu"),
)

_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")

# Tokens that must survive translation untouched: named `{placeholder}` tokens and printf `%s`/`%d`
# specs. Both confuse `translategemma` — it echoes a whole sentence containing a bare `%s`, and it
# *translates the name* of a semantic placeholder (`{version}` -> `{संस्करण}`), breaking the format
# string. `_protect` masks each as an opaque `{pN}` token (which the model preserves reliably and
# whose name carries no meaning to translate) and `_restore` puts the originals back afterwards.
_PROTECT_TOKEN = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|%[sd]")

# Trailing sentence punctuation the model sometimes adds to a fragment that had none. Includes the
# CJK full stop and the Arabic full stop/comma so it is stripped for those scripts too. The
# ambiguous fullwidth marks here are deliberate (that is the punctuation we want to strip).
_TRAILING_PUNCT = ".。!！?？:：،"  # noqa: RUF001

# Non-ASCII digit bases for de-numeralizing a representative count out of a plural translation, when
# the model rendered the number in the target script's own numerals instead of Western digits.
# Arabic-Indic, Extended Arabic-Indic (Urdu), Devanagari, Bengali.
_DIGIT_BASES = (0x0660, 0x06F0, 0x0966, 0x09E6)


def _iter_source_files() -> list[Path]:
    return sorted(p for p in _SRC_DIR.rglob("*.py") if "i18n/locales" not in p.as_posix())


def _const_str(node: ast.expr | None) -> str | None:
    """Return the string value of a constant (or implicitly-concatenated constant) node, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _func_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _key(context: str | None, source: str) -> str:
    return f"{context}{CONTEXT_SEP}{source}" if context else source


def extract() -> tuple[int, int]:
    """Parse the source tree for tr/trc/trn calls; write the manifests. Return (simple, plural)."""
    simple: dict[str, str] = {}
    plurals: dict[str, dict[str, str]] = {}
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _func_name(node)
            if name not in ("tr", "trc", "trn", "N_"):
                continue
            context = next(
                (_const_str(kw.value) for kw in node.keywords if kw.arg == "context"), None
            )
            if name in ("tr", "N_") and node.args:
                source = _const_str(node.args[0])
                if source and source.strip():
                    simple[_key(context, source)] = source
            elif name == "trc" and len(node.args) >= 2:
                ctx, source = _const_str(node.args[0]), _const_str(node.args[1])
                if ctx and source and source.strip():
                    simple[_key(ctx, source)] = source
            elif name == "trn" and len(node.args) >= 3:
                one, other = _const_str(node.args[1]), _const_str(node.args[2])
                if one and other:
                    plurals[_key(context, other)] = {"one": one, "other": other}
    _LOCALES_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(_LOCALES_DIR / "en.json", {k: simple[k] for k in sorted(simple)})
    _write_json(_LOCALES_DIR / "en.plurals.json", {k: plurals[k] for k in sorted(plurals)})
    print(f"extract: {len(simple)} simple + {len(plurals)} plural sources -> locales/en*.json")
    return len(simple), len(plurals)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except ValueError:
        return {}


def _ollama(model: str, prompt: str) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(_OLLAMA_URL, data=payload, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body.get("response", "")).strip()


def _protect(text: str) -> tuple[str, list[str]]:
    """Mask every placeholder (`{name}` and `%s`/`%d`) as an opaque `{p0}`, `{p1}`, ... token.

    Keeps `translategemma` from echoing a sentence that contains a bare `%s`, and from translating
    a semantic placeholder's name. The opaque tokens ride the reliable brace path. Returns the
    masked text and the original tokens in order, for `_restore` to put back.
    """
    specs: list[str] = []

    def _mask(match: re.Match[str]) -> str:
        specs.append(match.group(0))
        return f"{{p{len(specs) - 1}}}"

    return _PROTECT_TOKEN.sub(_mask, text), specs


def _restore(text: str, specs: list[str]) -> str:
    """Swap the `{pN}` mask tokens from `_protect` back to their original `%s`/`%d` specs."""
    for index, spec in enumerate(specs):
        text = text.replace(f"{{p{index}}}", spec)
    return text


def _prompt(name: str, tag: str, text: str, context: str | None, *, insist: bool = False) -> str:
    hint = f" The text is used in this context: {context}." if context else ""
    nudge = (
        " The previous attempt returned the text unchanged; this string DOES need translating, so "
        "render its meaning in the target language while preserving the tokens."
        if insist
        else ""
    )
    return (
        f"Translate the following user-interface text from English (en) to {name} ({tag})."
        f"{hint} Keep any {{placeholder}} tokens exactly as written, and keep any digits as "
        f"Western numerals (0-9).{nudge} Reply with only the translation, no quotes or notes."
        f"\n\n{text}"
    )


def _strip_trailing(source: str, out: str) -> str:
    if source and source[-1] not in _TRAILING_PUNCT and out and out[-1] in _TRAILING_PUNCT:
        return out[:-1].strip()
    return out


def _placeholders_ok(source: str, out: str) -> bool:
    return set(_PLACEHOLDER.findall(source)) == set(_PLACEHOLDER.findall(out))


def _denumeralize(text: str, rep: int) -> str:
    """Replace the representative count in `text` with the `{n}` placeholder (Western or native)."""
    western = str(rep)
    if western in text:
        return text.replace(western, "{n}", 1)
    for base in _DIGIT_BASES:
        native = "".join(chr(base + int(d)) for d in western)
        if native in text:
            return text.replace(native, "{n}", 1)
    return text


def _clean(response: str) -> str:
    return response.strip().strip('"').strip()


def _translate_text(model: str, name: str, tag: str, rendered: str, context: str | None) -> str:
    """Translate one rendered string, masking `%s` specs and retrying once if the model echoes it.

    Returns the translation, or the input `rendered` unchanged if both attempts fail to translate it
    (an exact echo) or mangle a placeholder; callers fall back to the English source in that case.
    """
    masked, specs = _protect(rendered)
    for insist in (False, True):
        response = _clean(_ollama(model, _prompt(name, tag, masked, context, insist=insist)))
        out = _restore(_strip_trailing(masked, response), specs)
        if out and _placeholders_ok(rendered, out) and out != rendered:
            return out
        if not specs and out == rendered and not insist:
            continue  # an echo of a token-free string: one firmer retry before giving up
        if out and _placeholders_ok(rendered, out):
            return out  # a legitimately identical translation (e.g. a loanword) — keep it
    return rendered


def _translate_simple(tag: str, name: str, manifest: dict[str, str], model: str) -> None:
    catalog = _load_json(_LOCALES_DIR / f"{tag}.json")
    catalog = {k: catalog[k] for k in manifest if k in catalog}  # drop stale keys
    missing = [k for k in manifest if k not in catalog]
    print(f"  simple: {len(missing)} to translate, {len(catalog)} done")
    for index, key in enumerate(missing, start=1):
        context = key.split(CONTEXT_SEP, 1)[0] if CONTEXT_SEP in key else None
        source = manifest[key]
        catalog[key] = _translate_text(model, name, tag, source, context)
        if index % 20 == 0:
            _write_json(_LOCALES_DIR / f"{tag}.json", {k: catalog[k] for k in sorted(catalog)})
    _write_json(_LOCALES_DIR / f"{tag}.json", {k: catalog[k] for k in sorted(catalog)})


def _translate_plurals(
    tag: str, name: str, manifest: dict[str, dict[str, str]], model: str
) -> None:
    path = _LOCALES_DIR / f"{tag}.plurals.json"
    raw = _load_json(path)
    # Typed copy, dropping any stale keys no longer in the manifest.
    catalog: dict[str, dict[str, str]] = {
        k: {str(c): str(s) for c, s in v.items()}
        for k, v in raw.items()
        if k in manifest and isinstance(v, dict)
    }
    categories = plural_categories(tag)
    pending = [k for k in manifest if set(categories) - set(catalog.get(k, {}))]
    print(f"  plurals: {len(pending)} to author across {categories}")
    for key in pending:
        context = key.split(CONTEXT_SEP, 1)[0] if CONTEXT_SEP in key else None
        forms = manifest[key]
        out_forms = dict(catalog.get(key, {}))
        for category in categories:
            if category in out_forms:
                continue
            rep = representative_count(tag, category)
            english = forms["one"] if plural_category("en", rep) == "one" else forms["other"]
            rendered = english.replace("{n}", str(rep))
            translated = _translate_text(model, name, tag, rendered, context)
            out = _denumeralize(translated, rep)
            # Accept any genuine translation. Many languages render 'one'/'two'/'zero' with no
            # numeral at all (Arabic 'one' omits the digit), so do not require an `{n}`; only fall
            # back to English when the model echoed the input (translated == rendered) or gave none.
            out_forms[category] = out if (translated and translated != rendered) else english
        catalog[key] = out_forms
        _write_json(path, {k: catalog[k] for k in sorted(catalog)})


def translate(tags: list[str], model: str) -> None:
    simple_manifest = cast("dict[str, str]", _load_json(_LOCALES_DIR / "en.json"))
    plural_raw = _load_json(_LOCALES_DIR / "en.plurals.json")
    plural_manifest = cast("dict[str, dict[str, str]]", plural_raw)
    if not simple_manifest and not plural_manifest:
        sys.exit("no manifests; run `extract` first")
    for tag, name in _TARGETS:
        if tags and tag not in tags:
            continue
        print(f"\n{tag} ({name}):")
        try:
            _translate_simple(tag, name, simple_manifest, model)
            _translate_plurals(tag, name, plural_manifest, model)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            sys.exit(f"\nollama call failed ({exc}); saved progress, re-run to resume")
        print(f"{tag}: done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("extract", help="scan source for tr/trc/trn calls -> manifests")
    translate_parser = sub.add_parser("translate", help="fill missing per-locale translations")
    translate_parser.add_argument("--locale", nargs="*", default=[], help="subset of target tags")
    translate_parser.add_argument("--model", default=_DEFAULT_MODEL, help="ollama model name")
    args = parser.parse_args()
    if args.command == "extract":
        extract()
    else:
        translate(args.locale, args.model)


if __name__ == "__main__":
    main()
