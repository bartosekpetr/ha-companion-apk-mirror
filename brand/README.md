# Brand assets

| File | What it is |
| --- | --- |
| `icon.svg` | The source. Everything else is generated from it. |
| `icon.png` | 256×256, for [home-assistant/brands][brands]. |
| `icon@2x.png` | 512×512, same. |

The mark is two stacked sheets — the upstream release and the copy Home
Assistant keeps — with a download arrow on the local one.

No Home Assistant logo, wordmark or brand colour is used: the brands repository
requires custom integrations to stay visually distinct from official ones, so
nobody mistakes this for a first-party integration.

## Regenerating the PNGs

```bash
python3 scripts/render_brand_icon.py   # needs Pillow
```

Edit `icon.svg`, re-run that, commit both. `tests/test_brand_icon.py` fails if
the PNGs stop matching the sizes the brands repository expects, or if the copy
of the icon inlined in `http_views.py` drifts from this one.

## Getting the icon into the Home Assistant UI

Home Assistant does not read icons from an integration's own repository — the
frontend loads them from `brands.home-assistant.io`. Until the files below are
merged, the integration shows a generic placeholder in **Settings → Devices &
services**.

1. Fork [home-assistant/brands][brands].
2. Add `custom_integrations/companion_apk/icon.png` and
   `custom_integrations/companion_apk/icon@2x.png` from this directory.
   The directory name has to match the `domain` in `manifest.json`.
3. Open a pull request. Their CI checks dimensions, trimming and compression.

[brands]: https://github.com/home-assistant/brands
