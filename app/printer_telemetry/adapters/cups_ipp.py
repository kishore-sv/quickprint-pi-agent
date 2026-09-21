"""CUPS / lpstat / ipptool printer probe."""

from __future__ import annotations

import re
import shutil

from app.cups_command import CupsCommandRunner
from app.cups_discovery import parse_lpstat_printer_status
from app.logger import get_logger
from app.printer_telemetry.normalize import parse_reason_tokens
from app.printer_telemetry.types import AdapterProbeResult

log = get_logger("printer_telemetry.cups")


def _parse_lpstat_long(stdout: str) -> dict[str, str]:
    """Parse key lines from `lpstat -l -p <queue>`."""
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("printer-state:"):
            out["printer_state"] = stripped.split(":", 1)[1].strip()
        elif lower.startswith("printer-state-reasons:"):
            out["printer_state_reasons"] = stripped.split(":", 1)[1].strip()
        elif lower.startswith("printer-state-message:"):
            out["printer_state_message"] = stripped.split(":", 1)[1].strip()
        elif lower.startswith("printer-is-accepting-jobs:"):
            out["accepting"] = stripped.split(":", 1)[1].strip()
    return out


def _ipp_state_to_int(text: str | None) -> int | None:
    if not text:
        return None
    t = text.strip().lower()
    mapping = {
        "3": 3,
        "idle": 3,
        "4": 4,
        "processing": 4,
        "5": 5,
        "stopped": 5,
    }
    for key, val in mapping.items():
        if key in t:
            return val
    if t.isdigit():
        return int(t)
    return None


def _parse_device_uri_lpstat_v(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if "device for" in line.lower() and ":" in line:
            idx = line.find(":")
            rest = line[idx + 1 :].strip()
            if rest:
                return rest
    return None


def _parse_ipptool_output(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        m = re.match(r"^\s*printer-state\s*\(enum\)\s*=\s*(\d+)", line, re.I)
        if m:
            out["printer_state"] = m.group(1)
        m = re.match(
            r"^\s*printer-state-reasons\s*\([^)]+\)\s*=\s*(.+)$", line, re.I
        )
        if m:
            out["printer_state_reasons"] = m.group(1).strip()
        m = re.match(
            r"^\s*printer-make-and-model\s*\([^)]+\)\s*=\s*(.+)$", line, re.I
        )
        if m:
            out["make_and_model"] = m.group(1).strip().strip('"')
        m = re.match(r"^\s*device-uri\s*\([^)]+\)\s*=\s*(.+)$", line, re.I)
        if m:
            out["device_uri"] = m.group(1).strip().strip('"')
    return out


class CupsIppAdapter:
    def __init__(
        self,
        printer_name: str,
        runner: CupsCommandRunner,
        command_timeout_seconds: float,
    ) -> None:
        self._printer_name = printer_name
        self._runner = runner
        self._timeout = command_timeout_seconds

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

        try:
            sched = await self._runner.run(["lpstat", "-r"], self._timeout)
            result.scheduler_running = (
                sched.returncode == 0 and "scheduler is running" in sched.stdout.lower()
            )
        except Exception:
            result.scheduler_running = False

        try:
            lp_p = await self._runner.run(
                ["lpstat", "-p", self._printer_name], self._timeout
            )
            if lp_p.returncode != 0:
                result.queue_exists = False
            else:
                parsed = parse_lpstat_printer_status(lp_p.stdout)
                result.queue_exists = bool(parsed.get("exists"))
                result.enabled = bool(parsed.get("enabled", True))
                result.accepting_jobs = bool(parsed.get("accepting_jobs", True))
                result.cups_idle = bool(parsed.get("idle"))
                result.cups_printing = bool(parsed.get("printing"))
        except Exception as e:
            log.debug("lpstat -p failed: %s", e)
            result.queue_exists = False

        try:
            lp_l = await self._runner.run(
                ["lpstat", "-l", "-p", self._printer_name], self._timeout
            )
            if lp_l.returncode == 0:
                long_parsed = _parse_lpstat_long(lp_l.stdout)
                if "printer_state" in long_parsed:
                    result.ipp_printer_state = _ipp_state_to_int(
                        long_parsed["printer_state"]
                    )
                if "printer_state_reasons" in long_parsed:
                    result.raw_reasons = parse_reason_tokens(
                        long_parsed["printer_state_reasons"]
                    )
                if "printer_state_message" in long_parsed:
                    result.state_message = long_parsed["printer_state_message"]
                if "accepting" in long_parsed:
                    acc = long_parsed["accepting"].lower()
                    result.accepting_jobs = acc in ("true", "1", "yes")
        except Exception as e:
            log.debug("lpstat -l failed: %s", e)

        try:
            lp_v = await self._runner.run(
                ["lpstat", "-v", self._printer_name], self._timeout
            )
            if lp_v.returncode == 0:
                uri = _parse_device_uri_lpstat_v(lp_v.stdout)
                if uri:
                    result.device_uri = uri
        except Exception:
            pass

        device_for_ipp = result.device_uri or f"ipp://localhost/printers/{self._printer_name}"
        if shutil.which("ipptool"):
            try:
                ipp_args = [
                    "ipptool",
                    "-t",
                    device_for_ipp,
                    "get-printer-attributes.test",
                ]
                ipp = await self._runner.run(ipp_args, min(self._timeout, 10.0))
                if ipp.returncode == 0 and ipp.stdout:
                    ipp_parsed = _parse_ipptool_output(ipp.stdout)
                    if "printer_state" in ipp_parsed:
                        result.ipp_printer_state = _ipp_state_to_int(
                            ipp_parsed["printer_state"]
                        )
                    if "printer_state_reasons" in ipp_parsed:
                        result.raw_reasons = parse_reason_tokens(
                            ipp_parsed["printer_state_reasons"]
                        )
                    if "make_and_model" in ipp_parsed:
                        result.make_and_model = ipp_parsed["make_and_model"]
                    if "device_uri" in ipp_parsed:
                        result.device_uri = ipp_parsed["device_uri"]
            except Exception as e:
                log.debug("ipptool probe skipped: %s", e)

        if result.cups_printing and result.ipp_printer_state is None:
            result.ipp_printer_state = 4

        return result
