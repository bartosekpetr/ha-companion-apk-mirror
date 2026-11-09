# Companion App APK Mirror

A Home Assistant custom integration that watches
[home-assistant/android](https://github.com/home-assistant/android) for new
releases, downloads the companion app APK onto your Home Assistant host, and
serves it from Home Assistant's own URL.

Built for the wall-tablet case: Home Assistant fetches the APK once, and the
tablet updates from `http://homeassistant.local:8123/api/companion_apk/`
instead of the Play Store.

## What you get

| Thing | Where |
| --- | --- |
| Install page for the tablet | `/api/companion_apk/` |
| The APK itself | `/api/companion_apk/latest.apk` |
| A specific version | `/api/companion_apk/apk/2026.11.1` |
| Mirror state as JSON | `/api/companion_apk/manifest.json` |
| `update.companion_app_apk_mirror` | Update entity: mirrored version vs. upstream, with release notes and an Install button |
| `sensor.companion_app_apk_mirror_latest_release` | Newest version published upstream |
| `sensor.companion_app_apk_mirror_mirrored_version` | Version currently served locally, with SHA-256, size and `versionCode` |
| `companion_apk.download` / `.refresh` / `.purge` | Services for automations |

APKs are stored in `<config>/companion_apk/`.

The update entity compares **what is mirrored locally** against **what is
published upstream** — it does not know what any individual tablet is running.
Before the first download it reports its installed version as `none`, so the
Install button is available straight away.

## Install

### HACS (custom repository)

1. HACS → three-dot menu → **Custom repositories**.
2. Add this repository's URL, category **Integration**.
3. Install **Companion App APK Mirror**, then restart Home Assistant.

### Manual

Copy `custom_components/companion_apk/` into your Home Assistant
`config/custom_components/` directory and restart.

### Configure

**Settings → Devices & services → Add integration → Companion App APK Mirror.**

| Option | Default | Notes |
| --- | --- | --- |
| Build flavor | `full` | `full` has Google services (FCM push); `minimal` does not. Also `automotive_full`, `automotive_minimal`, `wear`. |
| Download new releases automatically | on | Off means you press Install on the update entity. |
| Include beta releases | off | Upstream marks betas as pre-releases. |
| Check GitHub every | 6 h | 1–168 h. |
| Mirrored versions to keep | 2 | Older APKs are deleted. Keeping the previous one lets you roll back. |
| Require Home Assistant authentication | off | See [Security](#security). |
| GitHub token | empty | Only needed if you hit the anonymous 60 requests/hour API limit. |

All options are editable later via **Configure** without re-adding the
integration.

## Updating the tablet

1. On the tablet, open `http://<your-ha-host>:8123/api/companion_apk/`.
2. Tap the download button.
3. Android will ask to allow the browser to install unknown apps — allow it
   (`Settings → Apps → Special app access → Install unknown apps`).
4. Open the downloaded file and confirm.

See [docs/tablet-setup.md](docs/tablet-setup.md) for kiosk tablets, ADB-based
installs, and fully automated updates.

### Read this before the first install

**The APKs on GitHub are signed with the Home Assistant project's key, which is
not the key Google Play uses.** If the companion app on your tablet came from
the Play Store, Android will refuse to replace it
(`INSTALL_FAILED_UPDATE_INCOMPATIBLE`). You have to uninstall the Play Store
build first, which clears the app's local settings — the tablet will need to
log in to Home Assistant again. Once the GitHub build is installed, every
later update from this mirror upgrades in place.

The same applies to an F-Droid build: it uses yet another signing key.

## Automations

The update entity works with Home Assistant's normal update plumbing:

```yaml
automation:
  - alias: Tell me when a new companion APK is mirrored
    triggers:
      - trigger: state
        entity_id: sensor.companion_app_apk_mirror_mirrored_version
    conditions:
      - condition: template
        value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable'] }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: Companion app {{ trigger.to_state.state }} ready
          message: >-
            Open {{ state_attr('sensor.companion_app_apk_mirror_mirrored_version', 'install_page') }}
            on the tablet to install it.
```

Mirror a specific version, for example to roll back:

```yaml
action: companion_apk.download
data:
  version: "2026.10.1"
```

`companion_apk.download` and `companion_apk.purge` return a response, so you can
use `response_variable` to get the resulting version, file name and SHA-256.

## Security

The HTTP endpoints are unauthenticated by default, because a tablet's download
manager does not carry a Home Assistant token. They expose exactly one thing:
the public APK that anyone can download from GitHub anyway, plus its version
metadata. No Home Assistant state, tokens or configuration are reachable
through them.

If you would still rather lock them down, turn on **Require Home Assistant
authentication** in the options. Requests then need a valid Home Assistant
token or session, which means the plain "open the URL on the tablet" flow stops
working — use ADB or a token-carrying download instead.

A configured GitHub token is used only against `api.github.com`. It is
deliberately **not** sent with the asset download, because that request
redirects to a separate CDN host.

## Requirements

- Home Assistant 2025.2 or newer
- Outbound HTTPS from Home Assistant to `api.github.com` and
  `release-assets.githubusercontent.com` (where GitHub redirects release
  asset downloads)
- Roughly 50–130 MB of disk per kept version, depending on the flavor

## Development

```bash
# Pure release-selection logic, no Home Assistant needed
python3 tests/test_logic.py

# Full integration tests
uv venv .venv && uv pip install pytest-homeassistant-custom-component aioresponses
.venv/bin/python -m pytest tests -q
```

## License

MIT — see [LICENSE](LICENSE).

This project is not affiliated with the Home Assistant project. It redistributes
the official release artifacts unmodified on your own network.
