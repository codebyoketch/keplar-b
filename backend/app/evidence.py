"""Transparent per-segment evidence checks and dossier generation."""
from __future__ import annotations
from datetime import datetime, timezone
import math
from .prototype_audit import distance, in_polygon, samples

STALE_YEARS=0.1  # retained from the reference prototype for claims of current conditions

def _coverage(route_points, instruments, products):
    relevant=[p for p in products if p.get("inst") in instruments]
    hits=0; matched=[]
    for point in route_points:
        at_point=[product for product in relevant if in_polygon(point,product.get("poly",[]))]
        if at_point:hits+=1
        for product in at_point:
            if product not in matched:matched.append(product)
    fraction=hits/max(len(route_points),1)
    best=min(matched,key=lambda p:float(p.get("res",float("inf"))),default=None)
    return {"fraction":fraction,"products":matched,"best":best}

def _age_check(products, claim, age_limit_years=STALE_YEARS):
    dated=[p for p in products if p.get("date")]
    if claim!="current":
        if not products:return {"status":"warn","reason":"No dated observation is available for this segment.","value_type":"unknown"}
        return {"status":"pass" if dated else "warn",
                "reason":"Acquisition dates are recorded; this claim does not require live local conditions." if dated else "Acquisition date is unknown, so change over time cannot be assessed.",
                "value_type":"measured" if dated else "unknown"}
    if not dated:return {"status":"fail","reason":"A current-condition claim needs a known, recent observation date.","value_type":"unknown"}
    now=datetime.now(timezone.utc); ages=[]
    for product in dated:
        try:
            seen=datetime.fromisoformat(str(product["date"]).replace("Z","+00:00"))
            if seen.tzinfo is None:seen=seen.replace(tzinfo=timezone.utc)
            ages.append((now-seen).total_seconds()/31557600)
        except (TypeError,ValueError):continue
    if not ages:return {"status":"fail","reason":"Observation dates could not be parsed.","value_type":"unknown"}
    oldest=max(ages)
    return {"status":"fail","stale":oldest>age_limit_years,"has_unknown_dates":len(dated)<len(products),
            "reason":f"Orbital imagery is not live local data ({oldest:.1f} years old; crew-set recency limit {age_limit_years:.1f} years).",
            "value_type":"derived","oldest_age_years":round(oldest,2)}

def audit_segment(segment_id,coordinates,products,obstacle_tolerance_m=0.5,claim="terrain",slope_max_deg=0.0,slope_limit_deg=15.0,slope_from_dem=True,age_limit_years=STALE_YEARS):
    if len(coordinates)<2:raise ValueError("A segment needs at least two route coordinates")
    route_points=[]
    for a,b in zip(coordinates,coordinates[1:]):
        route_points.extend(samples(a,b,30)[:-1])
    route_points.append(tuple(coordinates[-1]))
    images=_coverage(route_points,{"HiRISE","CTX"},products)
    thermal=_coverage(route_points,{"THEMIS"},products) if claim=="thermal" else None
    highres=_coverage(route_points,{"HiRISE"},products)
    ctx=_coverage(route_points,{"CTX"},products)
    all_coverage=_coverage(route_points,{p.get("inst") for p in products},products)
    coverage_basis=thermal if thermal is not None else all_coverage
    if coverage_basis["fraction"]==0:
        coverage={"status":"fail","reason":"No product footprint covers this segment.","coverage_fraction":0.0,"value_type":"unknown"}
        coverage_code=("NO_IMAGE_COVERAGE","No imagery footprint over this segment","bad") if images["fraction"]==0 else None
    elif coverage_basis["fraction"]<1:
        coverage={"status":"warn","reason":f"Product footprints cover {coverage_basis['fraction']*100:.0f}% of the sampled segment.","coverage_fraction":coverage_basis["fraction"],"value_type":"interpolated"}
        coverage_code=("PARTIAL_COVERAGE",f"HiRISE {highres['fraction']*100:.0f}%, CTX {ctx['fraction']*100:.0f}% of segment covered","bad") if images["fraction"]<1 else None
    else:
        coverage={"status":"pass","reason":"At least one product footprint covers the full segment.","coverage_fraction":1.0,"value_type":"measured"}
        coverage_code=None
    adequate=highres["fraction"]==1 and highres["best"] and float(highres["best"].get("res",math.inf))<=obstacle_tolerance_m
    if adequate:
        scale={"status":"pass","reason":f"HiRISE resolution ({highres['best']['res']} m/px) meets the {obstacle_tolerance_m:g} m obstacle assumption.","resolution_m":highres["best"]["res"],"value_type":"measured"}
    elif ctx["fraction"]==1:
        scale={"status":"warn","reason":f"CTX ({ctx['best']['res']} m/px) covers the route but is too coarse to resolve {obstacle_tolerance_m:g} m obstacles.","resolution_m":ctx["best"]["res"],"value_type":"measured"}
    elif highres["fraction"]>0:
        scale={"status":"warn","reason":f"High-resolution imagery covers only {highres['fraction']*100:.0f}% of the segment at the requested scale.","resolution_m":highres["best"]["res"],"value_type":"interpolated"}
    elif images["fraction"]>0:
        scale={"status":"warn","reason":"Available imagery is too coarse to resolve astronaut-scale obstacles.","resolution_m":images["best"]["res"],"value_type":"measured"}
    else:
        scale={"status":"fail","reason":"No image product can establish obstacle scale on this segment.","value_type":"unknown"}
    imagery_products=list(all_coverage["products"])
    age=_age_check(imagery_products,claim,age_limit_years)
    placeholder=any(p.get("src")=="ILLUSTRATIVE" for p in imagery_products)
    type_names={"ILLUSTRATIVE":"assumed","ODE":"measured","WCS":"measured"}
    product_types=sorted({type_names.get(p.get("src"),"unknown") for p in imagery_products})
    if not imagery_products:
        data_type={"status":"fail","reason":"No source observation is available to classify.","value_type":"unknown","types":["unknown"]}
    elif placeholder:
        data_type={"status":"warn","reason":"Illustrative placeholder footprints are assumptions, not observed coverage.","value_type":"assumed","types":product_types}
    elif any(t in product_types for t in ("unknown","assumed","interpolated","derived")):
        data_type={"status":"warn","reason":"One or more products are derived, interpolated, unknown, or assumed.","value_type":product_types[0],"types":product_types}
    else:
        data_type={"status":"pass","reason":"Coverage products are measured orbital observations.","value_type":"measured","types":product_types}
    checks={"coverage":coverage,"scale":scale,"age":age,"type":data_type}
    flags=[]
    flags.append({"code":"SLOPE_FROM_DEM" if slope_from_dem else "SLOPE_ASSUMED",
                  "reason":f"Maximum slope {slope_max_deg:.1f}° is {'DEM-derived' if slope_from_dem else 'an assumption'}.","severity":"warn"})
    flags.append({"code":"DEM_COARSE","reason":"MOLA elevation is regional terrain context and may smooth local slopes or obstacles.","severity":"warn"})
    if coverage_code:flags.append({"code":coverage_code[0],"reason":coverage_code[1],"severity":coverage_code[2]})
    elif images["fraction"]==0 and claim!="thermal":
        flags.append({"code":"NO_IMAGE_COVERAGE","reason":"No HiRISE or CTX footprint covers this segment.","severity":"bad"})
    if not adequate:
        if ctx["fraction"]==1:code,reason,severity="CTX_ONLY",scale["reason"],"warn"
        elif images["fraction"]>0:code,reason,severity="IMAGE_RES_TOO_COARSE",scale["reason"],"bad"
        else:code,reason,severity="IMAGE_RES_TOO_COARSE",scale["reason"],"bad"
        if not any(f["code"]==code for f in flags):flags.append({"code":code,"reason":reason,"severity":severity})
    if highres["products"] and ctx["products"]:
        flags.append({"code":"MULTI_SOURCE_SCALE","reason":"CTX and HiRISE have different native scales; their evidence is kept separate.","severity":"warn"})
    if any(p.get("src")=="ODE" and p.get("res_src")=="nominal" for p in imagery_products):
        flags.append({"code":"RES_NOMINAL","reason":"Product resolution is missing from its metadata; a nominal value is shown.","severity":"warn"})
    if placeholder:flags.append({"code":"PLACEHOLDER_DATA","reason":"Illustrative footprint; not real coverage.","severity":"bad"})
    if claim=="current":
        flags.append({"code":"NOT_VALID_AS_LOCAL_CURRENT_CONDITION","reason":"Orbital observations are not live local conditions.","severity":"bad"})
        if age.get("stale"):flags.append({"code":"OBSERVATION_STALE","reason":age["reason"],"severity":"bad"})
        if age["status"]=="warn" or age.get("has_unknown_dates") or age.get("value_type")=="unknown":
            flags.append({"code":"OBSERVATION_TIME_UNKNOWN","reason":age["reason"],"severity":"bad"})
    if claim=="thermal":
        if thermal and thermal["fraction"]==1:
            flags.append({"code":"THERMAL_REGIONAL_ONLY","reason":"THEMIS is regional thermal context, not astronaut-level surface temperature.","severity":"warn"})
            checks["scale"]={"status":"warn","reason":"THEMIS is too coarse for astronaut-level surface temperature.","resolution_m":thermal["best"]["res"],"value_type":"measured"}
        else:
            flags.append({"code":"NO_THERMAL_COVERAGE","reason":f"THEMIS covers {thermal['fraction']*100:.0f}% of this segment.","severity":"bad"})
            checks["scale"]={"status":"fail","reason":"No THEMIS thermal footprint covers the segment.","value_type":"unknown"}
    statuses={check["status"] for check in checks.values()}
    verdict="Fragile" if "fail" in statuses else "Check" if "warn" in statuses else "Supported"
    all_products=[]
    for product in imagery_products:
        if product not in all_products:all_products.append(product)
    needed=("Acquire HiRISE imagery covering the full route at or finer than the configured obstacle tolerance." if not adequate
            else "No additional imagery is required for this claim.")
    return {"id":segment_id,"verdict":verdict,"checks":checks,"flags":flags,"products":all_products,
            "needed":needed,"claim":claim,"route_holds_under_dem":slope_max_deg<=slope_limit_deg,
            "highres_coverage_fraction":highres["fraction"],
            "slope_max_deg":round(float(slope_max_deg),2),"slope_limit_deg":float(slope_limit_deg),
            "stress_status":"not run; stress testing is implemented in Phase 3","placeholder_data":placeholder}
