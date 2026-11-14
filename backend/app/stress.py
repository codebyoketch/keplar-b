"""Explicit route stress scenarios; no scalar safety score is computed."""
from __future__ import annotations
from .grid import MarsGrid
from .routing import NoRouteError, find_path, path_distance_km, _path_summary

def unseen_obstacle(grid:MarsGrid,segment:dict,slope_limit_deg:float,radius_cells:int=1):
    cells=[tuple(cell) for cell in segment["cells"]]
    if len(cells)<2:raise ValueError("Segment is too short to stress-test")
    center=cells[len(cells)//2]
    blocked=set()
    for y in range(center[1]-radius_cells,center[1]+radius_cells+1):
        for x in range(center[0]-radius_cells,center[0]+radius_cells+1):
            if 0<=x<grid.width and 0<=y<grid.height and (x,y) not in (cells[0],cells[-1]):blocked.add((x,y))
    try:
        replanned=find_path(grid,cells[0],cells[-1],slope_limit_deg,blocked_cells=blocked)
        route_exists=True
        summary=_path_summary(grid,replanned)
        flipped=replanned!=cells
        extra=round(path_distance_km(grid,replanned)-path_distance_km(grid,cells),4)
    except NoRouteError:
        replanned=[];route_exists=False;summary=None;flipped=True;extra=None
    return {"scenario":"unseen_obstacle","eligible":True,"blocked_cells":[list(p) for p in sorted(blocked)],
            "route_flips":flipped,"route_exists":route_exists,"extra_distance_km":extra,
            "replanned":summary,"reason":"Blocked a plausible obstacle footprint on the segment without relying on unseen-image data."}


def slope_error(segment:dict,error_margin_deg:float,slope_limit_deg:float,dem_resolution_m:float,coarse_threshold_m:float):
    if error_margin_deg<0:raise ValueError("error_margin_deg must be non-negative")
    if dem_resolution_m<=coarse_threshold_m:raise ValueError("Slope-error scenario is intended for coarse terrain data")
    baseline=float(segment["max_slope_deg"])
    stressed=baseline+float(error_margin_deg)
    exceeds=stressed>slope_limit_deg
    return {"scenario":"slope_error","eligible":True,"error_margin_deg":float(error_margin_deg),
            "baseline_max_slope_deg":round(baseline,3),"stressed_max_slope_deg":round(stressed,3),
            "slope_limit_deg":float(slope_limit_deg),"exceeds_slope_limit":exceeds,
            "route_flips":exceeds,"reason":f"Adding {error_margin_deg:g}° to the coarse-DEM maximum gives {stressed:.1f}° against a {slope_limit_deg:g}° limit."}


def run_stress(grid:MarsGrid,segment:dict,dossier:dict,scenario,slope_limit_deg:float,
               slope_error_margin_deg:float|None=None,coarse_threshold_m:float|None=None,
               obstacle_radius_cells:int|None=None):
    if isinstance(scenario,str):scenario={"type":scenario}
    if not isinstance(scenario,dict):raise ValueError("scenario must be a string or object")
    kind=scenario.get("type",scenario.get("scenario"))
    if kind=="unseen_obstacle":
        if dossier.get("highres_coverage_fraction",0)>=1:
            return {"scenario":kind,"eligible":False,"route_flips":False,"reason":"This segment has full HiRISE coverage; the unseen-obstacle scenario targets segments without full high-resolution imagery."}
        radius=scenario.get("radius_cells",obstacle_radius_cells)
        if radius is None:raise ValueError("Configure obstacle_test_radius_cells in assumptions")
        if not isinstance(radius,int) or isinstance(radius,bool):raise ValueError("radius_cells must be an integer")
        if not 0<=radius<=10:raise ValueError("radius_cells must be between 0 and 10")
        return unseen_obstacle(grid,segment,slope_limit_deg,radius)
    if kind=="slope_error":
        margin=scenario.get("error_margin_deg",slope_error_margin_deg)
        if margin is None:raise ValueError("Provide error_margin_deg or configure it in assumptions")
        threshold=scenario.get("coarse_threshold_m",coarse_threshold_m)
        if threshold is None:raise ValueError("Configure coarse_dem_threshold_m in assumptions")
        return slope_error(segment,float(margin),slope_limit_deg,grid.resolution_m,float(threshold))
    raise ValueError("scenario type must be unseen_obstacle or slope_error")
