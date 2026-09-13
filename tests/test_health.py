import pytest

from app.health import collect_health, set_agent_start_time
from app.mock_printer import MockPrinter


@pytest.mark.asyncio
async def test_health_snapshot(tmp_path):
    set_agent_start_time()
    printer = MockPrinter()
    snap = await collect_health(
        tmp_path, printer, backend_state=None, printer_mode="mock"
    )
    assert snap.process_ok is True
    assert snap.agent_version
    assert snap.hostname
    assert snap.uptime_seconds >= 0
    d = snap.to_dict()
    assert "agent_version" in d
    assert "printer_ok" in d
