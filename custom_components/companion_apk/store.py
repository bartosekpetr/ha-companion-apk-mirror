"""Local APK mirror: download, index and prune release artifacts on disk."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    DOWNLOAD_CHUNK_SIZE,
    DOWNLOAD_TIMEOUT_SECONDS,
    INDEX_FILENAME,
    INDEX_VERSION,
    STORAGE_SUBDIR,
)
from .github import ReleaseInfo, is_newer, parse_version

_LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


class MirrorError(Exception):
    """Raised when an APK could not be mirrored locally."""


@dataclass(slots=True)
class MirroredApk:
    """Metadata for one APK that is present on disk."""

    version: str
    tag: str
    flavor: str
    filename: str
    size: int
    sha256: str
    mirrored_at: str
    release_url: str
    prerelease: bool
    version_code: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MirroredApk | None:
        """Build an entry from stored JSON, ignoring malformed records."""
        try:
            return cls(
                version=str(data["version"]),
                tag=str(data.get("tag") or data["version"]),
                flavor=str(data["flavor"]),
                filename=str(data["filename"]),
                size=int(data.get("size") or 0),
                sha256=str(data.get("sha256") or ""),
                mirrored_at=str(data.get("mirrored_at") or ""),
                release_url=str(data.get("release_url") or ""),
                prerelease=bool(data.get("prerelease")),
                version_code=(
                    str(data["version_code"])
                    if data.get("version_code") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _sanitize_component(value: str) -> str:
    """Keep only characters that are safe inside a file name."""
    return "".join(
        char if char.isalnum() or char in {".", "-", "_"} else "_" for char in value
    )


def apk_filename(flavor: str, version: str) -> str:
    """Return the on-disk file name used for a mirrored APK."""
    return (
        f"home-assistant-companion-{_sanitize_component(flavor)}-"
        f"{_sanitize_component(version)}.apk"
    )


class ApkStore:
    """Owns the mirror directory under the Home Assistant configuration dir."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the store."""
        self.hass = hass
        self.path = Path(hass.config.path(STORAGE_SUBDIR))
        self._index_path = self.path / INDEX_FILENAME
        self._entries: list[MirroredApk] = []

    # ------------------------------------------------------------------
    # Index handling
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load the index from disk and drop entries whose file disappeared."""
        self._entries = await self.hass.async_add_executor_job(self._load_index)

    def _load_index(self) -> list[MirroredApk]:
        self.path.mkdir(parents=True, exist_ok=True)
        if not self._index_path.is_file():
            return []
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            _LOGGER.warning(
                "Could not read %s, starting empty: %s", self._index_path, err
            )
            return []

        entries: list[MirroredApk] = []
        for item in raw.get("entries") or []:
            if not isinstance(item, dict):
                continue
            entry = MirroredApk.from_dict(item)
            if entry is None:
                continue
            if (self.path / entry.filename).is_file():
                entries.append(entry)
        return sorted(
            entries, key=lambda item: parse_version(item.version), reverse=True
        )

    def _save_index(self, entries: list[MirroredApk]) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "entries": [asdict(entry) for entry in entries],
        }
        tmp = self._index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._index_path)

    async def _async_save_index(self) -> None:
        await self.hass.async_add_executor_job(self._save_index, list(self._entries))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def entries(self) -> list[MirroredApk]:
        """All mirrored APKs, newest first."""
        return list(self._entries)

    def latest(self, flavor: str | None = None) -> MirroredApk | None:
        """Newest mirrored APK, optionally restricted to one flavor."""
        for entry in self._entries:
            if flavor is None or entry.flavor == flavor:
                return entry
        return None

    def get(self, version: str, flavor: str | None = None) -> MirroredApk | None:
        """Look up a mirrored APK by version."""
        wanted = version.strip().lstrip("vV")
        for entry in self._entries:
            if entry.version == wanted and (flavor is None or entry.flavor == flavor):
                return entry
        return None

    def file_path(self, entry: MirroredApk) -> Path:
        """Absolute path of a mirrored APK."""
        return self.path / entry.filename

    def has_newer_upstream(self, release: ReleaseInfo | None) -> bool:
        """Return True when the upstream release is newer than what we mirror."""
        if release is None:
            return False
        current = self.latest(release.flavor)
        return is_newer(release.version, current.version if current else None)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def async_download(
        self,
        release: ReleaseInfo,
        *,
        progress: ProgressCallback | None = None,
    ) -> MirroredApk:
        """Download a release asset into the mirror directory.

        The file is streamed to ``<name>.part`` and atomically renamed, so a
        partial download never becomes servable. Returns the existing entry
        untouched when that version is already mirrored.
        """
        existing = self.get(release.version, release.flavor)
        if existing is not None and self.file_path(existing).is_file():
            _LOGGER.debug("Version %s is already mirrored", release.version)
            return existing

        filename = apk_filename(release.flavor, release.version)
        destination = self.path / filename
        partial = self.path / f"{filename}.part"

        await self.hass.async_add_executor_job(self._prepare_download, partial)

        session = async_get_clientsession(self.hass)
        digest = hashlib.sha256()
        written = 0

        try:
            # No Authorization header here on purpose: asset downloads redirect
            # to a separate CDN host and a GitHub token must not follow them.
            async with session.get(
                release.download_url,
                timeout=ClientTimeout(total=DOWNLOAD_TIMEOUT_SECONDS),
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or release.size or 0)
                handle = await self.hass.async_add_executor_job(
                    self._open_for_write, partial
                )
                try:
                    async for chunk in response.content.iter_chunked(
                        DOWNLOAD_CHUNK_SIZE
                    ):
                        await self.hass.async_add_executor_job(
                            self._write_chunk, handle, digest, chunk
                        )
                        written += len(chunk)
                        if progress is not None:
                            progress(written, total)
                finally:
                    await self.hass.async_add_executor_job(handle.close)
        except (ClientError, TimeoutError, OSError) as err:
            await self.hass.async_add_executor_job(self._remove_file, partial)
            raise MirrorError(
                f"Download of {release.asset_name} {release.version} failed: {err}"
            ) from err

        if release.size and written != release.size:
            await self.hass.async_add_executor_job(self._remove_file, partial)
            raise MirrorError(
                f"Download of {release.version} was truncated "
                f"({written} of {release.size} bytes)"
            )

        await self.hass.async_add_executor_job(os.replace, partial, destination)

        entry = MirroredApk(
            version=release.version,
            tag=release.tag,
            flavor=release.flavor,
            filename=filename,
            size=written,
            sha256=digest.hexdigest(),
            mirrored_at=dt_util.utcnow().isoformat(),
            release_url=release.release_url,
            prerelease=release.prerelease,
            version_code=await self._async_fetch_version_code(release),
        )

        self._entries = sorted(
            [item for item in self._entries if item.filename != filename] + [entry],
            key=lambda item: parse_version(item.version),
            reverse=True,
        )
        await self._async_save_index()
        _LOGGER.info(
            "Mirrored Home Assistant companion %s (%s) to %s",
            release.version,
            release.flavor,
            destination,
        )
        return entry

    async def async_purge(self, *, keep: int, flavor: str | None = None) -> list[str]:
        """Delete all but the newest ``keep`` APKs. Returns removed versions."""
        keep = max(1, keep)
        kept_per_flavor: dict[str, int] = {}
        removed: list[str] = []
        surviving: list[MirroredApk] = []

        for entry in self._entries:
            if flavor is not None and entry.flavor != flavor:
                surviving.append(entry)
                continue
            seen = kept_per_flavor.get(entry.flavor, 0)
            if seen < keep:
                kept_per_flavor[entry.flavor] = seen + 1
                surviving.append(entry)
                continue
            await self.hass.async_add_executor_job(
                self._remove_file, self.path / entry.filename
            )
            removed.append(entry.version)

        if removed:
            self._entries = surviving
            await self._async_save_index()
            _LOGGER.info("Purged mirrored APK versions: %s", ", ".join(removed))
        return removed

    # ------------------------------------------------------------------
    # Executor helpers
    # ------------------------------------------------------------------

    def _prepare_download(self, partial: Path) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)

    @staticmethod
    def _open_for_write(path: Path):
        return path.open("wb")

    @staticmethod
    def _write_chunk(handle, digest, chunk: bytes) -> None:
        handle.write(chunk)
        digest.update(chunk)

    @staticmethod
    def _remove_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as err:  # pragma: no cover - best effort cleanup
            _LOGGER.debug("Could not remove %s: %s", path, err)

    async def _async_fetch_version_code(self, release: ReleaseInfo) -> str | None:
        """Fetch the Android versionCode published alongside the APK."""
        if not release.version_code_url:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                release.version_code_url, timeout=ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                text = await response.text()
        except (ClientError, TimeoutError) as err:
            _LOGGER.debug("Could not read version_code.txt: %s", err)
            return None
        code = text.strip()
        return code if code.isdigit() else None
