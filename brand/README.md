# Brand assets

| File | What it is |
| --- | --- |
| `brand/icon.svg` | The source. Everything else is generated from it. |
| `custom_components/companion_apk/brand/icon.png` | 256×256, the file Home Assistant serves. |
| `custom_components/companion_apk/brand/icon@2x.png` | 512×512, same. |

The mark is two stacked sheets — the upstream release and the copy Home
Assistant keeps — with a download arrow on the local one.

No Home Assistant logo, wordmark or brand colour is used, so nobody mistakes
this for a first-party integration. This is the integration's own icon; it has
nothing to do with the mirrored APK, which is served byte-for-byte as published
upstream.

## Regenerating the PNGs

```bash
python3 scripts/render_brand_icon.py   # needs Pillow
```

Edit `brand/icon.svg`, re-run that, commit both. `tests/test_brand_icon.py`
fails if the PNGs leave the directory Home Assistant reads, stop matching the
expected sizes, or if the copy of the icon inlined in `http_views.py` drifts
from the SVG.

## How the icon reaches the Home Assistant UI

Since [Home Assistant 2026.3][blog], an integration ships its own brand images:
anything in `custom_components/<domain>/brand/` is served from
`/api/brands/integration/<domain>/`, and takes priority over the
`brands.home-assistant.io` CDN. That is why the PNGs live inside
`custom_components/companion_apk/brand/` rather than here — nothing else is
needed, and no pull request to another repository is involved.

The supported filenames are `icon.png`, `icon@2x.png`, `logo.png`,
`logo@2x.png` and their `dark_` variants. Only the two icon sizes are shipped:
the mark reads fine on light and dark backgrounds, so a `dark_` variant would
be the same image.

On Home Assistant older than 2026.3 the integration falls back to the generic
placeholder in **Settings → Devices & services**. Submitting the same two PNGs
to [home-assistant/brands][brands] under `custom_integrations/companion_apk/`
would cover those versions too; it is not required and has not been done.

[blog]: https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/
[brands]: https://github.com/home-assistant/brands
