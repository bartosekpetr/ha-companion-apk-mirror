# Updating a wall tablet from the local mirror

Three ways to get the mirrored APK onto a tablet, from least to most automated.

## 1. Tap it (no extra setup)

Open `http://<your-ha-host>:8123/api/companion_apk/` on the tablet and tap the
download button.

The first time, Android asks whether the browser may install unknown apps.
Grant it under **Settings → Apps → Special app access → Install unknown
apps → <your browser> → Allow**.

If you run the tablet in a kiosk launcher that blocks the browser, add a
dashboard button instead:

```yaml
type: button
name: Update companion app
icon: mdi:android
tap_action:
  action: url
  url_path: /api/companion_apk/latest.apk
```

## 2. ADB over the network

Useful when the tablet is wall-mounted and you would rather not touch it.
Enable **Developer options → Wireless debugging** on the tablet, then from any
machine on the LAN:

```bash
HA=http://homeassistant.local:8123
curl -fL -o companion.apk "$HA/api/companion_apk/latest.apk"

adb connect <tablet-ip>:5555
adb install -r companion.apk      # -r upgrades in place
```

`adb install -r` fails with `INSTALL_FAILED_UPDATE_INCOMPATIBLE` if the
installed app came from Google Play. Uninstall it first
(`adb uninstall io.homeassistant.companion.android`) and be aware that this
clears the app's settings.

Verify what you downloaded before installing:

```bash
curl -fsS "$HA/api/companion_apk/manifest.json" | jq .
sha256sum companion.apk
```

## 3. Fully automated with the ADB integration

With Home Assistant's
[Android Debug Bridge](https://www.home-assistant.io/integrations/androidtv/)
integration set up for the tablet, the mirror can drive the install itself.

```yaml
automation:
  - alias: Push the mirrored companion APK to the hallway tablet
    triggers:
      - trigger: state
        entity_id: sensor.companion_app_apk_mirror_mirrored_version
    conditions:
      - condition: template
        value_template: >-
          {{ trigger.from_state.state not in ['unknown', 'unavailable', 'none'] }}
    actions:
      - action: androidtv.adb_command
        target:
          entity_id: media_player.hallway_tablet
        data:
          command: >-
            curl -fL -o /data/local/tmp/companion.apk
            http://homeassistant.local:8123/api/companion_apk/latest.apk
            && pm install -r /data/local/tmp/companion.apk
```

Notes:

- The tablet needs `curl` (most Android 11+ builds have it) and ADB enabled.
- `pm install -r` requires the APK to be readable by the shell user, which is
  why it is staged in `/data/local/tmp`.
- Reinstalling the app that is currently displaying your dashboard will close
  it; the kiosk launcher should bring it back.

## Rolling back

The mirror keeps the previous APK by default. List what is on disk and install
an older build:

```bash
curl -fsS "$HA/api/companion_apk/manifest.json" | jq '.available'
curl -fL -o rollback.apk "$HA/api/companion_apk/apk/2026.10.1"
```

If a version has already been purged, pull it back from GitHub:

```yaml
action: companion_apk.download
data:
  version: "2026.10.1"
```

Downgrading needs an uninstall first — Android will not replace an app with a
lower `versionCode`.

## Which flavor?

| Flavor | Asset | Use when |
| --- | --- | --- |
| `full` | `app-full-release.apk` | The tablet has Google Play services. Push notifications work via FCM. |
| `minimal` | `app-minimal-release.apk` | De-Googled tablet, custom ROM, or Amazon Fire. No FCM, so notifications need the local push/WebSocket path. |
| `automotive_full` / `automotive_minimal` | `automotive-*-release.apk` | Android Automotive head units. |
| `wear` | `wear-release.apk` | Wear OS watches. |

Switching flavor later changes which asset is mirrored, but Android treats the
two builds as different signatures in some cases — expect an uninstall when
moving between `full` and `minimal`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `404` from `/latest.apk` | Nothing mirrored yet. Press Install on `update.companion_app_apk_mirror` or call `companion_apk.download`. |
| `401` from the endpoints | **Require Home Assistant authentication** is on. Turn it off, or supply a bearer token. |
| `503` from the endpoints | The config entry is not loaded — check the Home Assistant log. |
| "App not installed" on the tablet | Signature mismatch with the Play Store build. Uninstall the existing app first. |
| Update entity stuck on an old version | GitHub API rate limit. Add a token in the options, or increase the check interval. |
| Download fails repeatedly | Home Assistant cannot reach `release-assets.githubusercontent.com`; check DNS and any egress filtering. |
