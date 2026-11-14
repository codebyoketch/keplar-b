"""Small content cache. NASA secrets are removed before cache-key derivation."""
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .config import CACHE_DIR


def cache_identity(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "api_key"]
    safe = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return hashlib.sha256(safe.encode("utf-8")).hexdigest()


def cache_path(url: str, cache_dir: Path = CACHE_DIR) -> Path:
    return Path(cache_dir) / cache_identity(url)


def read_bytes(url: str, cache_dir: Path = CACHE_DIR) -> bytes | None:
    path = cache_path(url, cache_dir)
    return path.read_bytes() if path.is_file() else None


def write_bytes(url: str, body: bytes, cache_dir: Path = CACHE_DIR) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache_path(url, cache_dir).write_bytes(body)


def read_json(url: str, cache_dir: Path = CACHE_DIR):
    body = read_bytes(url, cache_dir)
    return json.loads(body) if body is not None else None


def write_json(url: str, value, cache_dir: Path = CACHE_DIR) -> None:
    write_bytes(url, json.dumps(value).encode("utf-8"), cache_dir)
