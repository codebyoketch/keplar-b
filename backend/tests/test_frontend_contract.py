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


def test_frontend_http_flow(monkeypatch):
    """Exercise browser request shapes through HTTP with deterministic terrain."""
    import array
    import base64
    import sys
    from fastapi.testclient import TestClient
    from backend.app import main

    elevations = array.array('f', [0.0] * (41 * 41))
    if sys.byteorder == 'big':
        elevations.byteswap()
    dem = {
        'b': {'lo0': 0, 'la0': 0, 'lo1': .1, 'la1': .1},
        'w': 41, 'h': 41, 'z': base64.b64encode(elevations.tobytes()).decode(),
        'res': 463, 'layer': 'fixture MOLA',
    }
    monkeypatch.setattr(main.sources, 'get_dem', lambda bbox: dem)
    monkeypatch.setattr(main.sources, 'footprints', lambda bbox: {'live': False, 'errs': [], 'fps': []})
    monkeypatch.setattr(main, 'SEGMENT_DOSSIERS', {})
    monkeypatch.setattr(main, 'ROUTE_CONTEXTS', {})
    monkeypatch.setattr(main, 'LATEST_ROUTE_ID', None)
    with TestClient(app) as client:
        assert client.get('/api/status').status_code == 200
        assert client.get('/api/params').status_code == 200
        assert client.get('/api/dem?site=jezero').json() == dem
        assert client.get('/api/footprints?site=jezero').json()['fps'] == []
        response = client.post('/api/route', json={
            'target': {'name': 'Test target', 'claim': 'terrain'},
            'waypoints': [[.04, .05], [.06, .05]], 'stop_count': 1,
        })
        assert response.status_code == 200, response.text
        route = response.json()
        segment_id = route['segments'][0]['id']
        assert client.get(f'/api/segment/{segment_id}/dossier').status_code == 200
        response = client.post('/api/stress', json={
            'segment_id': segment_id, 'scenario': 'unseen_obstacle',
        })
        assert response.status_code == 200, response.text
        for endpoint in ('resources', 'mission', 'brief'):
            response = client.get(f'/api/{endpoint}', params={'route_id': route['route_id']})
            assert response.status_code == 200, response.text
            assert response.json()['route_id'] == route['route_id']


def test_unknown_api_does_not_return_frontend_html(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main

    (tmp_path / 'index.html').write_text('<html>Frontend</html>')
    monkeypatch.setattr(main, '_FRONTEND_DIST', tmp_path)
    with TestClient(app) as client:
        assert client.get('/').text == '<html>Frontend</html>'
        assert client.get('/planner').status_code == 200
        for path in ('/api', '/api/not-an-endpoint'):
            response = client.get(path)
            assert response.status_code == 404
            assert response.json()['detail'] == 'API endpoint not found'
