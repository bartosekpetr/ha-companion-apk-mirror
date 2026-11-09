"""Poll GitHub for companion app releases and keep the local mirror current."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_TIMEOUT_SECONDS,
    CONF_AUTO_DOWNLOAD,
    CONF_FLAVOR,
    CONF_GITHUB_TOKEN,
    CONF_INCLUDE_PRERELEASES,
    CONF_KEEP_VERSIONS,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_AUTO_DOWNLOAD,
    DEFAULT_FLAVOR,
    DEFAULT_INCLUDE_PRERELEASES,
    DEFAULT_KEEP_VERSIONS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    FLAVOR_ASSETS,
    GITHUB_RELEASES_URL,
    RELEASES_PAGE_SIZE,
)
from .github import (
    ReleaseInfo,
    find_release_by_version,
    release_from_payload,
    select_release,
)
from .store import ApkStore, MirroredApk, MirrorError

_LOGGER = logging.getLogger(__name__)

type CompanionApkConfigEntry = ConfigEntry["CompanionApkCoordinator"]


@dataclass(slots=True)
class CompanionApkData:
    """Snapshot handed to the entities on every coordinator refresh."""

    latest: ReleaseInfo | None
    mirrored: MirroredApk | None


class CompanionApkCoordinator(DataUpdateCoordinator[CompanionApkData]):
    """Keeps upstream release state and the on-disk mirror in sync."""

    config_entry: CompanionApkConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CompanionApkConfigEntry
    ) -> None:
        """Initialise the coordinator."""
        self.store = ApkStore(hass)
        self._download_lock = asyncio.Lock()
        self._progress_listeners: list[Callable[[int | None], None]] = []
        self._releases_cache: list[dict[str, Any]] = []

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                hours=self._option(
                    entry, CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                )
            ),
        )

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    @staticmethod
    def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
        if key in entry.options:
            return entry.options[key]
        return entry.data.get(key, default)

    def option(self, key: str, default: Any) -> Any:
        """Read an option, falling back to the original config entry data."""
        return self._option(self.config_entry, key, default)

    @property
    def flavor(self) -> str:
        """Configured build flavor."""
        flavor = self.option(CONF_FLAVOR, DEFAULT_FLAVOR)
        return flavor if flavor in FLAVOR_ASSETS else DEFAULT_FLAVOR

    @property
    def include_prereleases(self) -> bool:
        """Whether beta releases are considered."""
        return bool(self.option(CONF_INCLUDE_PRERELEASES, DEFAULT_INCLUDE_PRERELEASES))

    @property
    def auto_download(self) -> bool:
        """Whether new releases are mirrored without user interaction."""
        return bool(self.option(CONF_AUTO_DOWNLOAD, DEFAULT_AUTO_DOWNLOAD))

    @property
    def keep_versions(self) -> int:
        """How many APKs to retain per flavor."""
        try:
            return max(1, int(self.option(CONF_KEEP_VERSIONS, DEFAULT_KEEP_VERSIONS)))
        except (TypeError, ValueError):
            return DEFAULT_KEEP_VERSIONS

    # ------------------------------------------------------------------
    # Progress plumbing (used by the update entity)
    # ------------------------------------------------------------------

    def async_add_progress_listener(
        self, listener: Callable[[int | None], None]
    ) -> Callable[[], None]:
        """Register a download-progress listener and return its remover."""
        self._progress_listeners.append(listener)

        def _remove() -> None:
            if listener in self._progress_listeners:
                self._progress_listeners.remove(listener)

        return _remove

    def _notify_progress(self, percentage: int | None) -> None:
        for listener in list(self._progress_listeners):
            listener(percentage)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    async def async_prepare(self) -> None:
        """Load the on-disk index before the first refresh."""
        await self.store.async_load()

    async def _async_update_data(self) -> CompanionApkData:
        """Fetch upstream releases and reconcile with the mirror."""
        releases = await self._async_fetch_releases()
        self._releases_cache = releases

        asset_name = FLAVOR_ASSETS[self.flavor]
        payload = select_release(
            releases,
            include_prereleases=self.include_prereleases,
            asset_name=asset_name,
        )
        latest = release_from_payload(payload, self.flavor) if payload else None

        if latest is None:
            _LOGGER.warning(
                "No release of home-assistant/android publishes %s", asset_name
            )

        if (
            latest is not None
            and self.auto_download
            and self.store.has_newer_upstream(latest)
            and not self._download_lock.locked()
        ):
            self.config_entry.async_create_background_task(
                self.hass,
                self._async_auto_download(latest),
                name=f"{DOMAIN}_auto_download_{latest.version}",
            )

        return CompanionApkData(latest=latest, mirrored=self.store.latest(self.flavor))

    async def _async_fetch_releases(self) -> list[dict[str, Any]]:
        """Read the release list from the GitHub API."""
        session = async_get_clientsession(self.hass)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = self.option(CONF_GITHUB_TOKEN, "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with session.get(
                GITHUB_RELEASES_URL,
                params={"per_page": str(RELEASES_PAGE_SIZE)},
                headers=headers,
                timeout=ClientTimeout(total=API_TIMEOUT_SECONDS),
            ) as response:
                if response.status in (401, 403) and "rate limit" in (
                    await response.text()
                ).lower():
                    raise UpdateFailed(
                        "GitHub API rate limit reached. Add a personal access "
                        "token in the integration options, or poll less often."
                    )
                response.raise_for_status()
                payload = await response.json()
        except ClientResponseError as err:
            raise UpdateFailed(f"GitHub API returned HTTP {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Could not reach the GitHub API: {err}") from err

        if not isinstance(payload, list):
            raise UpdateFailed("Unexpected response from the GitHub API")
        return [item for item in payload if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------

    async def _async_auto_download(self, release: ReleaseInfo) -> None:
        try:
            await self.async_download(release)
        except MirrorError as err:
            _LOGGER.error("Automatic mirror of %s failed: %s", release.version, err)

    async def async_download(self, release: ReleaseInfo) -> MirroredApk:
        """Mirror a release, then prune old files and refresh the entities."""
        async with self._download_lock:
            last_reported = -1

            def _progress(written: int, total: int) -> None:
                # Called from the event loop while the response is streamed.
                nonlocal last_reported
                if not total:
                    return
                percentage = min(100, int(written * 100 / total))
                if percentage != last_reported:
                    last_reported = percentage
                    self._notify_progress(percentage)

            self._notify_progress(0)
            try:
                entry = await self.store.async_download(release, progress=_progress)
            finally:
                self._notify_progress(None)

            await self.store.async_purge(keep=self.keep_versions, flavor=release.flavor)

        self.async_set_updated_data(
            CompanionApkData(
                latest=self.data.latest if self.data else release,
                mirrored=self.store.latest(self.flavor),
            )
        )
        return entry

    async def async_download_version(self, version: str | None) -> MirroredApk:
        """Mirror a specific version, or the newest one when ``version`` is None."""
        asset_name = FLAVOR_ASSETS[self.flavor]

        if version is None:
            release = self.data.latest if self.data else None
            if release is None:
                await self.async_refresh()
                release = self.data.latest if self.data else None
            if release is None:
                raise MirrorError("No upstream release is currently known")
            return await self.async_download(release)

        releases = self._releases_cache or await self._async_fetch_releases()
        payload = find_release_by_version(releases, version, asset_name=asset_name)
        if payload is None:
            raise MirrorError(
                f"Release {version} was not found among the latest "
                f"{RELEASES_PAGE_SIZE} releases, or it does not publish {asset_name}"
            )
        release = release_from_payload(payload, self.flavor)
        if release is None:
            raise MirrorError(f"Release {version} does not publish {asset_name}")
        return await self.async_download(release)

    async def async_purge(self, keep: int | None = None) -> list[str]:
        """Remove old mirrored APKs."""
        removed = await self.store.async_purge(
            keep=self.keep_versions if keep is None else keep
        )
        if removed:
            self.async_set_updated_data(
                CompanionApkData(
                    latest=self.data.latest if self.data else None,
                    mirrored=self.store.latest(self.flavor),
                )
            )
        return removed
