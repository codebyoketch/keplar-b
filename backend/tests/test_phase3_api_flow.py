import array
import base64
import sys
from backend.app import main

def test_stress_changes_mission_and_brief_reports_results(monkeypatch):
    size=41;z=array.array("f",[0.0]*(size*size))
    if sys.byteorder=="big":z.byteswap()
    dem={"b":{"lo0":0,"la0":0,"lo1":.1,"la1":.1},"w":size,"h":size,
         "z":base64.b64encode(z.tobytes()).decode(),"res":463,"layer":"fixture MOLA"}
    no_products={"live":False,"errs":["offline"],"fps":[]}
    monkeypatch.setattr(main.sources,"get_dem",lambda bbox:dem)
    monkeypatch.setattr(main.sources,"footprints",lambda bbox:no_products)
    route=main.create_route({"target":{"name":"test target"},"waypoints":[[.04,.05],[.06,.05]]})
    segment=route["segments"][0]
    tested=main.stress({"segment_id":segment["id"],"scenario":"unseen_obstacle"})
    assert tested["route_flips"] and tested["route_exists"]
    mission=main.mission(route["route_id"])
    assert mission["verdict"]=="GO WITH CHANGES"
    brief=main.brief(route["route_id"])
    assert brief["stress_test_results"]
    assert brief["next_observation"]
    assert brief["advisory_only"] is True
