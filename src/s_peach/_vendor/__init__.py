"""Vendored packages: kittentts 0.8.1, en_core_web_sm 3.8.0.

Call install() once at startup to add this directory to sys.path,
making `import kittentts` and `import en_core_web_sm` work.
Call patch_spacy() before loading spaCy models to make
spacy.load("en_core_web_sm") find the vendored model.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR_DIR = str(Path(__file__).parent)
_installed = False
_spacy_patched = False

_VENDORED_SPACY_MODELS = {"en_core_web_sm"}


def install() -> None:
    """Add the vendor directory to sys.path if not already present."""
    global _installed
    if _installed:
        return
    if _VENDOR_DIR not in sys.path:
        sys.path.insert(0, _VENDOR_DIR)
    _installed = True


def patch_spacy() -> None:
    """Make spacy.util.is_package() recognise vendored spaCy models.

    Call this right before spacy.load() — not at startup, to avoid
    importing spaCy (~1s) on every CLI invocation.
    """
    global _spacy_patched
    if _spacy_patched:
        return
    _spacy_patched = True
    try:
        import spacy.util
    except ImportError:
        return
    _original = spacy.util.is_package

    def _is_package(name: str) -> bool:
        if name in _VENDORED_SPACY_MODELS:
            return True
        return _original(name)

    spacy.util.is_package = _is_package
