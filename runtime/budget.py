import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from runtime.errors import BudgetExceededError


def estimate_tokens(value: Any) -> int:
    if value is None:
        return 0

    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True)

    if not text:
        return 0

    return max(1, math.ceil(len(text) / 4))


@dataclass
class RunBudget:
    max_steps: int | None = None
    max_tool_calls: int | None = None
    max_tokens: int | None = None
    max_wall_clock_ms: int | None = None
    started_at: float = field(default_factory=time.perf_counter)
    steps_used: int = 0
    tool_calls_used: int = 0
    tokens_used: int = 0

    def ensure_wall_clock_remaining(self) -> None:
        if self.max_wall_clock_ms is None:
            return

        elapsed_ms = round((time.perf_counter() - self.started_at) * 1000, 2)
        if elapsed_ms > self.max_wall_clock_ms:
            raise BudgetExceededError(
                "Run exceeded `max_wall_clock_ms` budget",
                budget_name="max_wall_clock_ms",
            )

    def consume_step(self) -> None:
        self.ensure_wall_clock_remaining()
        if self.max_steps is not None and self.steps_used >= self.max_steps:
            raise BudgetExceededError(
                "Run exceeded `max_steps` budget",
                budget_name="max_steps",
            )

        self.steps_used += 1

    def consume_tool_call(self) -> None:
        self.ensure_wall_clock_remaining()
        if self.max_tool_calls is not None and self.tool_calls_used >= self.max_tool_calls:
            raise BudgetExceededError(
                "Run exceeded `max_tool_calls` budget",
                budget_name="max_tool_calls",
            )

        self.tool_calls_used += 1

    def consume_tokens(self, token_count: int) -> None:
        self.ensure_wall_clock_remaining()
        if token_count < 0:
            raise ValueError("Token count cannot be negative")

        if self.max_tokens is not None and (self.tokens_used + token_count) > self.max_tokens:
            raise BudgetExceededError(
                "Run exceeded `max_tokens` budget",
                budget_name="max_tokens",
            )

        self.tokens_used += token_count

    def limits_snapshot(self) -> dict[str, int | None]:
        return {
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "max_wall_clock_ms": self.max_wall_clock_ms,
        }

    def usage_snapshot(self) -> dict[str, int | float]:
        elapsed_ms = round((time.perf_counter() - self.started_at) * 1000, 2)
        return {
            "steps_used": self.steps_used,
            "tool_calls_used": self.tool_calls_used,
            "tokens_used": self.tokens_used,
            "wall_clock_ms": elapsed_ms,
        }


def load_budget(config: dict | None) -> RunBudget:
    config = config or {}
    return RunBudget(
        max_steps=config.get("max_steps"),
        max_tool_calls=config.get("max_tool_calls"),
        max_tokens=config.get("max_tokens"),
        max_wall_clock_ms=config.get("max_wall_clock_ms"),
    )
