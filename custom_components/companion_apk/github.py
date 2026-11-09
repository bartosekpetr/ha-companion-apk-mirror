"""GitHub release discovery for the Home Assistant Android companion app.

The pure helpers in this module (``parse_version``, ``select_release``,
``select_asset``, ``release_from_payload``) do not import Home Assistant and are
covered by ``tests/test_logic.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import FLAVOR_ASSETS, VERSION_CODE_ASSET


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    """A single upstream release, narrowed to the asset we care about."""

    version: str
    tag: str
    flavor: str
    asset_name: str
    download_url: str
    size: int
    published_at: str | None
    prerelease: bool
    release_url: str
    notes: str
    version_code_url: str | None


def parse_version(value: str | None) -> tuple[int, ...]:
    """Turn a release tag into a sortable tuple.

    Upstream uses calendar versions such as ``2026.11.2``. Anything that is not
    a plain dotted number sorts as ``(-1,)`` so it never wins a comparison with
    a well-formed version.
    """
    if not value:
        return (-1,)
    cleaned = value.strip().lstrip("vV")
    parts = cleaned.split(".")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return (-1,)
        numbers.append(int(part))
    return tuple(numbers) if numbers else (-1,)


def is_newer(candidate: str | None, current: str | None) -> bool:
    """Return True when ``candidate`` is a strictly newer version."""
    if not candidate:
        return False
    if not current:
        return True
    parsed_candidate = parse_version(candidate)
    parsed_current = parse_version(current)
    if parsed_candidate == (-1,) or parsed_current == (-1,):
        # Fall back to a plain string compare for non-numeric tags so the
        # integration still behaves deterministically.
        return candidate != current and candidate > current
    return parsed_candidate > parsed_current


def _published_sort_key(release: dict[str, Any]) -> tuple[tuple[int, ...], str]:
    return (
        parse_version(release.get("tag_name")),
        str(release.get("published_at") or ""),
    )


def select_release(
    releases: list[dict[str, Any]],
    *,
    include_prereleases: bool,
    asset_name: str,
) -> dict[str, Any] | None:
    """Pick the newest usable release that actually ships ``asset_name``."""
    candidates = [
        release
        for release in releases
        if isinstance(release, dict)
        and not release.get("draft")
        and (include_prereleases or not release.get("prerelease"))
        and select_asset(release, asset_name) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=_published_sort_key)


def find_release_by_version(
    releases: list[dict[str, Any]],
    version: str,
    *,
    asset_name: str,
) -> dict[str, Any] | None:
    """Find a specific release by tag, ignoring an optional ``v`` prefix."""
    wanted = version.strip().lstrip("vV")
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "").lstrip("vV")
        if tag == wanted and select_asset(release, asset_name) is not None:
            return release
    return None


def select_asset(release: dict[str, Any], asset_name: str) -> dict[str, Any] | None:
    """Return the named asset of a release, if present."""
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == asset_name:
            return asset
    return None


def release_from_payload(release: dict[str, Any], flavor: str) -> ReleaseInfo | None:
    """Convert a GitHub release payload into a :class:`ReleaseInfo`."""
    asset_name = FLAVOR_ASSETS.get(flavor)
    if asset_name is None:
        return None
    asset = select_asset(release, asset_name)
    if asset is None or not asset.get("browser_download_url"):
        return None

    version_code_asset = select_asset(release, VERSION_CODE_ASSET)
    tag = str(release.get("tag_name") or "")

    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        flavor=flavor,
        asset_name=asset_name,
        download_url=str(asset["browser_download_url"]),
        size=int(asset.get("size") or 0),
        published_at=release.get("published_at"),
        prerelease=bool(release.get("prerelease")),
        release_url=str(release.get("html_url") or ""),
        notes=str(release.get("body") or ""),
        version_code_url=(
            str(version_code_asset["browser_download_url"])
            if version_code_asset and version_code_asset.get("browser_download_url")
            else None
        ),
    )
