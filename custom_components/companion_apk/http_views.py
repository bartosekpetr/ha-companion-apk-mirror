"""HTTP endpoints that serve the mirrored APK from the Home Assistant URL."""

from __future__ import annotations

import logging
from html import escape
from typing import TYPE_CHECKING

from aiohttp import hdrs, web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    APK_CONTENT_TYPE,
    CONF_REQUIRE_AUTH,
    DEFAULT_REQUIRE_AUTH,
    DOMAIN,
    URL_LANDING,
    URL_LANDING_SLASH,
    URL_LATEST_APK,
    URL_MANIFEST,
    URL_VERSIONED_APK,
)
from .store import MirroredApk

if TYPE_CHECKING:
    from .coordinator import CompanionApkCoordinator

_LOGGER = logging.getLogger(__name__)

VIEWS_REGISTERED_KEY = f"{DOMAIN}_views_registered"

FLAVOR_LABELS = {
    "full": "Phone/tablet - full (with Google services)",
    "minimal": "Phone/tablet - minimal (no Google services)",
    "automotive_full": "Android Automotive - full",
    "automotive_minimal": "Android Automotive - minimal",
    "wear": "Wear OS",
}


def async_register_views(hass: HomeAssistant) -> None:
    """Register the public views once per Home Assistant run.

    Home Assistant cannot unregister an HTTP view, so registration is guarded
    and the views resolve the active coordinator on every request instead of
    capturing it.
    """
    if hass.data.get(VIEWS_REGISTERED_KEY):
        return
    hass.http.register_view(CompanionApkLandingView())
    hass.http.register_view(CompanionApkDownloadView())
    hass.http.register_view(CompanionApkVersionedDownloadView())
    hass.http.register_view(CompanionApkManifestView())
    hass.data[VIEWS_REGISTERED_KEY] = True


def _coordinator(request: web.Request) -> CompanionApkCoordinator | None:
    """Return the coordinator of the loaded config entry, if any."""
    hass: HomeAssistant = request.app[KEY_HASS]
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            return coordinator
    return None


def _check_auth(
    request: web.Request, coordinator: CompanionApkCoordinator
) -> None:
    """Enforce the optional "require Home Assistant login" option.

    The views are registered with ``requires_auth = False`` so the setting can
    change without restarting Home Assistant; Home Assistant's auth middleware
    still populates the authenticated user when a token is supplied.
    """
    if not coordinator.option(CONF_REQUIRE_AUTH, DEFAULT_REQUIRE_AUTH):
        return
    if request.get("hass_user") is not None:
        return
    raise web.HTTPUnauthorized(
        text=(
            "This endpoint requires a Home Assistant login. Disable "
            '"Require Home Assistant authentication" in the integration '
            "options to let a tablet download the APK directly."
        )
    )


def _resolve(
    request: web.Request, version: str | None = None
) -> tuple[CompanionApkCoordinator, MirroredApk]:
    """Find the coordinator and the mirrored APK a request refers to."""
    coordinator = _coordinator(request)
    if coordinator is None:
        raise web.HTTPServiceUnavailable(
            text="The Companion App APK Mirror integration is not loaded."
        )
    _check_auth(request, coordinator)

    entry = (
        coordinator.store.get(version)
        if version
        else coordinator.store.latest(coordinator.flavor)
    )
    if entry is None or not coordinator.store.file_path(entry).is_file():
        raise web.HTTPNotFound(
            text=(
                "No APK has been mirrored yet. Install the update from the "
                "Home Assistant UI, or call the companion_apk.download service."
            )
        )
    return coordinator, entry


def _apk_response(
    coordinator: CompanionApkCoordinator, entry: MirroredApk
) -> web.FileResponse:
    """Serve an APK with the headers Android needs to offer installation."""
    return web.FileResponse(
        coordinator.store.file_path(entry),
        headers={
            hdrs.CONTENT_TYPE: APK_CONTENT_TYPE,
            hdrs.CONTENT_DISPOSITION: (
                f'attachment; filename="{entry.filename}"'
            ),
            hdrs.CACHE_CONTROL: "no-cache",
            "X-Apk-Version": entry.version,
            "X-Apk-Sha256": entry.sha256,
            "X-Apk-Flavor": entry.flavor,
        },
    )


class CompanionApkDownloadView(HomeAssistantView):
    """Serve the newest mirrored APK."""

    url = URL_LATEST_APK
    name = f"api:{DOMAIN}:latest"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Stream the newest mirrored APK."""
        coordinator, entry = _resolve(request)
        return _apk_response(coordinator, entry)


class CompanionApkVersionedDownloadView(HomeAssistantView):
    """Serve a specific mirrored APK version."""

    url = URL_VERSIONED_APK
    name = f"api:{DOMAIN}:versioned"
    requires_auth = False

    async def get(self, request: web.Request, version: str) -> web.StreamResponse:
        """Stream one mirrored APK by version."""
        coordinator, entry = _resolve(request, version.removesuffix(".apk"))
        return _apk_response(coordinator, entry)


class CompanionApkManifestView(HomeAssistantView):
    """Machine-readable description of what is mirrored."""

    url = URL_MANIFEST
    name = f"api:{DOMAIN}:manifest"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Return mirror metadata as JSON."""
        coordinator = _coordinator(request)
        if coordinator is None:
            raise web.HTTPServiceUnavailable(
                text="The Companion App APK Mirror integration is not loaded."
            )
        _check_auth(request, coordinator)

        data = coordinator.data
        latest = data.latest if data else None
        mirrored = coordinator.store.latest(coordinator.flavor)

        return self.json(
            {
                "flavor": coordinator.flavor,
                "upstream": (
                    {
                        "version": latest.version,
                        "published_at": latest.published_at,
                        "prerelease": latest.prerelease,
                        "release_url": latest.release_url,
                        "size": latest.size,
                    }
                    if latest
                    else None
                ),
                "mirrored": (
                    {
                        "version": mirrored.version,
                        "version_code": mirrored.version_code,
                        "filename": mirrored.filename,
                        "size": mirrored.size,
                        "sha256": mirrored.sha256,
                        "mirrored_at": mirrored.mirrored_at,
                        "prerelease": mirrored.prerelease,
                        "url": URL_LATEST_APK,
                    }
                    if mirrored
                    else None
                ),
                "available": [
                    {
                        "version": item.version,
                        "flavor": item.flavor,
                        "size": item.size,
                        "sha256": item.sha256,
                        "url": URL_VERSIONED_APK.format(version=item.version),
                    }
                    for item in coordinator.store.entries
                ],
            }
        )


class CompanionApkLandingView(HomeAssistantView):
    """A small page a tablet can open to install the mirrored APK."""

    url = URL_LANDING
    extra_urls = [URL_LANDING_SLASH]  # noqa: RUF012 - Home Assistant API
    name = f"api:{DOMAIN}:landing"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Render the install page."""
        coordinator = _coordinator(request)
        if coordinator is None:
            raise web.HTTPServiceUnavailable(
                text="The Companion App APK Mirror integration is not loaded."
            )
        _check_auth(request, coordinator)

        data = coordinator.data
        latest = data.latest if data else None
        mirrored = coordinator.store.latest(coordinator.flavor)
        return web.Response(
            text=_render_page(coordinator.flavor, latest, mirrored),
            content_type="text/html",
            headers={hdrs.CACHE_CONTROL: "no-store"},
        )


def _format_size(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB" if size else "unknown size"


def _render_page(flavor: str, latest, mirrored: MirroredApk | None) -> str:
    """Build the (self-contained, no external assets) install page."""
    flavor_label = escape(FLAVOR_LABELS.get(flavor, flavor))

    if mirrored is not None:
        action = (
            f'<a class="cta" href="{escape(URL_LATEST_APK)}">'
            f"Download {escape(mirrored.version)}</a>"
        )
        details = f"""
        <dl>
          <dt>Mirrored version</dt><dd>{escape(mirrored.version)}</dd>
          <dt>Build</dt><dd>{flavor_label}</dd>
          <dt>Android versionCode</dt>
          <dd>{escape(mirrored.version_code or "unknown")}</dd>
          <dt>Size</dt><dd>{escape(_format_size(mirrored.size))}</dd>
          <dt>SHA-256</dt><dd class="hash">{escape(mirrored.sha256)}</dd>
        </dl>"""
    else:
        action = '<p class="empty">Nothing mirrored yet.</p>'
        details = (
            "<p>Install the update from <strong>Settings &rarr; Devices &amp; "
            "services &rarr; Companion App APK Mirror</strong>, or call the "
            "<code>companion_apk.download</code> service, then reload this "
            "page.</p>"
        )

    if latest is not None and (
        mirrored is None or mirrored.version != latest.version
    ):
        upstream = (
            f'<p class="notice">Upstream release {escape(latest.version)} '
            f"({escape(_format_size(latest.size))}) has not been mirrored yet.</p>"
        )
    else:
        upstream = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Home Assistant Companion - local install</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 24px; line-height: 1.5; max-width: 42rem;
         margin-inline: auto; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  p.sub {{ margin: 0 0 1.5rem; opacity: .7; }}
  .cta {{ display: block; text-align: center; padding: 1rem 1.25rem;
          border-radius: 12px; background: #03a9f4; color: #fff;
          font-size: 1.1rem; font-weight: 600; text-decoration: none;
          margin: 1.5rem 0; }}
  .cta:active {{ filter: brightness(.9); }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1rem;
        margin: 0 0 1.5rem; }}
  dt {{ opacity: .65; }}
  dd {{ margin: 0; }}
  dd.hash {{ font-family: ui-monospace, monospace; font-size: .75rem;
             overflow-wrap: anywhere; }}
  .notice, .empty {{ padding: .75rem 1rem; border-radius: 8px;
                     background: rgba(255,152,0,.15); }}
  ol {{ padding-left: 1.25rem; }}
  footer {{ margin-top: 2rem; font-size: .8rem; opacity: .65; }}
  code {{ font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<h1>Home Assistant Companion</h1>
<p class="sub">Served locally by your Home Assistant instance.</p>
{upstream}
{action}
{details}
<h2>Installing on this device</h2>
<ol>
  <li>Tap the download button above.</li>
  <li>Allow this browser to <em>install unknown apps</em> when Android asks.</li>
  <li>Open the downloaded file and confirm the installation.</li>
</ol>
<footer>
  These APKs are built and signed by the Home Assistant project. If the
  companion app was installed from Google Play, Android will refuse to replace
  it because the signing keys differ - uninstall the Play Store build first.
</footer>
</body>
</html>"""
