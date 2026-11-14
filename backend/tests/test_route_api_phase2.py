import array
import base64
import sys
from backend.app import main

def test_route_endpoint_builds_waypoint_segments_and_dossiers(monkeypatch):
    width=height=41
    elevations=array.array("f",[0.0]*(width*height))
    if sys.byteorder=="big":elevations.byteswap()
    dem={"b":{"lo0":0,"la0":0,"lo1":.1,"la1":.1},"w":width,"h":height,
         "z":base64.b64encode(elevations.tobytes()).decode(),"res":463,"layer":"fixture MOLA"}
    footprints={"live":True,"errs":[],"fps":[{"id":"TEST-HIRISE","inst":"HiRISE","poly":[[-.01,-.01],[.11,-.01],[.11,.11],[-.01,.11],[-.01,-.01]],"res":.25,"res_src":"metadata","date":"2026-01-01","src":"ODE"}]}
    monkeypatch.setattr(main.sources,"get_dem",lambda bbox:dem)
    monkeypatch.setattr(main.sources,"footprints",lambda bbox:footprints)
    response=main.create_route({"target":{"name":"rock unit","claim":"terrain"},
                                "waypoints":[[.01,.05],[.05,.06],[.09,.05]]})
    assert response["alternate"] is not None
    assert len(response["segments"])==2
    assert response["segments"][0]["verdict"]=="Supported"
    dossier=main.segment_dossier(response["segments"][0]["id"])
    assert dossier["checks"]["coverage"]["status"]=="pass"
    assert dossier["products"][0]["id"]=="TEST-HIRISE"
