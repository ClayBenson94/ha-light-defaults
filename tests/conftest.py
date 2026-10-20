"""Shared fixtures."""

import pytest

# When the `hass` fixture starts, Home Assistant imports `custom_components`
# from the test harness's own config dir unless it's already imported. Import
# this repo's first so HA can find custom_components/light_defaults.
import custom_components  # noqa: F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom integrations."""
    yield
