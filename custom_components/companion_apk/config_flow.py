"""Config and options flow for the Companion App APK Mirror integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError, ClientTimeout
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_TIMEOUT_SECONDS,
    CONF_AUTO_DOWNLOAD,
    CONF_FLAVOR,
    CONF_GITHUB_TOKEN,
    CONF_INCLUDE_PRERELEASES,
    CONF_KEEP_VERSIONS,
    CONF_REQUIRE_AUTH,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_AUTO_DOWNLOAD,
    DEFAULT_FLAVOR,
    DEFAULT_INCLUDE_PRERELEASES,
    DEFAULT_KEEP_VERSIONS,
    DEFAULT_REQUIRE_AUTH,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    FLAVOR_ASSETS,
    GITHUB_RELEASES_URL,
    MAX_KEEP_VERSIONS,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_KEEP_VERSIONS,
    MIN_SCAN_INTERVAL_HOURS,
    RELEASES_PAGE_SIZE,
)
from .github import select_release

_LOGGER = logging.getLogger(__name__)

TITLE = "Companion App APK Mirror"


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the shared config/options schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_FLAVOR, default=defaults.get(CONF_FLAVOR, DEFAULT_FLAVOR)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(FLAVOR_ASSETS),
                    translation_key="flavor",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_AUTO_DOWNLOAD,
                default=defaults.get(CONF_AUTO_DOWNLOAD, DEFAULT_AUTO_DOWNLOAD),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_PRERELEASES,
                default=defaults.get(
                    CONF_INCLUDE_PRERELEASES, DEFAULT_INCLUDE_PRERELEASES
                ),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SCAN_INTERVAL_HOURS,
                default=defaults.get(
                    CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL_HOURS,
                    max=MAX_SCAN_INTERVAL_HOURS,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="h",
                )
            ),
            vol.Required(
                CONF_KEEP_VERSIONS,
                default=defaults.get(CONF_KEEP_VERSIONS, DEFAULT_KEEP_VERSIONS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_KEEP_VERSIONS,
                    max=MAX_KEEP_VERSIONS,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_REQUIRE_AUTH,
                default=defaults.get(CONF_REQUIRE_AUTH, DEFAULT_REQUIRE_AUTH),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_GITHUB_TOKEN,
                default=defaults.get(CONF_GITHUB_TOKEN, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


def _normalise(user_input: dict[str, Any]) -> dict[str, Any]:
    """Coerce the numeric selector values and trim the token."""
    data = dict(user_input)
    data[CONF_SCAN_INTERVAL_HOURS] = int(
        data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
    )
    data[CONF_KEEP_VERSIONS] = int(
        data.get(CONF_KEEP_VERSIONS, DEFAULT_KEEP_VERSIONS)
    )
    data[CONF_GITHUB_TOKEN] = str(data.get(CONF_GITHUB_TOKEN) or "").strip()
    return data


class CompanionApkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the build flavor and mirror behaviour."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalise(user_input)
            errors = await _async_validate(self.hass, data)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=TITLE, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> CompanionApkOptionsFlow:
        """Return the options flow."""
        return CompanionApkOptionsFlow()


class CompanionApkOptionsFlow(OptionsFlow):
    """Handle option changes."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the mirror options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalise(user_input)
            errors = await _async_validate(self.hass, data)
            if not errors:
                return self.async_create_entry(data=data)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(user_input or defaults),
            errors=errors,
        )


async def _async_validate(hass, data: dict[str, Any]) -> dict[str, str]:
    """Confirm GitHub is reachable and publishes the selected APK."""
    flavor = data.get(CONF_FLAVOR, DEFAULT_FLAVOR)
    asset_name = FLAVOR_ASSETS.get(flavor)
    if asset_name is None:
        return {CONF_FLAVOR: "unknown_flavor"}

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data.get(CONF_GITHUB_TOKEN):
        headers["Authorization"] = f"Bearer {data[CONF_GITHUB_TOKEN]}"

    session = async_get_clientsession(hass)
    try:
        async with session.get(
            GITHUB_RELEASES_URL,
            params={"per_page": str(RELEASES_PAGE_SIZE)},
            headers=headers,
            timeout=ClientTimeout(total=API_TIMEOUT_SECONDS),
        ) as response:
            if response.status in (401, 403):
                return {"base": "invalid_auth"}
            response.raise_for_status()
            payload = await response.json()
    except (ClientError, TimeoutError) as err:
        _LOGGER.debug("GitHub validation failed: %s", err)
        return {"base": "cannot_connect"}

    if not isinstance(payload, list):
        return {"base": "cannot_connect"}

    release = select_release(
        payload,
        include_prereleases=bool(data.get(CONF_INCLUDE_PRERELEASES)),
        asset_name=asset_name,
    )
    if release is None:
        return {CONF_FLAVOR: "no_release"}
    return {}
