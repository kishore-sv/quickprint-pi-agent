"""Fake CUPS command runner for unit tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.cups_command import CommandResult, CupsCommandTimeoutError


@dataclass
class FakeCupsRunner:
    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    timeout_on: set[tuple[str, ...]] = field(default_factory=set)
    lp_call_count: int = 0

    async def run(self, args: list[str], timeout_seconds: float) -> CommandResult:
        self.calls.append(list(args))
        key = tuple(args)
        if key in self.timeout_on:
            raise CupsCommandTimeoutError("fake timeout")
        if args and args[0] == "lp":
            self.lp_call_count += 1
        if key in self.responses:
            return self.responses[key]
        if args[:2] == ["lpstat", "-p"]:
            return CommandResult(1, "", "Unknown printer")
        if args[:2] == ["lpstat", "-r"]:
            return CommandResult(0, "scheduler is running", "")
        if args[:2] == ["lpstat", "-o"] and len(args) == 3:
            return CommandResult(0, "", "")
        if args[:3] == ["lpstat", "-W", "completed"] and len(args) == 5:
            return CommandResult(0, "", "")
        if args[:2] == ["lpstat", "-o"]:
            return CommandResult(1, "", "Unable to locate printer")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "")
        return CommandResult(1, "", "unhandled fake command")
