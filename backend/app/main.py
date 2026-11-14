from __future__ import annotations
import math
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from .config import KEY_STATUS, NASA_API_KEY
from . import data_sources as sources
from .grid import from_dem
from .routing import plan_route
from .evidence import audit_segment
from .params import get_params, update_params
from .stress import run_stress
from .resources import estimate_resources, evaluate_mission
from uuid import uuid4
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse

app=FastAPI(title="Cairn: Trail Mode")
SEGMENT_DOSSIERS={}
ROUTE_CONTEXTS={}
LATEST_ROUTE_ID=None


@app.middleware("http")
async def redact_server_key(request:Request,call_next):
    """Final response guard: credentials can never be echoed to a caller."""
    response=await call_next(request)
    secret=NASA_API_KEY.encode("utf-8")
    if not secret or secret==b"DEMO_KEY":return response
    body=b"".join([chunk async for chunk in response.body_iterator]).replace(secret,b"[redacted]")
    headers=dict(response.headers)
    headers.pop("content-length",None)
    from starlette.responses import Response as StarletteResponse
    return StarletteResponse(body,status_code=response.status_code,headers=headers,media_type=response.media_type)


@app.get("/api/status")
def status():
    return {"key":KEY_STATUS}


@app.get("/api/layers")
def layers():
    try:
        names=sources.basemap_layers()
        return {"layers":names,"auto":sources.auto_layer(),"source":"USGS WMS"}
    except Exception:
        return {"layers":[],"auto":None,"source":"USGS WMS unavailable; retry or use cached area"}


@app.get("/api/basemap")
def basemap(site:str="jezero",lo0:float|None=None,la0:float|None=None,lo1:float|None=None,la1:float|None=None,layer:str=""):
    query={"site":site}
    if lo0 is not None:query["lo0"]=lo0
    if la0 is not None:query["la0"]=la0
    if lo1 is not None:query["lo1"]=lo1
    if la1 is not None:query["la1"]=la1
    try:
        image,name=sources.get_basemap(sources.bbox_from_query(query),layer or None)
        return Response(image,media_type="image/png",headers={"X-Layer":name,"Access-Control-Expose-Headers":"X-Layer"})
    except Exception as exc:raise HTTPException(502,detail=f"Basemap unavailable ({type(exc).__name__})")


@app.get("/api/dem")
def dem(site:str="jezero",lo0:float|None=None,la0:float|None=None,lo1:float|None=None,la1:float|None=None):
    query={"site":site}
    for key,value in (("lo0",lo0),("la0",la0),("lo1",lo1),("la1",la1)):
        if value is not None:query[key]=value
    try:return sources.get_dem(sources.bbox_from_query(query))
    except Exception as exc:raise HTTPException(502,detail=f"DEM unavailable ({type(exc).__name__})")


@app.get("/api/dem/hirise")
def hirise_dem(site:str="jezero",lo0:float|None=None,la0:float|None=None,lo1:float|None=None,la1:float|None=None):
    query={"site":site}
    for key,value in (("lo0",lo0),("la0",la0),("lo1",lo1),("la1",la1)):
        if value is not None:query[key]=value
    try:return sources.hirise_dem(sources.bbox_from_query(query))
    except Exception as exc:raise HTTPException(502,detail=f"HiRISE visual DEM unavailable ({type(exc).__name__}: {exc})")


@app.get("/api/dem/hirise/ortho")
def hirise_ortho(site:str="jezero",lo0:float|None=None,la0:float|None=None,lo1:float|None=None,la1:float|None=None):
    query={"site":site}
    for key,value in (("lo0",lo0),("la0",la0),("lo1",lo1),("la1",la1)):
        if value is not None:query[key]=value
    try:return sources.hirise_ortho(sources.bbox_from_query(query))
    except Exception as exc:raise HTTPException(502,detail=f"HiRISE orthoimage unavailable ({type(exc).__name__}: {exc})")


@app.get("/api/footprints")
def footprints(site:str="jezero",lo0:float|None=None,la0:float|None=None,lo1:float|None=None,la1:float|None=None):
    query={"site":site}
    for key,value in (("lo0",lo0),("la0",la0),("lo1",lo1),("la1",la1)):
        if value is not None:query[key]=value
    return sources.footprints(sources.bbox_from_query(query))


@app.get("/api/registry")
def registry(site:str="jezero",lo0:float|None=None,la0:float|None=None,lo1:float|None=None,la1:float|None=None):
    query={"site":site}
    for key,value in (("lo0",lo0),("la0",la0),("lo1",lo1),("la1",la1)):
        if value is not None:query[key]=value
    result=sources.footprints(sources.bbox_from_query(query))
    return [{"id":p["id"],"name":p["id"],"source":p.get("src"),"product_id":p["id"],
             "resolution_m":p.get("res"),"observation_date":p.get("date"),"footprint":p.get("poly"),
             "processing_level":p.get("proc"),"value_type":"assumed" if p.get("src")=="ILLUSTRATIVE" else "measured" if p.get("src")=="ODE" else "unknown",
             "is_placeholder":p.get("src")=="ILLUSTRATIVE"} for p in result["fps"]]


@app.get("/api/apod")
def apod_endpoint():
    try:return sources.apod(NASA_API_KEY)
    except Exception as exc:raise HTTPException(502,detail=f"NASA APOD unavailable ({type(exc).__name__})")


@app.get("/api/rover-photos")
def rover_photos(rover:str="perseverance",sol:int=Query(ge=0)):
    try:return sources.rover_photos(rover,sol,NASA_API_KEY)
    except ValueError as exc:raise HTTPException(400,detail=str(exc))
    except Exception as exc:raise HTTPException(502,detail=f"NASA rover photos unavailable ({type(exc).__name__})")


@app.get("/api/params")
def params():
    return get_params()


@app.put("/api/params")
def put_params(payload:dict):
    try:return update_params(payload)
    except ValueError as exc:raise HTTPException(400,detail=str(exc))


def _route_bbox(waypoints):
    lons=[float(point[0]) for point in waypoints];lats=[float(point[1]) for point in waypoints]
    lon_span=max(lons)-min(lons);lat_span=max(lats)-min(lats)
    pad=max(.04,lon_span*.15,lat_span*.15)
    return min(lons)-pad,min(lats)-pad,max(lons)+pad,max(lats)+pad


@app.post("/api/route")
def create_route(payload:dict):
    global LATEST_ROUTE_ID
    if not isinstance(payload,dict):raise HTTPException(400,detail="Request body must be an object")
    target=payload.get("target")
    target_info=target if isinstance(target,dict) else {"name":str(target or "unnamed target")}
    claim=target_info.get("claim","terrain")
    if claim not in {"terrain","current","thermal"}:raise HTTPException(400,detail="claim must be terrain, current, or thermal")
    waypoints=payload.get("waypoints")
    if not isinstance(waypoints,list) or len(waypoints)<2:raise HTTPException(400,detail="At least two [longitude, latitude] waypoints are required")
    stop_count=payload.get("stop_count",1)
    if not isinstance(stop_count,int) or isinstance(stop_count,bool) or stop_count<1:
        raise HTTPException(400,detail="stop_count must be a positive integer (including the target stop)")
    target_coordinates=target_info.get("coordinates")
    for point in waypoints:
        if not isinstance(point,(list,tuple)) or len(point)!=2:
            raise HTTPException(400,detail="Each waypoint must contain longitude and latitude")
        try:
            if not all(math.isfinite(float(value)) for value in point):raise ValueError
        except (TypeError,ValueError):raise HTTPException(400,detail="Waypoint coordinates must be finite numbers")
    if target_coordinates is not None:
        if not isinstance(target_coordinates,(list,tuple)) or len(target_coordinates)!=2:
            raise HTTPException(400,detail="Target coordinates must contain longitude and latitude")
        try:
            if not all(math.isfinite(float(value)) for value in target_coordinates):raise ValueError
        except (TypeError,ValueError):raise HTTPException(400,detail="Target coordinates must be finite numbers")
    if target_coordinates and list(target_coordinates)!=list(waypoints[-1]):waypoints=[*waypoints,list(target_coordinates)]
    try:
        bbox=_route_bbox(waypoints)
        dem=sources.get_dem(bbox)
        grid=from_dem(dem)
        settings=get_params()
        slope_limit=float(settings["slope_limit_deg"]["value"])
        obstacle_tolerance=float(settings["boulder_tolerance"]["value"])
        planned=plan_route(grid,waypoints,slope_limit)
        footprints_result=sources.footprints(bbox)
    except ValueError as exc:raise HTTPException(400,detail=str(exc))
    except Exception as exc:raise HTTPException(502,detail=f"Route planning data unavailable ({type(exc).__name__})")
    route_id=uuid4().hex[:12]
    segments=[]
    for index,segment in enumerate(planned["segments"],start=1):
        segment_id=f"{route_id}-S{index}"
        dossier=audit_segment(segment_id,segment["coordinates"],footprints_result["fps"],obstacle_tolerance,claim,
                              segment["max_slope_deg"],slope_limit,slope_from_dem=True,
                              age_limit_years=float(settings["current_observation_age_limit_years"]["value"]))
        dossier["products"]=[{**product,"value_type":"assumed" if product.get("src")=="ILLUSTRATIVE" else "measured" if product.get("src")=="ODE" else "unknown"} for product in dossier["products"]]
        SEGMENT_DOSSIERS[segment_id]=dossier
        segments.append({**segment,"id":segment_id,"verdict":dossier["verdict"],"checks":dossier["checks"],"flags":dossier["flags"]})
    if len(SEGMENT_DOSSIERS)>600:
        for old_id in list(SEGMENT_DOSSIERS)[:200]:SEGMENT_DOSSIERS.pop(old_id,None)
    ROUTE_CONTEXTS[route_id]={"grid":grid,"plan":planned,"segments":segments,
        "dossiers":{item["id"]:SEGMENT_DOSSIERS[item["id"]] for item in segments},
        "target":target_info,"claim":claim,"waypoints":waypoints,"stop_count":stop_count,
        "data_status":"live" if footprints_result["live"] else "PLACEHOLDER DATA"}
    LATEST_ROUTE_ID=route_id
    return {"route_id":route_id,"target":target_info,"claim":claim,"waypoints":waypoints,
            "grid":{"width":grid.width,"height":grid.height,"bounds":grid.bounds,"resolution_m":grid.resolution_m,
                    "elevation_type":grid.elevation_type,"slope_type":grid.slope_type},
            "routing_rule":"8-neighbor A*: block cells above the slope limit; distance cost is weighted by 1 + mean slope / slope limit.",
            "assumptions":{"slope_limit_deg":{"value":slope_limit,"label":"unvalidated assumption"},
                           "boulder_tolerance":{"value":obstacle_tolerance,"unit":"meters","label":"unvalidated assumption"}},
            "data_status":"live" if footprints_result["live"] else "PLACEHOLDER DATA",
            "footprint_errors":footprints_result.get("errs",[]),"main":planned["main"],"alternate":planned["alternate"],"segments":segments}


@app.get("/api/segment/{segment_id}/dossier")
def segment_dossier(segment_id:str):
    dossier=SEGMENT_DOSSIERS.get(segment_id)
    if dossier is None:raise HTTPException(404,detail="Segment dossier not found; calculate a route first")
    return dossier


def _route_context(route_id=None):
    key=route_id or LATEST_ROUTE_ID
    context=ROUTE_CONTEXTS.get(key)
    if context is None:raise HTTPException(404,detail="Calculate a route first")
    return key,context


@app.post("/api/stress")
def stress(payload:dict):
    segment_id=payload.get("segment_id")
    scenario=payload.get("scenario")
    dossier=SEGMENT_DOSSIERS.get(segment_id)
    if dossier is None:raise HTTPException(404,detail="Segment dossier not found; calculate a route first")
    route_id=segment_id.rsplit("-S",1)[0]
    context=ROUTE_CONTEXTS.get(route_id)
    if context is None:raise HTTPException(404,detail="Route context expired; calculate the route again")
    segment=next((item for item in context["segments"] if item["id"]==segment_id),None)
    settings=get_params()
    try:result=run_stress(context["grid"],segment,dossier,scenario,float(settings["slope_limit_deg"]["value"]),
                          float(settings["slope_error_margin_deg"]["value"]),float(settings["coarse_dem_threshold_m"]["value"]),
                          int(settings["obstacle_test_radius_cells"]["value"]))
    except (ValueError,TypeError) as exc:raise HTTPException(400,detail=str(exc))
    dossier.setdefault("stress_tests",[]).append(result)
    if result.get("route_flips"):
        dossier["verdict"]="Fragile"
        code="STRESS_ROUTE_FLIP" if result["scenario"]=="unseen_obstacle" else "STRESS_SLOPE_LIMIT"
        dossier.setdefault("flags",[]).append({"code":code,"reason":result.get("reason","Scenario changed the route status."),"severity":"bad"})
    return {"segment_id":segment_id,**result,"verdict":dossier["verdict"]}


def _resource_analysis(route_id=None):
    key,context=_route_context(route_id)
    settings=get_params()
    stress_by_segment={}
    for segment_id,dossier in context["dossiers"].items():
        for result in dossier.get("stress_tests",[]):
            per_segment=stress_by_segment.setdefault(segment_id,{})
            if result.get("scenario")=="unseen_obstacle":
                old=per_segment.get("obstacle")
                old_extra=float((old or {}).get("extra_distance_km") or 0)
                new_extra=float(result.get("extra_distance_km") or 0)
                if old is None or (result.get("route_flips") and not result.get("route_exists",True)) or new_extra>old_extra:
                    per_segment["obstacle"]=result
            elif result.get("scenario")=="slope_error":
                old=per_segment.get("slope_error")
                if old is None or float(result.get("stressed_max_slope_deg",0))>float(old.get("stressed_max_slope_deg",0)):
                    per_segment["slope_error"]=result
    resources=estimate_resources(context["segments"],settings,context["grid"].resolution_m,stress_by_segment,context["stop_count"])
    stress_results=[result for dossier in context["dossiers"].values() for result in dossier.get("stress_tests",[])]
    return key,context,resources,stress_results


@app.get("/api/resources")
def resources(route_id:str|None=None):
    key,context,projection,_=_resource_analysis(route_id)
    return {"route_id":key,"terrain_resolution_m":{"value":context["grid"].resolution_m,"value_type":"measured"},**projection}


def _mission_payload(route_id=None):
    key,context,projection,stress_results=_resource_analysis(route_id)
    result=evaluate_mission(projection,stress_results)
    turn=projection["turn_back_point"]
    clock={"point":turn["point"],"elapsed_outbound_minutes":turn["elapsed_outbound_minutes"],
           "return_time_minutes":turn["return_time_minutes"],"value_type":"derived"}
    return {"route_id":key,"verdict":result["verdict"],"clock":clock,"fixes":result["fixes"],
            "directive":result["directive"],"hard_limits":result["hard_limits"],
            "safety_margins":result["safety_margins"],"resources":projection,"stress_tests":stress_results}


@app.get("/api/mission")
def mission(route_id:str|None=None):
    return _mission_payload(route_id)


@app.get("/api/brief")
def brief(route_id:str|None=None):
    key,context,projection,stress_results=_resource_analysis(route_id)
    mission_result=evaluate_mission(projection,stress_results)
    segments=list(context["segments"])
    dossiers=context["dossiers"]
    weakest=next((dossiers[segment["id"]] for segment in segments if dossiers[segment["id"]]["verdict"]=="Fragile"),None)
    if weakest is None:weakest=next((dossiers[segment["id"]] for segment in segments if dossiers[segment["id"]]["verdict"]=="Check"),None)
    supported=[{"id":segment["id"],"verdict":dossiers[segment["id"]]["verdict"],"checks":dossiers[segment["id"]]["checks"]}
               for segment in segments if dossiers[segment["id"]]["verdict"]=="Supported"]
    caveats=[{"segment_id":segment["id"],"flags":dossiers[segment["id"]]["flags"]}
             for segment in segments if dossiers[segment["id"]]["flags"]]
    next_observation=weakest["needed"] if weakest else "No additional observation is identified for the current route."
    turn=projection["turn_back_point"]
    return {"route_id":key,"target":context["target"],"mission_verdict":mission_result["verdict"],
            "turn_back_clock":{"point":turn["point"],"elapsed_outbound_minutes":turn["elapsed_outbound_minutes"],
                               "return_time_minutes":turn["return_time_minutes"],"value_type":"derived"},
            "resource_margins":projection["safety_margins_worst"],
            "resources":projection,"well_supported":supported,"caveats":caveats,
            "stress_test_results":stress_results,"next_observation":next_observation,
            "sources":[{key:p.get(key) for key in ("id","inst","src","res","date","proc")} for d in dossiers.values() for p in d["products"]],
            "data_status":context["data_status"],"advisory_only":True,"print_ready":True}


# Vite's production bundle is served locally. The dev server proxies /api to this app.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (_FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")


@app.get("/{frontend_path:path}", include_in_schema=False)
def frontend(frontend_path: str = ""):
    if frontend_path == "api" or frontend_path.startswith("api/"):
        raise HTTPException(404, detail="API endpoint not found")
    index = _FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return PlainTextResponse("Frontend bundle missing. Run: cd frontend && npm install && npm run build", status_code=503)
