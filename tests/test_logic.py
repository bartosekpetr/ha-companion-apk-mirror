"""Tests for the release-selection helpers.

These run without Home Assistant installed:

    python3 tests/test_logic.py
    pytest tests/test_logic.py
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "companion_apk"
)


def _load_module(name: str):
    """Import one component module without executing the package __init__."""
    if "companion_apk" not in sys.modules:
        package = types.ModuleType("companion_apk")
        package.__path__ = [str(COMPONENT_DIR)]
        sys.modules["companion_apk"] = package
    qualified = f"companion_apk.{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(
        qualified, COMPONENT_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


const = _load_module("const")
github = _load_module("github")


def _release(
    tag: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    assets: list[str] | None = None,
    published_at: str = "2026-01-01T00:00:00Z",
) -> dict:
    names = (
        assets
        if assets is not None
        else ["app-full-release.apk", "app-minimal-release.apk", "version_code.txt"]
    )
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "published_at": published_at,
        "html_url": f"https://github.com/home-assistant/android/releases/tag/{tag}",
        "body": f"Notes for {tag}",
        "assets": [
            {
                "name": name,
                "size": 1000,
                "browser_download_url": f"https://example.invalid/{tag}/{name}",
            }
            for name in names
        ],
    }


# ----------------------------------------------------------------------
# parse_version / is_newer
# ----------------------------------------------------------------------


def test_parse_version_handles_calendar_versions() -> None:
    assert github.parse_version("2026.11.2") == (2026, 11, 2)
    assert github.parse_version("v2026.11.2") == (2026, 11, 2)
    assert github.parse_version("2026.11.10") > github.parse_version("2026.11.9")
    assert github.parse_version("2026.11.1") > github.parse_version("2026.9.9")


def test_parse_version_rejects_junk() -> None:
    assert github.parse_version(None) == (-1,)
    assert github.parse_version("") == (-1,)
    assert github.parse_version("nightly") == (-1,)
    assert github.parse_version("2026.11.2-beta") == (-1,)


def test_is_newer() -> None:
    assert github.is_newer("2026.11.2", "2026.11.1")
    assert github.is_newer("2026.11.10", "2026.11.9")
    assert github.is_newer("2026.1.1", None)
    assert not github.is_newer("2026.11.1", "2026.11.1")
    assert not github.is_newer("2026.10.1", "2026.11.1")
    assert not github.is_newer(None, "2026.11.1")


# ----------------------------------------------------------------------
# select_release
# ----------------------------------------------------------------------


def test_select_release_prefers_newest_stable() -> None:
    releases = [
        _release("2026.11.2", prerelease=True),
        _release("2026.11.1"),
        _release("2026.10.1"),
    ]
    chosen = github.select_release(
        releases, include_prereleases=False, asset_name="app-full-release.apk"
    )
    assert chosen["tag_name"] == "2026.11.1"


def test_select_release_can_include_prereleases() -> None:
    releases = [
        _release("2026.11.2", prerelease=True),
        _release("2026.11.1"),
    ]
    chosen = github.select_release(
        releases, include_prereleases=True, asset_name="app-full-release.apk"
    )
    assert chosen["tag_name"] == "2026.11.2"


def test_select_release_ignores_drafts() -> None:
    releases = [_release("2026.12.1", draft=True), _release("2026.11.1")]
    chosen = github.select_release(
        releases, include_prereleases=True, asset_name="app-full-release.apk"
    )
    assert chosen["tag_name"] == "2026.11.1"


def test_select_release_ignores_releases_without_the_asset() -> None:
    releases = [
        _release("2026.11.2", assets=["wear-release.apk"]),
        _release("2026.11.1"),
    ]
    chosen = github.select_release(
        releases, include_prereleases=False, asset_name="app-full-release.apk"
    )
    assert chosen["tag_name"] == "2026.11.1"


def test_select_release_returns_none_when_nothing_matches() -> None:
    assert (
        github.select_release(
            [], include_prereleases=True, asset_name="app-full-release.apk"
        )
        is None
    )
    assert (
        github.select_release(
            [_release("2026.11.1", assets=["version_code.txt"])],
            include_prereleases=True,
            asset_name="app-full-release.apk",
        )
        is None
    )


def test_select_release_is_not_fooled_by_api_ordering() -> None:
    # The GitHub API sorts by creation date; a patch for an older branch can be
    # published after a newer release.
    releases = [
        _release("2026.10.2", published_at="2026-11-20T00:00:00Z"),
        _release("2026.11.1", published_at="2026-11-02T00:00:00Z"),
    ]
    chosen = github.select_release(
        releases, include_prereleases=False, asset_name="app-full-release.apk"
    )
    assert chosen["tag_name"] == "2026.11.1"


# ----------------------------------------------------------------------
# find_release_by_version / release_from_payload
# ----------------------------------------------------------------------


def test_find_release_by_version() -> None:
    releases = [_release("2026.11.1"), _release("2026.10.1")]
    assert (
        github.find_release_by_version(
            releases, "2026.10.1", asset_name="app-full-release.apk"
        )["tag_name"]
        == "2026.10.1"
    )
    assert (
        github.find_release_by_version(
            releases, "v2026.10.1", asset_name="app-full-release.apk"
        )["tag_name"]
        == "2026.10.1"
    )
    assert (
        github.find_release_by_version(
            releases, "2025.1.1", asset_name="app-full-release.apk"
        )
        is None
    )


def test_release_from_payload_populates_asset_details() -> None:
    info = github.release_from_payload(_release("2026.11.1"), "full")
    assert info is not None
    assert info.version == "2026.11.1"
    assert info.asset_name == "app-full-release.apk"
    assert info.download_url.endswith("app-full-release.apk")
    assert info.size == 1000
    assert info.notes == "Notes for 2026.11.1"
    assert info.version_code_url is not None
    assert info.version_code_url.endswith("version_code.txt")


def test_release_from_payload_handles_missing_version_code() -> None:
    payload = _release("2026.11.1", assets=["app-minimal-release.apk"])
    info = github.release_from_payload(payload, "minimal")
    assert info is not None
    assert info.version_code_url is None


def test_release_from_payload_rejects_unknown_flavor() -> None:
    assert github.release_from_payload(_release("2026.11.1"), "nope") is None


def test_every_flavor_maps_to_a_distinct_asset() -> None:
    assets = list(const.FLAVOR_ASSETS.values())
    assert len(assets) == len(set(assets))
    assert const.DEFAULT_FLAVOR in const.FLAVOR_ASSETS


if __name__ == "__main__":
    failures = 0
    for test_name, test in sorted(globals().items()):
        if not test_name.startswith("test_") or not callable(test):
            continue
        try:
            test()
        except AssertionError as err:
            failures += 1
            print(f"FAIL {test_name}: {err}")
        else:
            print(f"ok   {test_name}")
    print("\n" + ("all tests passed" if not failures else f"{failures} failure(s)"))
    sys.exit(1 if failures else 0)
