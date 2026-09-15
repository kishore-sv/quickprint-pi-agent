"""Injectable CUPS CLI command runner."""

from __future__ import annotations

import asyncio
import os
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
    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        self._extra_env = extra_env or {}

    def _subprocess_env(self) -> dict[str, str] | None:
        if not self._extra_env:
            return None
        env = os.environ.copy()
        env.update(self._extra_env)
        return env

    async def run(self, args: list[str], timeout_seconds: float) -> CommandResult:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
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
