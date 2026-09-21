"""Optional HPLIP hp-probe fallback for USB HP printers."""

from __future__ import annotations

import shutil

from app.cups_command import AsyncSubprocessCupsRunner
from app.logger import get_logger
from app.printer_telemetry.types import AdapterProbeResult

log = get_logger("printer_telemetry.hplip")

_HP_USB_MARKERS = ("hp:/", "usb://", "hplip", "hp laserjet", "hewlett")


def should_use_hplip(probe: AdapterProbeResult) -> bool:
    uri = (probe.device_uri or "").lower()
    model = (probe.make_and_model or "").lower()
    if any(m in uri for m in _HP_USB_MARKERS):
        return True
    if "hp " in model or model.startswith("hewlett"):
        return True
    return False


class HplipAdapter:
    def __init__(
        self,
        enabled: bool,
        probe_timeout_seconds: float = 2.0,
    ) -> None:
        self._enabled = enabled
        self._timeout = probe_timeout_seconds
        self._runner = AsyncSubprocessCupsRunner()

    async def probe(self, base: AdapterProbeResult) -> AdapterProbeResult:
        result = AdapterProbeResult(
            queue_exists=base.queue_exists,
            scheduler_running=base.scheduler_running,
            enabled=base.enabled,
            accepting_jobs=base.accepting_jobs,
            cups_idle=base.cups_idle,
            cups_printing=base.cups_printing,
            ipp_printer_state=base.ipp_printer_state,
            raw_reasons=list(base.raw_reasons),
            state_message=base.state_message,
            device_uri=base.device_uri,
            make_and_model=base.make_and_model,
            physical_usb_present=base.physical_usb_present,
            backend_unreachable=base.backend_unreachable,
        )

        if not self._enabled:
            return result
        if not should_use_hplip(result):
            return result
        if not shutil.which("hp-probe"):
            log.debug("HPLIP fallback unavailable (hp-probe missing)")
            return result

        try:
            cmd = await self._runner.run(
                ["hp-probe", "-b", "usb"], self._timeout
            )
            out = (cmd.stdout + cmd.stderr).lower()
            if "found" in out and "printer" in out:
                result.physical_usb_present = True
            elif "no devices found" in out:
                result.physical_usb_present = False
        except Exception as e:
            log.debug("hp-probe failed: %s", e)

        return result
