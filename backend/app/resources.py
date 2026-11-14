"""Transparent best/worst oxygen, power, time and return-reserve projections."""
from __future__ import annotations
import math

def _value(params,key):return float(params[key]["value"])

def _segment_cost(distance_km,slope_deg,stop_minutes,load,params):
    speed=_value(params,"walking_speed")
    slope_limit=_value(params,"slope_limit_deg")
    hours=distance_km/speed
    total_hours=hours+stop_minutes/60
    slope_factor=1+max(0,slope_deg)/slope_limit
    oxygen=distance_km*_value(params,"oxygen_rate")*load*slope_factor+total_hours*_value(params,"oxygen_rate_per_hour")
    power=distance_km*_value(params,"power_rate")*load*slope_factor+total_hours*_value(params,"power_rate_per_hour")
    return {"oxygen_used_pct":oxygen,"power_used_pct":power,"walk_minutes":hours*60,
            "stop_minutes":stop_minutes,"total_minutes":total_hours*60}


def estimate_resources(segments,params,dem_resolution_m,stress_by_segment=None,stop_count=1):
    """Return segment and round-trip resource ranges. Worst case drives turnback."""
    stress_by_segment=stress_by_segment or {}
    coarse=float(dem_resolution_m)>_value(params,"coarse_dem_threshold_m")
    load=_value(params,"load_factor")
    distance_factor=_value(params,"coarse_terrain_distance_factor") if coarse else 1.0
    error_margin=_value(params,"slope_error_margin_deg") if coarse else 0.0
    stop_duration=_value(params,"stop_duration_minutes")
    output=[];out_o=out_p=out_t=back_o=back_p=back_t=0.0
    checkpoints=[]
    for idx,segment in enumerate(segments):
        base_dist=float(segment["distance_km"])
        slope=float(segment["max_slope_deg"])
        stress=stress_by_segment.get(segment.get("id"),{})
        obstacle=stress.get("obstacle",stress)
        detour=float(obstacle.get("extra_distance_km") or 0) if obstacle.get("route_flips") and obstacle.get("route_exists",True) else 0.0
        slope_stress=stress.get("slope_error")
        if obstacle.get("replanned"):
            slope=max(slope,float(obstacle["replanned"].get("max_slope_deg",0)))
        best_dist=base_dist
        worst_dist=base_dist*distance_factor+max(0,detour)
        best_slope=slope
        worst_slope=min(89.9,max(slope+error_margin,float((slope_stress or {}).get("stressed_max_slope_deg",0))))
        stop_minutes=stop_duration*max(1,int(stop_count)) if idx==len(segments)-1 else 0.0
        best=_segment_cost(best_dist,best_slope,stop_minutes,load,params)
        worst=_segment_cost(worst_dist,worst_slope,stop_minutes,load,params)
        return_cost=_segment_cost(worst_dist,worst_slope,0,load,params)
        row={"id":segment.get("id",f"S{idx+1}"),"distance_km":{"best":round(best_dist,3),"worst":round(worst_dist,3),"value_type":"derived"},
             "slope_deg":{"best":round(best_slope,2),"worst":round(worst_slope,2),"value_type":"derived"},
             "oxygen_used_pct":{"best":round(best["oxygen_used_pct"],2),"worst":round(worst["oxygen_used_pct"],2),"value_type":"derived"},
             "power_used_pct":{"best":round(best["power_used_pct"],2),"worst":round(worst["power_used_pct"],2),"value_type":"derived"},
             "time_minutes":{"best":round(best["total_minutes"],2),"worst":round(worst["total_minutes"],2),"value_type":"derived"},
             "return_worst":{"oxygen_used_pct":round(return_cost["oxygen_used_pct"],2),"power_used_pct":round(return_cost["power_used_pct"],2),"time_minutes":round(return_cost["total_minutes"],2)},
             "terrain_range":"coarse DEM uncertainty included" if coarse else "fine terrain grid"}
        output.append(row)
        out_o+=worst["oxygen_used_pct"];out_p+=worst["power_used_pct"];out_t+=worst["total_minutes"]
        back_o+=return_cost["oxygen_used_pct"];back_p+=return_cost["power_used_pct"];back_t+=return_cost["total_minutes"]
        reserves=params["reserve_minimums"]["value"]
        checkpoints.append({"point":row["id"],"after_segment":idx+1,
            "oxygen_margin_pct":round(_value(params,"starting_oxygen")-out_o-back_o-float(reserves["oxygen"]),2),
            "power_margin_pct":round(_value(params,"starting_power")-out_p-back_p-float(reserves["power"]),2),
            "daylight_margin_minutes":round(_value(params,"daylight_remaining")-out_t-back_t,2),
            "elapsed_outbound_minutes":round(out_t,2),"return_time_minutes":round(back_t,2)})
    reserves=params["reserve_minimums"]["value"]
    start_oxygen=_value(params,"starting_oxygen");start_power=_value(params,"starting_power")
    roundtrip={"oxygen_used_pct":round(out_o+back_o,2),"power_used_pct":round(out_p+back_p,2),
               "time_minutes":round(out_t+back_t,2)}
    margins={"oxygen_pct":round(start_oxygen-float(reserves["oxygen"])-out_o-back_o,2),
             "power_pct":round(start_power-float(reserves["power"])-out_p-back_p,2),
             "daylight_minutes":round(_value(params,"daylight_remaining")-out_t-back_t,2)}
    safe=[point for point in checkpoints if point["oxygen_margin_pct"]>=0 and point["power_margin_pct"]>=0 and point["daylight_margin_minutes"]>=0]
    turnback=safe[-1] if safe else {"point":"SHELTER","after_segment":0,"oxygen_margin_pct":round(start_oxygen-float(reserves["oxygen"]),2),
        "power_margin_pct":round(start_power-float(reserves["power"]),2),"daylight_margin_minutes":round(_value(params,"daylight_remaining"),2),"elapsed_outbound_minutes":0,"return_time_minutes":0}
    return {"segments":output,"round_trip_worst":roundtrip,"safety_margins_worst":margins,
            "checkpoints":checkpoints,"turn_back_point":turnback,
            "assumptions":{"load_factor":params["load_factor"],"stop_duration_minutes":params["stop_duration_minutes"],
             "slope_error_margin_deg":params["slope_error_margin_deg"],"coarse_terrain_distance_factor":params["coarse_terrain_distance_factor"],
             "coarse_dem_threshold_m":params["coarse_dem_threshold_m"],"obstacle_test_radius_cells":params["obstacle_test_radius_cells"],
             "label":"unvalidated assumption"},
            "formula":"distance rate × load × (1 + slope / slope limit), plus hourly resource rate × walking and stop time; worst case adds coarse-terrain factors."}


def fix_preserves_margins(before,after):
    """A proposed change is admissible only if every listed reserve/time margin holds."""
    return all(key in after and float(after[key])>=float(value) for key,value in before.items())


def evaluate_mission(resources,stress_results):
    margins=resources["safety_margins_worst"]
    blocked_stress=any(item.get("scenario")=="unseen_obstacle" and item.get("route_flips") and not item.get("route_exists",True) for item in stress_results)
    slope_exceeded=any(item.get("scenario")=="slope_error" and item.get("exceeds_slope_limit") for item in stress_results)
    reserve_breached=margins["oxygen_pct"]<0 or margins["power_pct"]<0
    if reserve_breached or blocked_stress or slope_exceeded:
        return {"verdict":"NO-GO","fixes":[],"directive":"return to shelter",
                "hard_limits":{"reserve_breached":reserve_breached,"obstacle_route_unavailable":blocked_stress,"slope_limit_exceeded":slope_exceeded},
                "safety_margins":margins}
    daylight_short=margins["daylight_minutes"]<0
    route_changed=any(item.get("scenario")=="unseen_obstacle" and item.get("route_flips") and item.get("route_exists",True) for item in stress_results)
    verdict="GO WITH CHANGES" if daylight_short or route_changed else "GO"
    fixes=[]
    if daylight_short:
        before=dict(margins)
        earlier=math.ceil(-margins["daylight_minutes"]+1)
        after={**margins,"daylight_minutes":margins["daylight_minutes"]+earlier}
        if fix_preserves_margins(before,after):
            fixes.append({"action":"Start earlier to recover the projected daylight shortfall.","change_minutes":earlier,
                          "safety_margins_before":before,"safety_margins_after":after})
    if route_changed:
        before=dict(margins);after=dict(margins)
        if fix_preserves_margins(before,after):
            fixes.append({"action":"Use the route replanned around the unseen obstacle.",
                          "safety_margins_before":before,"safety_margins_after":after,
                          "note":"The worst-case resource projection already includes the stress-tested detour."})
    return {"verdict":verdict,"fixes":fixes,"directive":None,"hard_limits":{"reserve_breached":False,"obstacle_route_unavailable":False,"slope_limit_exceeded":False},
            "safety_margins":margins}
