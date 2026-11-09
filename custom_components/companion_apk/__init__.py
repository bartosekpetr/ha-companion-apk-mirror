"""Mirror the Home Assistant Android companion app APK on the local network."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_VERSION,
    CONF_KEEP_VERSIONS,
    DOMAIN,
    MAX_KEEP_VERSIONS,
    MIN_KEEP_VERSIONS,
    SERVICE_DOWNLOAD,
    SERVICE_PURGE,
    SERVICE_REFRESH,
)
from .coordinator import CompanionApkConfigEntry, CompanionApkCoordinator
from .http_views import async_register_views
from .store import MirrorError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.UPDATE]

SERVICE_DOWNLOAD_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_VERSION): cv.string}
)
SERVICE_PURGE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_KEEP_VERSIONS): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_KEEP_VERSIONS, max=MAX_KEEP_VERSIONS)
        )
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CompanionApkConfigEntry
) -> bool:
    """Set up the integration from a config entry."""
    coordinator = CompanionApkCoordinator(hass, entry)
    await coordinator.async_prepare()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    async_register_views(hass)
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CompanionApkConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        for service in (SERVICE_DOWNLOAD, SERVICE_REFRESH, SERVICE_PURGE):
            hass.services.async_remove(DOMAIN, service)
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: CompanionApkConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_coordinator(hass: HomeAssistant) -> CompanionApkCoordinator:
    """Return the coordinator of the loaded config entry."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            return coordinator
    raise ServiceValidationError(
        "The Companion App APK Mirror integration is not loaded"
    )


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD):
        return

    async def _handle_download(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass)
        try:
            entry = await coordinator.async_download_version(
                call.data.get(ATTR_VERSION)
            )
        except MirrorError as err:
            raise HomeAssistantError(str(err)) from err
        return {
            "version": entry.version,
            "filename": entry.filename,
            "size": entry.size,
            "sha256": entry.sha256,
            "version_code": entry.version_code,
        }

    async def _handle_refresh(call: ServiceCall) -> None:
        await _resolve_coordinator(hass).async_request_refresh()

    async def _handle_purge(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass)
        removed = await coordinator.async_purge(call.data.get(CONF_KEEP_VERSIONS))
        return {"removed": removed}

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD,
        _handle_download,
        schema=SERVICE_DOWNLOAD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)
    hass.services.async_register(
        DOMAIN,
        SERVICE_PURGE,
        _handle_purge,
        schema=SERVICE_PURGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
