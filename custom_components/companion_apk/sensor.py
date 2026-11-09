"""Sensors describing the upstream release and the local mirror."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CompanionApkConfigEntry, CompanionApkCoordinator
from .entity import CompanionApkEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionApkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            LatestReleaseSensor(coordinator),
            MirroredVersionSensor(coordinator),
        ]
    )


class LatestReleaseSensor(CompanionApkEntity, SensorEntity):
    """Newest release published by home-assistant/android."""

    _attr_name = "Latest release"
    _attr_icon = "mdi:cloud-download-outline"

    def __init__(self, coordinator: CompanionApkCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "latest_release")

    @property
    def native_value(self) -> str | None:
        """Upstream version string."""
        latest = self.coordinator.data.latest if self.coordinator.data else None
        return latest.version if latest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details about the upstream release."""
        latest = self.coordinator.data.latest if self.coordinator.data else None
        if latest is None:
            return {}
        return {
            "tag": latest.tag,
            "flavor": latest.flavor,
            "asset": latest.asset_name,
            "size_bytes": latest.size,
            "published_at": latest.published_at,
            "prerelease": latest.prerelease,
            "release_url": latest.release_url,
        }


class MirroredVersionSensor(CompanionApkEntity, SensorEntity):
    """The APK version currently served from this Home Assistant."""

    _attr_name = "Mirrored version"
    _attr_icon = "mdi:android"

    def __init__(self, coordinator: CompanionApkCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "mirrored_version")

    @property
    def native_value(self) -> str | None:
        """Mirrored version string, or None when nothing is mirrored."""
        mirrored = self.coordinator.store.latest(self.coordinator.flavor)
        return mirrored.version if mirrored else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details about every APK held on disk."""
        mirrored = self.coordinator.store.latest(self.coordinator.flavor)
        attributes: dict[str, Any] = {
            "local_url": self.local_apk_url,
            "install_page": self.install_page_url,
            "mirror_path": str(self.coordinator.store.path),
            "available_versions": [
                entry.version for entry in self.coordinator.store.entries
            ],
        }
        if mirrored is not None:
            attributes |= {
                "flavor": mirrored.flavor,
                "filename": mirrored.filename,
                "size_bytes": mirrored.size,
                "sha256": mirrored.sha256,
                "version_code": mirrored.version_code,
                "mirrored_at": mirrored.mirrored_at,
                "prerelease": mirrored.prerelease,
            }
        return attributes
