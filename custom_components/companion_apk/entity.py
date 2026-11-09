"""Shared entity base for the Companion App APK Mirror integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, URL_LANDING_SLASH, URL_LATEST_APK
from .coordinator import CompanionApkCoordinator


def local_url(hass: HomeAssistant, path: str) -> str | None:
    """Build an absolute internal URL, or None when none is configured."""
    for prefer_external in (False, True):
        try:
            return f"{get_url(hass, prefer_external=prefer_external)}{path}"
        except NoURLAvailableError:
            continue
    return None


class CompanionApkEntity(CoordinatorEntity[CompanionApkCoordinator]):
    """Common device info and URL helpers."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CompanionApkCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Home Assistant",
            model="Companion app APK mirror",
            name="Companion App APK Mirror",
            configuration_url=local_url(coordinator.hass, URL_LANDING_SLASH),
        )

    @property
    def local_apk_url(self) -> str:
        """URL of the mirrored APK on this Home Assistant."""
        return local_url(self.coordinator.hass, URL_LATEST_APK) or URL_LATEST_APK

    @property
    def install_page_url(self) -> str:
        """URL of the tablet-friendly install page."""
        return local_url(self.coordinator.hass, URL_LANDING_SLASH) or URL_LANDING_SLASH
