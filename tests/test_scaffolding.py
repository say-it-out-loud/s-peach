"""Tests for s_peach.scaffolding — shared init/voice helpers."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


class TestScaffoldingImports:
    """Verify scaffolding.py has no circular dependencies."""

    def test_scaffolding_no_circular_imports(self) -> None:
        """scaffolding.py must not import from s_peach.main or s_peach.cli."""
        src = Path(importlib.util.find_spec("s_peach.scaffolding").origin)
        tree = ast.parse(src.read_text())

        forbidden = {"s_peach.main", "s_peach.cli"}
        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden:
                    if node.module == prefix or node.module.startswith(prefix + "."):
                        violations.append(f"line {node.lineno}: from {node.module} import ...")

        assert violations == [], f"Circular import(s) found in scaffolding.py: {violations}"

    def test_import_init_scaffolding(self) -> None:
        """init_scaffolding is importable from s_peach.scaffolding."""
        from s_peach.scaffolding import init_scaffolding
        assert callable(init_scaffolding)

    def test_import_generate_api_key(self) -> None:
        """_generate_api_key is importable from s_peach.scaffolding."""
        from s_peach.scaffolding import _generate_api_key
        assert callable(_generate_api_key)

    def test_generate_api_key_returns_hex_string(self) -> None:
        """_generate_api_key returns a 64-char hex string."""
        from s_peach.scaffolding import _generate_api_key
        key = _generate_api_key()
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)
