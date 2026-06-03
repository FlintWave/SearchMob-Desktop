"""Download a release installer and verify it against the published SHA256SUMS.

This backs the GUI's one-click "Update" action on macOS and Windows, where the platform installer
is unambiguous (`.dmg` / `.msi`). The flow is deliberately a *fetch-and-hand-off*, not a silent
auto-install: download the right asset, prove its SHA-256 matches the release's signed-by-checksum
`SHA256SUMS`, then let the OS open the installer. (Linux ships several package formats, so the GUI
opens the release page there instead of guessing.)

Every download goes through the same privacy-proxy `httpx.AsyncClient` the engines use (no cookies,
rotated User-Agent, no env proxies) and is bounded: the body is streamed with a hard size cap so a
hostile or mis-published asset cannot exhaust memory or disk, and the SHA-256 is computed while
streaming so a tampered byte fails the check before the file is ever opened.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import httpx

from searchmob_desktop.update import ReleaseAsset

__all__ = [
    "MAX_INSTALLER_BYTES",
    "MAX_SUMS_BYTES",
    "UpdateDownloadError",
    "default_download_dir",
    "download_and_verify",
    "expected_digest",
    "parse_sha256sums",
]

# Hard ceiling on a downloaded installer. SearchMob's installers are well under 300 MiB; this bounds
# disk/memory use so a mis-published or hostile asset cannot stream an unbounded body.
MAX_INSTALLER_BYTES = 512 * 1024 * 1024

# The SHA256SUMS file is one short line per asset; a few KiB at most.
MAX_SUMS_BYTES = 64 * 1024


class UpdateDownloadError(Exception):
    """A download or integrity check failed. Carries a user-facing message."""


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse `SHA256SUMS` content into `{asset_name: lowercase_hex_digest}`.

    Accepts the standard `sha256sum` format: `<64-hex><space><space-or-asterisk><name>`. Lines that
    do not match (blank lines, comments, malformed entries) are skipped. A leading `*` (binary-mode
    marker) on the name is stripped so the names match the published asset names.
    """
    digests: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].lower(), parts[1].strip()
        if name.startswith("*"):
            name = name[1:]
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            digests[name] = digest
    return digests


def expected_digest(sums_text: str, asset_name: str) -> str | None:
    """The expected SHA-256 for `asset_name` from `SHA256SUMS` content, or None when absent."""
    return parse_sha256sums(sums_text).get(asset_name)


def default_download_dir() -> Path:
    """A sensible place to drop the installer: the user's Downloads folder, else the temp dir.

    Downloads is discoverable for the user after the hand-off; the temp dir is the fail-safe when
    no Downloads folder exists (or is not writable).
    """
    downloads = Path.home() / "Downloads"
    if downloads.is_dir() and os.access(downloads, os.W_OK):
        return downloads
    return Path(tempfile.gettempdir())


async def _fetch_sums(client: httpx.AsyncClient, sums_asset: ReleaseAsset) -> str:
    """Download the bounded SHA256SUMS body and return it as text, or raise UpdateDownloadError."""
    try:
        async with client.stream("GET", sums_asset.download_url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_SUMS_BYTES:
                    raise UpdateDownloadError("Checksum file was unexpectedly large; aborting.")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise UpdateDownloadError(f"Could not fetch the checksum file: {exc}") from exc
    return b"".join(chunks).decode("utf-8", errors="replace")


async def download_and_verify(
    client: httpx.AsyncClient,
    asset: ReleaseAsset,
    sums_asset: ReleaseAsset,
    dest_dir: Path,
    *,
    max_bytes: int = MAX_INSTALLER_BYTES,
) -> Path:
    """Stream `asset` into `dest_dir`, verifying its SHA-256 against `sums_asset`. Return the path.

    Raises `UpdateDownloadError` on any transport failure, an oversized body, a missing checksum
    entry, or a digest mismatch. The file is written to a temporary name and only moved into place
    once the checksum verifies, so a partial or tampered download never lands at the final path.
    """
    expected = expected_digest(await _fetch_sums(client, sums_asset), asset.name)
    if expected is None:
        raise UpdateDownloadError(
            f"No published checksum for {asset.name}; refusing to open an unverified download."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    final_path = dest_dir / asset.name
    # Write next to the final path so the move is an atomic rename on the same filesystem.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{asset.name}.", dir=str(dest_dir))
    tmp_path = Path(tmp_name)
    hasher = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                async with client.stream("GET", asset.download_url) as response:
                    response.raise_for_status()
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise UpdateDownloadError(
                                "The download exceeded the expected size; aborting."
                            )
                        hasher.update(chunk)
                        out.write(chunk)
            except httpx.HTTPError as exc:
                raise UpdateDownloadError(f"Download failed: {exc}") from exc
        actual = hasher.hexdigest()
        if actual != expected:
            raise UpdateDownloadError(
                "The downloaded file's checksum did not match the published value; "
                "discarding it for your safety."
            )
        os.replace(tmp_path, final_path)
    finally:
        # Remove the temp file on any failure (a successful os.replace already consumed it).
        try:
            tmp_path.unlink()
        except OSError:
            pass
    return final_path
