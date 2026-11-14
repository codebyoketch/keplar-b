"""Start the authoritative FastAPI application with Uvicorn.

Supports both ``python backend/run.py`` and ``python -m backend.run``.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

# Direct script execution otherwise puts only backend/ on the import path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=os.getenv("CAIRN_HOST", "127.0.0.1"),
        port=int(os.getenv("CAIRN_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
