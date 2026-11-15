import pytest
from backend.app.explore import suggest


@pytest.mark.parametrize('payload', [
    {'site': 'unknown'}, {'claim': 'unknown'},
    {'start': [0, 0]}, {'start': [True, 18]}, {'start': [77]},
])
def test_invalid_exploration_input(payload):
    with pytest.raises(ValueError):
        suggest(payload)


def test_placeholder_coverage_is_not_recommended(monkeypatch):
    from backend.app import explore
    from backend.app.grid import from_elevations
    grid = from_elevations([0.] * 100, 10, 10,
        {'lo0': 76.8, 'la0': 17.6, 'lo1': 78.4, 'la1': 19.2})
    monkeypatch.setattr(explore, 'from_dem', lambda _: grid)
    monkeypatch.setattr(explore.sources, 'get_dem', lambda _: {})
    monkeypatch.setattr(explore.sources, 'footprints', lambda _: {'fps': [
        {'src': 'ILLUSTRATIVE', 'inst': 'HiRISE', 'poly': [[76,17],[79,17],[79,20],[76,20]]}
    ]})
    result = suggest({})
    assert result['start_source'] == 'site_center'
    assert result['suggestions'] == []
    assert result['message']


def test_nearby_narrow_footprint_is_discovered(monkeypatch):
    from backend.app import explore
    from backend.app.grid import from_elevations
    grid = from_elevations([0.] * 101**2, 101, 101,
        {'lo0': 76.8, 'la0': 17.6, 'lo1': 78.4, 'la1': 19.2})
    monkeypatch.setattr(explore, 'from_dem', lambda _: grid)
    monkeypatch.setattr(explore.sources, 'get_dem', lambda _: {})
    # Near the default start, between the old 16-by-16 sampling points.
    monkeypatch.setattr(explore.sources, 'footprints', lambda _: {'fps': [
        {'id': 'real-test', 'src': 'ODE', 'inst': 'CTX', 'res': 6,
         'poly': [[77.615,18.38],[77.635,18.38],[77.635,18.42],[77.615,18.42]]}
    ]})
    result = suggest({})
    assert result['diagnostics']['covered_cells'] > 0
    assert result['suggestions']
    assert result['suggestions'][0]['distance_km'] < 3
