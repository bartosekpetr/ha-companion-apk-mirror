"""Update entity that mirrors the newest companion app release on demand."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CompanionApkConfigEntry, CompanionApkCoordinator
from .entity import CompanionApkEntity
from .store import MirrorError

NOTHING_MIRRORED = "none"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionApkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the update entity."""
    async_add_entities([CompanionApkUpdateEntity(entry.runtime_data)])


class CompanionApkUpdateEntity(CompanionApkEntity, UpdateEntity):
    """Compares the mirrored APK against the newest upstream release.

    ``installed_version`` is the version held in the local mirror, not the
    version running on a particular tablet. Installing the update here makes
    the new APK available on the Home Assistant URL; the tablet then installs
    it from the local install page.
    """

    # The mirror's primary entity, so it carries the device name alone.
    _attr_name = None
    _attr_title = "Home Assistant Companion for Android"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.SPECIFIC_VERSION
    )

    def __init__(self, coordinator: CompanionApkCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator, "mirror")

    async def async_added_to_hass(self) -> None:
        """Subscribe to download progress."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_progress_listener(self._handle_progress)
        )

    @callback
    def _handle_progress(self, percentage: int | None) -> None:
        """Mirror download progress into the entity state."""
        self._attr_in_progress = percentage is not None
        self._attr_update_percentage = percentage
        self.async_write_ha_state()

    @property
    def installed_version(self) -> str | None:
        """Version currently mirrored locally.

        Reported as ``none`` rather than ``None`` when the mirror is empty:
        Home Assistant renders an update entity with an unknown installed
        version as simply unavailable, which would hide the Install button in
        exactly the case where it is needed most.
        """
        mirrored = self.coordinator.store.latest(self.coordinator.flavor)
        return mirrored.version if mirrored else NOTHING_MIRRORED

    @property
    def latest_version(self) -> str | None:
        """Newest version published upstream."""
        latest = self.coordinator.data.latest if self.coordinator.data else None
        return latest.version if latest else self.installed_version

    @property
    def release_url(self) -> str | None:
        """Link to the upstream release notes."""
        latest = self.coordinator.data.latest if self.coordinator.data else None
        return latest.release_url or None if latest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the local URLs so dashboards and automations can use them."""
        mirrored = self.coordinator.store.latest(self.coordinator.flavor)
        return {
            "flavor": self.coordinator.flavor,
            "local_url": self.local_apk_url,
            "install_page": self.install_page_url,
            "version_code": mirrored.version_code if mirrored else None,
            "sha256": mirrored.sha256 if mirrored else None,
        }

    async def async_release_notes(self) -> str | None:
        """Return the upstream changelog for the pending release."""
        latest = self.coordinator.data.latest if self.coordinator.data else None
        if latest is None or not latest.notes:
            return None
        return latest.notes

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Mirror the requested (or newest) release onto this Home Assistant."""
        try:
            await self.coordinator.async_download_version(version)
        except MirrorError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
