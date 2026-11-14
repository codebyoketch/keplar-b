from backend.app.grid import from_elevations
from backend.app.params import get_params
from backend.app.resources import estimate_resources, evaluate_mission, fix_preserves_margins
from backend.app.routing import plan_route
from backend.app.stress import run_stress

BOUNDS={"lo0":0.0,"la0":0.0,"lo1":0.1,"la1":0.1}

def flat_grid(size=41):return from_elevations([0.0]*(size*size),size,size,BOUNDS)

def test_unseen_obstacle_on_no_highres_segment_changes_route():
    grid=flat_grid()
    a,b=grid.coordinate(2,20),grid.coordinate(38,20)
    route=plan_route(grid,[a,b],15)
    segment={**route["segments"][0],"id":"r-S1"}
    params=get_params()
    result=run_stress(grid,segment,{"highres_coverage_fraction":0},"unseen_obstacle",15,
                      params["slope_error_margin_deg"]["value"],params["coarse_dem_threshold_m"]["value"],
                      params["obstacle_test_radius_cells"]["value"])
    assert result["eligible"] is True
    assert result["route_flips"] is True
    assert result["route_exists"] is True
    assert result["extra_distance_km"]>0

def test_full_hires_segment_skips_unseen_obstacle_case():
    grid=flat_grid();a,b=grid.coordinate(2,20),grid.coordinate(38,20)
    segment={"cells":[[2,20],[38,20]],"distance_km":1,"max_slope_deg":0}
    params=get_params()
    result=run_stress(grid,segment,{"highres_coverage_fraction":1},"unseen_obstacle",15,
                      params["slope_error_margin_deg"]["value"],params["coarse_dem_threshold_m"]["value"],
                      params["obstacle_test_radius_cells"]["value"])
    assert result["eligible"] is False
    assert result["route_flips"] is False

def test_slope_error_reports_limit_exceedance():
    grid=flat_grid()
    segment={"cells":[[2,20],[38,20]],"distance_km":1,"max_slope_deg":12}
    params=get_params()
    result=run_stress(grid,segment,{"highres_coverage_fraction":0},{"type":"slope_error","error_margin_deg":6},15,
                      params["slope_error_margin_deg"]["value"],params["coarse_dem_threshold_m"]["value"],
                      params["obstacle_test_radius_cells"]["value"])
    assert result["stressed_max_slope_deg"]==18
    assert result["exceeds_slope_limit"] is True

def test_resource_projection_returns_best_and_worst_on_coarse_dem():
    params=get_params()
    resources=estimate_resources([{"id":"S1","distance_km":1,"max_slope_deg":5}],params,463)
    row=resources["segments"][0]
    assert row["distance_km"]["worst"]>row["distance_km"]["best"]
    assert row["oxygen_used_pct"]["worst"]>row["oxygen_used_pct"]["best"]
    assert resources["turn_back_point"]

def test_every_suggested_change_preserves_each_reported_safety_margin():
    resources={"safety_margins_worst":{"oxygen_pct":18,"power_pct":12,"daylight_minutes":-5}}
    mission=evaluate_mission(resources,[])
    assert mission["verdict"]=="GO WITH CHANGES"
    assert mission["fixes"]
    for fix in mission["fixes"]:
        assert fix_preserves_margins(fix["safety_margins_before"],fix["safety_margins_after"])

def test_no_go_has_no_fixes_and_only_return_directive():
    resources={"safety_margins_worst":{"oxygen_pct":-1,"power_pct":10,"daylight_minutes":20}}
    mission=evaluate_mission(resources,[])
    assert mission["verdict"]=="NO-GO"
    assert mission["fixes"]==[]
    assert mission["directive"]=="return to shelter"

def test_slope_limit_breach_is_no_go_without_fixes():
    resources={"safety_margins_worst":{"oxygen_pct":10,"power_pct":10,"daylight_minutes":10}}
    stress=[{"scenario":"slope_error","exceeds_slope_limit":True}]
    mission=evaluate_mission(resources,stress)
    assert mission["verdict"]=="NO-GO" and mission["fixes"]==[]

def test_obstacle_detour_yields_go_with_changes_when_reserves_hold():
    resources={"safety_margins_worst":{"oxygen_pct":18,"power_pct":12,"daylight_minutes":20}}
    stress=[{"scenario":"unseen_obstacle","route_flips":True,"route_exists":True,"extra_distance_km":.3}]
    mission=evaluate_mission(resources,stress)
    assert mission["verdict"]=="GO WITH CHANGES"
    assert any("replanned around" in fix["action"] for fix in mission["fixes"])
    for fix in mission["fixes"]:
        assert fix_preserves_margins(fix["safety_margins_before"],fix["safety_margins_after"])
