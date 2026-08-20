"""Test fixtures for the Phyn integration.

The full Home Assistant test harness (pytest-homeassistant-custom-component)
is used when available (CI installs it via requirements_test.txt). Pure unit
tests — JNAP parsing, blueprint/manifest validation — run without it, so the
plugin import is optional here.
"""
import sys
from pathlib import Path

import pytest

# Add the project root to the Python path so imports work
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HAS_HA_TEST_PLUGIN = True
except ImportError:
    _HAS_HA_TEST_PLUGIN = False

if _HAS_HA_TEST_PLUGIN:
    pytest_plugins = "pytest_homeassistant_custom_component"

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable custom integrations."""
        yield
