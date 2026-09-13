"""Injectable CUPS CLI command runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CupsCommandTimeoutError(Exception):
    """CUPS command exceeded timeout."""


class CupsCommandRunner(Protocol):
    async def run(self, args: list[str], timeout_seconds: float) -> CommandResult:
        ...


class AsyncSubprocessCupsRunner:
    async def run(self, args: list[str], timeout_seconds: float) -> CommandResult:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CupsCommandTimeoutError(
                f"Command timed out after {timeout_seconds}s: {args[0]}"
            ) from None
        return CommandResult(
            returncode=proc.returncode or 0,
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
        )
