"""Check the frontend's required HTTP endpoints against the authoritative FastAPI app.

This intentionally avoids network access and validates the mounted API contract.
"""
from fastapi.routing import APIRoute

from backend.app.main import app


def test_frontend_api_contract():
    required = {
        ("GET", "/api/status"),
        ("GET", "/api/layers"),
        ("GET", "/api/params"),
        ("PUT", "/api/params"),
        ("GET", "/api/footprints"),
        ("GET", "/api/dem"),
        ("GET", "/api/basemap"),
        ("GET", "/api/registry"),
        ("POST", "/api/route"),
        ("GET", "/api/segment/{segment_id}/dossier"),
        ("POST", "/api/stress"),
        ("GET", "/api/resources"),
        ("GET", "/api/mission"),
        ("GET", "/api/brief"),
        ("GET", "/api/rover-photos"),
    }
    available = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert required <= available, f"Missing frontend API routes: {required - available}"
