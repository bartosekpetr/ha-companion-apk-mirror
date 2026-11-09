"""Constants for the Companion App APK Mirror integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "companion_apk"

GITHUB_OWNER: Final = "home-assistant"
GITHUB_REPO: Final = "android"
GITHUB_API_BASE: Final = "https://api.github.com"
GITHUB_RELEASES_URL: Final = (
    f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
)

# Configuration / option keys
CONF_FLAVOR: Final = "flavor"
CONF_INCLUDE_PRERELEASES: Final = "include_prereleases"
CONF_AUTO_DOWNLOAD: Final = "auto_download"
CONF_KEEP_VERSIONS: Final = "keep_versions"
CONF_SCAN_INTERVAL_HOURS: Final = "scan_interval_hours"
CONF_REQUIRE_AUTH: Final = "require_auth"
CONF_GITHUB_TOKEN: Final = "github_token"

# Each release of home-assistant/android publishes one APK per build flavor.
# Keys are stable option values, values are the published asset file names.
FLAVOR_ASSETS: Final[dict[str, str]] = {
    "full": "app-full-release.apk",
    "minimal": "app-minimal-release.apk",
    "automotive_full": "automotive-full-release.apk",
    "automotive_minimal": "automotive-minimal-release.apk",
    "wear": "wear-release.apk",
}

VERSION_CODE_ASSET: Final = "version_code.txt"

DEFAULT_FLAVOR: Final = "full"
DEFAULT_INCLUDE_PRERELEASES: Final = False
DEFAULT_AUTO_DOWNLOAD: Final = True
DEFAULT_KEEP_VERSIONS: Final = 2
DEFAULT_SCAN_INTERVAL_HOURS: Final = 6
DEFAULT_REQUIRE_AUTH: Final = False

MIN_KEEP_VERSIONS: Final = 1
MAX_KEEP_VERSIONS: Final = 10
MIN_SCAN_INTERVAL_HOURS: Final = 1
MAX_SCAN_INTERVAL_HOURS: Final = 168

# Where mirrored APKs live, relative to the Home Assistant configuration dir.
STORAGE_SUBDIR: Final = "companion_apk"
INDEX_FILENAME: Final = "index.json"
INDEX_VERSION: Final = 1

# How many releases to inspect when looking for the newest matching one.
RELEASES_PAGE_SIZE: Final = 30

DOWNLOAD_CHUNK_SIZE: Final = 262144  # 256 KiB
DOWNLOAD_TIMEOUT_SECONDS: Final = 1800
API_TIMEOUT_SECONDS: Final = 30

APK_CONTENT_TYPE: Final = "application/vnd.android.package-archive"

# Public HTTP endpoints exposed on the Home Assistant URL.
URL_BASE: Final = "/api/companion_apk"
URL_LANDING: Final = URL_BASE
URL_LANDING_SLASH: Final = f"{URL_BASE}/"
URL_LATEST_APK: Final = f"{URL_BASE}/latest.apk"
URL_MANIFEST: Final = f"{URL_BASE}/manifest.json"
URL_VERSIONED_APK: Final = URL_BASE + "/apk/{version}"

SERVICE_DOWNLOAD: Final = "download"
SERVICE_REFRESH: Final = "refresh"
SERVICE_PURGE: Final = "purge"

ATTR_VERSION: Final = "version"
