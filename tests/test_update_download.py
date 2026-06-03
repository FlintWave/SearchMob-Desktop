"""Unit tests for the installer download + SHA-256 verification helper."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from searchmob_desktop.update import ReleaseAsset
from searchmob_desktop.update_download import (
    UpdateDownloadError,
    download_and_verify,
    expected_digest,
    parse_sha256sums,
)

_INSTALLER_URL = "https://example.test/dl/SearchMob.dmg"
_SUMS_URL = "https://example.test/dl/SHA256SUMS"


def _asset(name: str = "SearchMob.dmg") -> ReleaseAsset:
    return ReleaseAsset(name=name, download_url=_INSTALLER_URL)


def _sums_asset() -> ReleaseAsset:
    return ReleaseAsset(name="SHA256SUMS", download_url=_SUMS_URL)


def _sums_text(payload: bytes, name: str = "SearchMob.dmg", extra: str = "") -> str:
    digest = hashlib.sha256(payload).hexdigest()
    line = f"{digest}  {name}\n"
    return extra + line


# --- parse_sha256sums -------------------------------------------------------------------------


def test_parse_sha256sums_reads_two_space_and_binary_marker() -> None:
    digest = "a" * 64
    text = f"{digest}  plain.dmg\n{digest} *binary.msi\n\n# a comment\nbad line\n"
    parsed = parse_sha256sums(text)
    assert parsed == {"plain.dmg": digest, "binary.msi": digest}


def test_parse_sha256sums_skips_non_hex_and_short_digests() -> None:
    text = "zzzz  bad.dmg\nABCDEF  short.dmg\n"
    assert parse_sha256sums(text) == {}


def test_parse_sha256sums_lowercases_digest() -> None:
    digest_upper = "A" * 64
    assert parse_sha256sums(f"{digest_upper}  x.dmg") == {"x.dmg": "a" * 64}


def test_expected_digest_returns_none_when_absent() -> None:
    assert expected_digest("", "missing.dmg") is None


# --- download_and_verify ----------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_download_and_verify_writes_file_when_checksum_matches(tmp_path: Path) -> None:
    payload = b"installer-bytes" * 100
    respx.get(_SUMS_URL).respond(200, text=_sums_text(payload))
    respx.get(_INSTALLER_URL).respond(200, content=payload)
    async with httpx.AsyncClient() as client:
        path = await download_and_verify(client, _asset(), _sums_asset(), tmp_path)
    assert path == tmp_path / "SearchMob.dmg"
    assert path.read_bytes() == payload
    # No leftover temp files beside the final installer.
    assert [p.name for p in tmp_path.iterdir()] == ["SearchMob.dmg"]


@respx.mock
@pytest.mark.asyncio
async def test_download_and_verify_rejects_checksum_mismatch(tmp_path: Path) -> None:
    payload = b"the-real-bytes"
    # The sums file describes a DIFFERENT payload, so the computed digest will not match.
    respx.get(_SUMS_URL).respond(200, text=_sums_text(b"something-else"))
    respx.get(_INSTALLER_URL).respond(200, content=payload)
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpdateDownloadError, match="checksum did not match"):
            await download_and_verify(client, _asset(), _sums_asset(), tmp_path)
    # The mismatched download must not be left on disk under the final name.
    assert not (tmp_path / "SearchMob.dmg").exists()
    assert list(tmp_path.iterdir()) == []


@respx.mock
@pytest.mark.asyncio
async def test_download_and_verify_errors_when_no_checksum_entry(tmp_path: Path) -> None:
    # Sums file exists but has no line for our asset name -> refuse to open an unverified download.
    respx.get(_SUMS_URL).respond(200, text=_sums_text(b"x", name="other.dmg"))
    respx.get(_INSTALLER_URL).respond(200, content=b"x")
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpdateDownloadError, match="No published checksum"):
            await download_and_verify(client, _asset(), _sums_asset(), tmp_path)


@respx.mock
@pytest.mark.asyncio
async def test_download_and_verify_enforces_size_cap(tmp_path: Path) -> None:
    payload = b"x" * 5000
    respx.get(_SUMS_URL).respond(200, text=_sums_text(payload))
    respx.get(_INSTALLER_URL).respond(200, content=payload)
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpdateDownloadError, match="exceeded the expected size"):
            await download_and_verify(client, _asset(), _sums_asset(), tmp_path, max_bytes=1000)
    assert list(tmp_path.iterdir()) == []


@respx.mock
@pytest.mark.asyncio
async def test_download_and_verify_raises_on_transport_error(tmp_path: Path) -> None:
    respx.get(_SUMS_URL).respond(200, text=_sums_text(b"x"))
    respx.get(_INSTALLER_URL).mock(side_effect=httpx.ConnectError("down"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpdateDownloadError, match="Download failed"):
            await download_and_verify(client, _asset(), _sums_asset(), tmp_path)
