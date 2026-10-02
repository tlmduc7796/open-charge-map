#!/usr/bin/env python3
"""Compatibility entrypoint for the executable quantile RDM trainer.

New commands should use ``train_rdm_quantile.py``.  This name remains so old
notebooks and documentation cannot silently train a different RDM pipeline.
"""

from __future__ import annotations

try:  # Supports package import and `python ml/src/...py`.
    from .train_rdm_quantile import main
except ImportError:  # pragma: no cover - direct CLI invocation.
    from train_rdm_quantile import main

if __name__ == "__main__":
    main()
