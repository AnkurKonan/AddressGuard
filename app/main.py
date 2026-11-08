"""Local compatibility entry for uvicorn / pytest.

Cloudflare Workers uses src/main.py as the Worker entrypoint.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path so `src.main` resolves when running as app.main
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.main import *  # noqa: F401,F403
from src.main import app  # noqa: F401
