# Contributing to SearchMob Desktop

Thanks for the interest. SearchMob Desktop is a Python port of
[SearchMob for Android](https://github.com/FlintWave/SearchMob), so feature work happens here
independently of the Android repo, with parity as a goal.

## Development setup

You need Python 3.12+.

```bash
git clone https://github.com/FlintWave/SearchMob-Desktop.git
cd SearchMob-Desktop
python -m venv .venv
. .venv/bin/activate                 # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"              # plus [gui] / [storage] as you need them
```

## Day-to-day

```bash
ruff check                            # lint
ruff format                           # format
pytest -q                             # tests
searchmob-desktop --help              # invoke the CLI
```

## Commits and branches

- One feature or fix per branch; rebase or merge `main` into your branch before opening a PR.
- [Conventional Commits](https://www.conventionalcommits.org) for commit messages.
- CI must be green before merge. `main` is protected.

## Style

- Match the surrounding code: same indentation, naming, and idioms.
- No em dashes (— –) anywhere in source, comments, docs, or UI strings; use plain punctuation.
- Type-annotated where it helps the reader; `mypy --strict` runs in CI.

## Releases (maintainers)

Releases follow Ubuntu-style `YY.MM.VV` versioning. Bump `__version__` in
`src/searchmob_desktop/version.py`, tag `vYY.MM.VV`, and push the tag. The release workflow builds
the native installers and uploads them to the GitHub Release.
