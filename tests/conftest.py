"""Test fixtures for the Companion App APK Mirror integration.

Home Assistant only discovers custom integrations inside its configuration
directory, so the test configuration directory is redirected to a temporary one
that links this repository's component.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component import common as phcc_common

pytest_plugins = ["pytest_homeassistant_custom_component"]

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_SOURCE = REPO_ROOT / "custom_components" / "companion_apk"

_TEST_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="companion_apk_test_config_"))
_CUSTOM_COMPONENTS = _TEST_CONFIG_DIR / "custom_components"
_CUSTOM_COMPONENTS.mkdir(parents=True, exist_ok=True)
(_CUSTOM_COMPONENTS / "companion_apk").symlink_to(
    COMPONENT_SOURCE, target_is_directory=True
)


def _get_test_config_dir(*add_path: str) -> str:
    """Return the temporary configuration directory used by the tests."""
    return str(_TEST_CONFIG_DIR.joinpath(*add_path))


phcc_common.get_test_config_dir = _get_test_config_dir


def pytest_sessionfinish(session, exitstatus) -> None:
    """Remove the temporary configuration directory."""
    shutil.rmtree(_TEST_CONFIG_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the custom integration in every test."""
    return


@pytest.fixture(autouse=True)
def clean_mirror_dir():
    """Start every test with an empty mirror directory."""
    mirror = _TEST_CONFIG_DIR / "companion_apk"
    shutil.rmtree(mirror, ignore_errors=True)
    yield
    shutil.rmtree(mirror, ignore_errors=True)
