"""Server-only configuration. NASA credentials are never exposed to clients."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # lets cached/offline startup work before optional env setup is installed
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[2]
if load_dotenv:
    load_dotenv(ROOT / ".env", override=False)
NASA_API_KEY = (os.environ.get("NASA_API_KEY") or "").strip() or "DEMO_KEY"
KEY_STATUS = "custom" if NASA_API_KEY != "DEMO_KEY" else "DEMO_KEY"
PARAM_UPDATES_ENABLED = os.environ.get("CAIRN_ENABLE_PARAM_UPDATES", "false").strip().lower() in {"1", "true", "yes", "on"}
CACHE_DIR = Path(os.environ.get("CAIRN_CACHE_DIR", ROOT / "backend" / "cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
