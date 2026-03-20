"""Data models for diagnostic checks.

Defines the core types used across the doctor subsystem:
- Status: check outcome type alias
- CheckResult: single check outcome
- CheckCategory: grouped collection of related checks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["ok", "warn", "error", "info"]


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""

    name: str
    status: Status
    message: str
    fix: str | None = None
    fixable: bool = False


@dataclass
class CheckCategory:
    """A group of related diagnostic checks."""

    name: str
    checks: list[CheckResult] = field(default_factory=list)
