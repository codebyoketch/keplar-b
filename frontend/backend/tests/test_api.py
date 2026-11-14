import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["CAIRN_PARAMS_FILE"] = str(Path(tempfile.mkdtemp()) / "params.json")

import planning  # noqa: E402
from app import app  # noqa: E402

client = TestClient(app)
AREA = planning.AREA


def box_query():
    return f"lo0={AREA['lo0']}&la0={AREA['la0']}&lo1={AREA['lo1']}&la1={AREA['la1']}"


@pytest.fixture(scope="module")
def planned_route():
    response = client.post("/api/route", json={
        "target": {"name": "Jezero delta front", "claim": "terrain", "coordinates": [77.45, 18.15]},
        "waypoints": [[77.10, 17.95], [77.40, 18.15], [77.62, 18.28]],
        "stop_count": 2,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_status_and_layers():
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["key"] in ("DEMO_KEY", "custom")

    layers = client.get("/api/layers").json()
    assert layers["layers"] and layers["auto"] in layers["layers"]


def test_params_round_trip():
    original = client.get("/api/params").json()
    assert "slope_limit_deg" in original
    assert original["reserve_minimums"]["value"]["oxygen"] == 30

    updated = client.put("/api/params", json={
        **original,
        "slope_limit_deg": {**original["slope_limit_deg"], "value": 32},
    }).json()
    assert updated["slope_limit_deg"]["value"] == 32

    client.put("/api/params", json=original)


def test_footprints_and_dem():
    fps = client.get(f"/api/footprints?{box_query()}").json()
    assert fps["fps"]
    assert {fp["inst"] for fp in fps["fps"]} <= {"CTX", "HiRISE", "CRISM", "THEMIS"}
    assert all(len(fp["poly"]) >= 3 for fp in fps["fps"])

    dem = client.get(f"/api/dem?{box_query()}").json()
    assert dem["w"] > 0 and dem["h"] > 0
    assert len(dem["z"]) > 0
    # 72x72 float32 grid, base64 encoded.
    assert len(dem["z"]) == pytest.approx(72 * 72 * 4 * 4 / 3, rel=0.05)
    assert dem["b"]["lo0"] == AREA["lo0"]


def test_route_contract(planned_route):
    assert planned_route["route_id"].startswith("RT-")
    assert len(planned_route["segments"]) == 2
    for segment in planned_route["segments"]:
        assert segment["verdict"] in ("Supported", "Check", "Fragile")
        assert isinstance(segment["flags"], list)
        assert segment["checks"]["coverage"]["status"] in ("pass", "warn", "fail")
        assert segment["checks"]["scale"]["value_type"]
        assert segment["distance_km"] > 0
        assert len(segment["coordinates"]) >= 2
    assert planned_route["alternate"]["coordinates"]
    assert planned_route["data_status"] == "PLACEHOLDER DATA"


def test_route_requires_two_waypoints():
    response = client.post("/api/route", json={"waypoints": [[77.1, 18.0]], "target": {"name": "x", "claim": "terrain"}})
    assert response.status_code == 400


def test_resources_mission_and_brief(planned_route):
    route_id = planned_route["route_id"]

    resources = client.get(f"/api/resources?route_id={route_id}").json()
    assert len(resources["segments"]) == len(planned_route["segments"])
    for row in resources["segments"]:
        assert row["oxygen_used_pct"]["best"] <= row["oxygen_used_pct"]["worst"]

    mission = client.get(f"/api/mission?route_id={route_id}").json()
    assert mission["verdict"] in ("GO", "CAUTION", "NO-GO")
    assert set(mission["hard_limits"]) == {
        "reserve_breached", "obstacle_route_unavailable", "slope_limit_exceeded",
    }
    assert mission["clock"]["point"].startswith("S")
    assert mission["safety_margins"]["oxygen_pct"] < 100

    brief = client.get(f"/api/brief?route_id={route_id}").json()
    assert brief["target"]["name"] == "Jezero delta front"
    assert brief["mission_verdict"] == mission["verdict"]
    assert brief["resource_margins"] == mission["safety_margins"]
    assert brief["next_observation"]
    assert brief["sources"]
    assert brief["data_status"] == "PLACEHOLDER DATA"


def test_dossier_resolves_latest_route_without_route_id(planned_route):
    segment_id = planned_route["segments"][0]["id"]
    dossier = client.get(f"/api/segment/{segment_id}/dossier")
    assert dossier.status_code == 200, dossier.text
    body = dossier.json()
    assert body["segment_id"] == segment_id
    assert 0 <= body["highres_coverage_fraction"] <= 1
    assert body["needed"]


def test_stress_unseen_obstacle_changes_verdict_and_mission(planned_route):
    route_id = planned_route["route_id"]
    segment_id = planned_route["segments"][0]["id"]

    response = client.post("/api/stress", json={"segment_id": segment_id, "scenario": "unseen_obstacle"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["result"]["scenario"] == "unseen_obstacle"
    assert body["dossier"]["stress_tests"]
    assert body["dossier"]["verdict"] in ("Check", "Fragile")
    assert body["mission"]["verdict"] in ("CAUTION", "NO-GO")

    after = client.get(f"/api/mission?route_id={route_id}").json()
    assert after["verdict"] == body["mission"]["verdict"]
    if body["result"]["no_route"]:
        assert after["hard_limits"]["obstacle_route_unavailable"] is True

    brief = client.get(f"/api/brief?route_id={route_id}").json()
    assert any(item["scenario"] == "unseen_obstacle" for item in brief["stress_test_results"])


def test_stress_slope_error_and_unknown_inputs(planned_route):
    segment_id = planned_route["segments"][1]["id"]
    body = client.post("/api/stress", json={"segment_id": segment_id, "scenario": "slope_error"}).json()
    assert body["result"]["scenario"] == "slope_error"
    assert "limit" in body["result"]["reason"]

    assert client.post("/api/stress", json={"segment_id": segment_id, "scenario": "meteor"}).status_code == 400
    assert client.post("/api/stress", json={"segment_id": "S99", "scenario": "slope_error"}).status_code == 404
    assert client.get("/api/mission?route_id=RT-NOPE").status_code == 404
    assert client.get("/api/brief?route_id=RT-NOPE").status_code == 404


def test_basemap_is_png_with_layer_header():
    response = client.get(f"/api/basemap?{box_query()}&layer=Mars_CTX_Mosaic")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-layer"] == "Mars_CTX_Mosaic"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_rover_photos_and_registry_shape():
    photos = client.get("/api/rover-photos?rover=perseverance&sol=1").json()
    assert isinstance(photos, list)

    registry = client.get(f"/api/registry?{box_query()}").json()
    assert registry
    assert all("is_placeholder" in row for row in registry)
