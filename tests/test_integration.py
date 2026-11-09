"""End-to-end tests: set up the entry, mirror an APK, serve it over HTTP."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.companion_apk.const import (
    CONF_AUTO_DOWNLOAD,
    CONF_FLAVOR,
    CONF_INCLUDE_PRERELEASES,
    CONF_KEEP_VERSIONS,
    CONF_REQUIRE_AUTH,
    CONF_SCAN_INTERVAL_HOURS,
    DOMAIN,
    GITHUB_RELEASES_URL,
    RELEASES_PAGE_SIZE,
)

RELEASES_API_URL = f"{GITHUB_RELEASES_URL}?per_page={RELEASES_PAGE_SIZE}"
ASSET_HOST = "https://objects.githubusercontent.test"

APK_BODY = b"PK\x03\x04" + b"companion-apk-payload" * 64
OLD_APK_BODY = b"PK\x03\x04" + b"older-apk-payload" * 32

UPDATE_ENTITY = "update.companion_app_apk_mirror"
MIRRORED_SENSOR = "sensor.companion_app_apk_mirror_mirrored_version"
LATEST_SENSOR = "sensor.companion_app_apk_mirror_latest_release"


def _release(
    tag: str,
    *,
    prerelease: bool = False,
    assets: list[str] | None = None,
    body: bytes = APK_BODY,
) -> dict[str, Any]:
    names = assets or [
        "app-full-release.apk",
        "app-minimal-release.apk",
        "version_code.txt",
    ]
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": False,
        "published_at": "2026-01-01T00:00:00Z",
        "html_url": f"https://github.com/home-assistant/android/releases/tag/{tag}",
        "body": f"### Changes in {tag}\n\n- Something improved",
        "assets": [
            {
                "name": name,
                "size": len(body) if name.endswith(".apk") else 6,
                "browser_download_url": f"{ASSET_HOST}/{tag}/{name}",
            }
            for name in names
        ],
    }


def _mock_github(
    aioclient_mock: AiohttpClientMocker,
    releases: list[dict[str, Any]],
    *,
    bodies: dict[str, bytes] | None = None,
) -> None:
    """Mock the release list, the APK assets and version_code.txt."""
    payloads = bodies or {}
    for release in releases:
        for asset in release["assets"]:
            if asset["name"].endswith(".apk"):
                asset["size"] = len(payloads.get(release["tag_name"], APK_BODY))
    aioclient_mock.get(RELEASES_API_URL, json=releases)
    for release in releases:
        tag = release["tag_name"]
        for asset in release["assets"]:
            url = asset["browser_download_url"]
            if asset["name"].endswith(".apk"):
                body = payloads.get(tag, APK_BODY)
                aioclient_mock.get(
                    url,
                    content=body,
                    headers={"Content-Length": str(len(body))},
                )
            else:
                aioclient_mock.get(url, text="123456")


def _entry(**overrides: Any) -> MockConfigEntry:
    data = {
        CONF_FLAVOR: "full",
        CONF_AUTO_DOWNLOAD: True,
        CONF_INCLUDE_PRERELEASES: False,
        CONF_SCAN_INTERVAL_HOURS: 6,
        CONF_KEEP_VERSIONS: 2,
        CONF_REQUIRE_AUTH: False,
    }
    data.update(overrides)
    return MockConfigEntry(domain=DOMAIN, data=data, unique_id=DOMAIN, title="Mirror")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    # Auto-download runs as a background task, which the default
    # async_block_till_done() does not wait for.
    await hass.async_block_till_done(wait_background_tasks=True)


# ----------------------------------------------------------------------
# Setup and auto-download
# ----------------------------------------------------------------------


async def test_setup_mirrors_and_serves_the_apk(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth,
) -> None:
    """The newest release is mirrored and served on the Home Assistant URL."""
    _mock_github(aioclient_mock, [_release("2026.11.1"), _release("2026.10.1")])
    entry = _entry()
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED

    update_state = hass.states.get(UPDATE_ENTITY)
    assert update_state is not None
    assert update_state.attributes["installed_version"] == "2026.11.1"
    assert update_state.attributes["latest_version"] == "2026.11.1"
    assert update_state.state == "off"

    assert hass.states.get(LATEST_SENSOR).state == "2026.11.1"
    mirrored = hass.states.get(MIRRORED_SENSOR)
    assert mirrored.state == "2026.11.1"
    assert mirrored.attributes["version_code"] == "123456"
    assert mirrored.attributes["size_bytes"] == len(APK_BODY)

    apk_path = (
        entry.runtime_data.store.path
        / "home-assistant-companion-full-2026.11.1.apk"
    )
    assert apk_path.is_file()
    assert apk_path.read_bytes() == APK_BODY

    client = await hass_client_no_auth()

    response = await client.get("/api/companion_apk/latest.apk")
    assert response.status == HTTPStatus.OK
    assert response.headers["Content-Type"] == "application/vnd.android.package-archive"
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.headers["X-Apk-Version"] == "2026.11.1"
    assert await response.read() == APK_BODY

    manifest = await (await client.get("/api/companion_apk/manifest.json")).json()
    assert manifest["mirrored"]["version"] == "2026.11.1"
    assert manifest["mirrored"]["sha256"]
    assert manifest["upstream"]["version"] == "2026.11.1"
    assert manifest["available"][0]["version"] == "2026.11.1"

    landing = await client.get("/api/companion_apk/")
    assert landing.status == HTTPStatus.OK
    body = await landing.text()
    assert "2026.11.1" in body
    assert "/api/companion_apk/latest.apk" in body


async def test_prereleases_are_skipped_unless_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A pre-release is ignored with the default options."""
    _mock_github(
        aioclient_mock,
        [_release("2026.11.2", prerelease=True), _release("2026.11.1")],
    )
    await _setup(hass, _entry())
    assert hass.states.get(LATEST_SENSOR).state == "2026.11.1"


async def test_prereleases_can_be_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Enabling pre-releases picks up the beta."""
    _mock_github(
        aioclient_mock,
        [_release("2026.11.2", prerelease=True), _release("2026.11.1")],
    )
    await _setup(hass, _entry(**{CONF_INCLUDE_PRERELEASES: True}))
    assert hass.states.get(LATEST_SENSOR).state == "2026.11.2"


async def test_minimal_flavor_downloads_the_minimal_asset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The configured flavor decides which asset is mirrored."""
    _mock_github(aioclient_mock, [_release("2026.11.1")])
    entry = _entry(**{CONF_FLAVOR: "minimal"})
    await _setup(hass, entry)

    mirrored = entry.runtime_data.store.latest("minimal")
    assert mirrored is not None
    assert mirrored.flavor == "minimal"
    assert any(
        str(call[1]).endswith("app-minimal-release.apk")
        for call in aioclient_mock.mock_calls
    )


# ----------------------------------------------------------------------
# Manual install path
# ----------------------------------------------------------------------


async def test_manual_install_when_auto_download_is_off(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth,
) -> None:
    """With auto-download off, nothing is mirrored until Install is pressed."""
    _mock_github(aioclient_mock, [_release("2026.11.1")])
    await _setup(hass, _entry(**{CONF_AUTO_DOWNLOAD: False}))

    update_state = hass.states.get(UPDATE_ENTITY)
    assert update_state.attributes["installed_version"] == "none"
    assert update_state.state == "on"

    client = await hass_client_no_auth()
    missing = await client.get("/api/companion_apk/latest.apk")
    assert missing.status == HTTPStatus.NOT_FOUND

    await hass.services.async_call(
        "update", "install", {"entity_id": UPDATE_ENTITY}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(UPDATE_ENTITY).attributes["installed_version"] == "2026.11.1"
    served = await client.get("/api/companion_apk/latest.apk")
    assert served.status == HTTPStatus.OK
    assert await served.read() == APK_BODY


async def test_download_service_can_pin_a_version(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth,
) -> None:
    """A specific older release can be mirrored and fetched by version."""
    _mock_github(
        aioclient_mock,
        [_release("2026.11.1"), _release("2026.10.1")],
        bodies={"2026.10.1": OLD_APK_BODY},
    )
    await _setup(hass, _entry(**{CONF_AUTO_DOWNLOAD: False}))

    result = await hass.services.async_call(
        DOMAIN,
        "download",
        {"version": "2026.10.1"},
        blocking=True,
        return_response=True,
    )
    assert result["version"] == "2026.10.1"

    client = await hass_client_no_auth()
    response = await client.get("/api/companion_apk/apk/2026.10.1")
    assert response.status == HTTPStatus.OK
    assert await response.read() == OLD_APK_BODY


async def test_download_service_rejects_an_unknown_version(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Asking for a version that does not exist raises instead of guessing."""
    _mock_github(aioclient_mock, [_release("2026.11.1")])
    await _setup(hass, _entry(**{CONF_AUTO_DOWNLOAD: False}))

    with pytest.raises(Exception, match=r"2019\.1\.1"):
        await hass.services.async_call(
            DOMAIN, "download", {"version": "2019.1.1"}, blocking=True
        )


# ----------------------------------------------------------------------
# Retention
# ----------------------------------------------------------------------


async def test_old_versions_are_purged(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only the configured number of APKs is kept on disk."""
    _mock_github(
        aioclient_mock,
        [_release("2026.11.1"), _release("2026.10.1"), _release("2026.8.4")],
        bodies={"2026.10.1": OLD_APK_BODY},
    )
    entry = _entry(**{CONF_AUTO_DOWNLOAD: False, CONF_KEEP_VERSIONS: 2})
    await _setup(hass, entry)

    for version in ("2026.8.4", "2026.10.1", "2026.11.1"):
        await hass.services.async_call(
            DOMAIN, "download", {"version": version}, blocking=True
        )
        await hass.async_block_till_done()

    store = entry.runtime_data.store
    assert [item.version for item in store.entries] == ["2026.11.1", "2026.10.1"]
    assert not (
        store.path / "home-assistant-companion-full-2026.8.4.apk"
    ).exists()

    removed = await hass.services.async_call(
        DOMAIN, "purge", {"keep_versions": 1}, blocking=True, return_response=True
    )
    assert removed["removed"] == ["2026.10.1"]
    assert [item.version for item in store.entries] == ["2026.11.1"]


async def test_index_survives_a_reload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A mirrored APK is still known after Home Assistant reloads the entry."""
    _mock_github(aioclient_mock, [_release("2026.11.1")])
    entry = _entry()
    await _setup(hass, entry)
    assert entry.runtime_data.store.latest("full") is not None

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(MIRRORED_SENSOR).state == "2026.11.1"


# ----------------------------------------------------------------------
# Access control and failure modes
# ----------------------------------------------------------------------


async def test_require_auth_blocks_anonymous_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth,
    hass_client,
) -> None:
    """With the option on, the endpoints need a Home Assistant session."""
    _mock_github(aioclient_mock, [_release("2026.11.1")])
    await _setup(hass, _entry(**{CONF_REQUIRE_AUTH: True}))

    anonymous = await hass_client_no_auth()
    assert (
        await anonymous.get("/api/companion_apk/latest.apk")
    ).status == HTTPStatus.UNAUTHORIZED

    authenticated = await hass_client()
    response = await authenticated.get("/api/companion_apk/latest.apk")
    assert response.status == HTTPStatus.OK
    assert await response.read() == APK_BODY


async def test_github_failure_retries_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unreachable GitHub API leaves the entry in a retrying state."""
    aioclient_mock.get(RELEASES_API_URL, status=HTTPStatus.INTERNAL_SERVER_ERROR)
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_release_without_the_asset_is_reported_as_unknown(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A release that ships no matching APK does not crash the integration."""
    _mock_github(aioclient_mock, [_release("2026.11.1", assets=["wear-release.apk"])])
    await _setup(hass, _entry())

    assert hass.states.get(LATEST_SENSOR).state == "unknown"
    assert hass.states.get(MIRRORED_SENSOR).state == "unknown"


async def test_truncated_download_is_not_served(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_client_no_auth
) -> None:
    """A short body is rejected instead of being mirrored as a broken APK."""
    releases = [_release("2026.11.1")]
    aioclient_mock.get(RELEASES_API_URL, json=releases)
    for asset in releases[0]["assets"]:
        if asset["name"].endswith(".apk"):
            aioclient_mock.get(
                asset["browser_download_url"],
                content=b"truncated",
                headers={"Content-Length": "9"},
            )
        else:
            aioclient_mock.get(asset["browser_download_url"], text="123456")

    entry = _entry()
    await _setup(hass, entry)

    assert entry.runtime_data.store.latest("full") is None
    client = await hass_client_no_auth()
    assert (
        await client.get("/api/companion_apk/latest.apk")
    ).status == HTTPStatus.NOT_FOUND


async def test_unload_removes_services(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unloading the entry cleans up its services."""
    _mock_github(aioclient_mock, [_release("2026.11.1")])
    entry = _entry()
    await _setup(hass, entry)
    assert hass.services.has_service(DOMAIN, "download")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "download")
