"""Optional Linux/CUPS integration tests — skipped on Mac without CUPS."""

import platform
import shutil

import pytest

pytestmark = pytest.mark.skipif(
    platform.system() != "Linux" or shutil.which("lpstat") is None,
    reason="CUPS integration requires Linux with lpstat",
)


@pytest.mark.asyncio
async def test_lpstat_available():
    """Placeholder for manual Pi verification."""
    assert shutil.which("lpstat") is not None
