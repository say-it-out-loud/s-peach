"""Shared CLI test helpers."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from s_peach.cli import main


def run_main(
    *args: str,
    stdin_text: str | None = None,
) -> tuple[int, str, str]:
    """Run main() and capture exit code, stdout, stderr."""
    captured_out = StringIO()
    captured_err = StringIO()

    patches = [
        patch("sys.stdout", captured_out),
        patch("sys.stderr", captured_err),
    ]
    if stdin_text is not None:
        stdin_patch = StringIO(stdin_text)
        patches.append(patch("sys.stdin", stdin_patch))

    for p in patches:
        p.start()

    try:
        main(list(args))
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        for p in reversed(patches):
            p.stop()

    return code, captured_out.getvalue(), captured_err.getvalue()
