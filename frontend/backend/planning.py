"""Planning engine for Cairn Trail Mode.

Deterministic, planning-time only. All data is synthetic ("PLACEHOLDER DATA")
and is derived from the analytic terrain so the React frontend has a stable
contract to talk to. No live telemetry is used or implied.
"""

import math
import random
import uuid

AREA = {"lo0": 76.8, "la0": 17.6, "lo1": 78.4, "la1": 19.2}
DEM_WIDTH = 72
DEM_HEIGHT = 72
MARS_RADIUS_KM = 3389.5
METERS_PER_DEG_LAT = 59150.0
DATA_STATUS = "PLACEHOLDER DATA"

VERDICT_SUPPORTED = "Supported"
VERDICT_CHECK = "Check"
VERDICT_FRAGILE = "Fragile"

CLAIM_TYPES = {
    "terrain": "terrain",
    "current": "current",
    "thermal": "thermal",
}

DEFAULT_PARAMS = {
    "traverse_speed_kmh": {"value": 8.0, "unit": "km/h", "label": "Conservative traverse speed"},
    "daylight_minutes": {"value": 960, "unit": "min", "label": "Usable daylight window"},
    "slope_limit_deg": {"value": 30, "unit": "deg", "label": "Traversable slope limit"},
    "slope_error_margin_deg": {"value": 5, "unit": "deg", "label": "DEM slope error margin"},
    "oxygen_use_pct_per_km": {"value": 0.5, "unit": "%/km", "label": "Crew oxygen use per km"},
    "power_use_pct_per_km": {"value": 0.35, "unit": "%/km", "label": "Power use per km"},
    "sample_mass_kg": {"value": 12, "unit": "kg", "label": "Planned sample mass"},
    "reserve_minimums": {"value": {"oxygen": 30, "power": 20}, "unit": "%", "label": "Return reserve minimums"},
}

PRODUCTS = [
    {
        "id": "CTX-01", "inst": "CTX", "res": 6, "src": "PDS", "value_type": "terrain",
        "poly": [[77.05, 17.95], [77.72, 17.95], [77.72, 18.52], [77.05, 18.52]],
    },
    {
        "id": "HiRISE-01", "inst": "HiRISE", "res": 0.25, "src": "PDS", "value_type": "terrain",
        "poly": [[77.30, 18.02], [77.66, 18.02], [77.66, 18.34], [77.30, 18.34]],
    },
    {
        "id": "CRISM-01", "inst": "CRISM", "res": 18, "src": "PDS", "value_type": "mineralogy",
        "poly": [[76.90, 17.70], [77.90, 17.70], [77.90, 18.40], [76.90, 18.40]],
    },
    {
        "id": "THEMIS-01", "inst": "THEMIS", "res": 100, "src": "PDS", "value_type": "thermal",
        "poly": [[77.00, 17.80], [78.30, 17.80], [78.30, 19.00], [77.00, 19.00]],
    },
    {
        "id": "CTX-02", "inst": "CTX", "res": 6, "src": "ILLUSTRATIVE", "value_type": "terrain",
        "poly": [[77.80, 18.40], [78.30, 18.40], [78.30, 19.00], [77.80, 19.00]],
    },
    {
        "id": "HiRISE-02", "inst": "HiRISE", "res": 0.25, "src": "PDS", "value_type": "terrain",
        "poly": [[76.85, 18.60], [77.15, 18.60], [77.15, 18.86], [76.85, 18.86]],
    },
    {
        "id": "CRISM-02", "inst": "CRISM", "res": 18, "src": "ILLUSTRATIVE", "value_type": "mineralogy",
        "poly": [[78.00, 18.80], [78.35, 18.80], [78.35, 19.10], [78.00, 19.10]],
    },
]

ROUTES = {}
PARAMS_PATH = None  # set by the app module so tests can redirect persistence


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------

def elevation(lon, lat):
    """Analytic synthetic elevation in metres (deterministic, local area)."""
    u = (lon - AREA["lo0"]) / (AREA["lo1"] - AREA["lo0"])
    v = (lat - AREA["la0"]) / (AREA["la1"] - AREA["la0"])
    return (
        900.0
        + 420.0 * math.sin(6.2 * u + 1.1) * math.cos(5.1 * v)
        + 240.0 * math.sin(11.0 * u - 3.0 * v)
        + 160.0 * math.cos(9.0 * v + 2.0 * u)
        + 90.0 * math.sin(51.0 * u * v)
        + 380.0 * math.sin(38.0 * u + 21.0 * v)
        + 200.0 * math.sin(77.0 * u - 55.0 * v)
        + 110.0 * math.sin(131.0 * u + 97.0 * v)
    )


def slope_at(lon, lat):
    """Local slope in degrees from the analytic terrain."""
    h = 0.001
    d_lon_m = METERS_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6)
    dz_dx = (elevation(lon + h, lat) - elevation(lon - h, lat)) / (2 * h * d_lon_m)
    dz_dy = (elevation(lon, lat + h) - elevation(lon, lat - h)) / (2 * h * METERS_PER_DEG_LAT)
    return math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))


def build_dem(box):
    """Return the frontend DEM payload (base64 float32 LE elevations)."""
    import base64
    import struct

    lo0 = float(box["lo0"])
    la0 = float(box["la0"])
    lo1 = float(box["lo1"])
    la1 = float(box["la1"])
    values = []
    for y in range(DEM_HEIGHT):
        lat = la1 - (y / (DEM_HEIGHT - 1)) * (la1 - la0)
        for x in range(DEM_WIDTH):
            lon = lo0 + (x / (DEM_WIDTH - 1)) * (lo1 - lo0)
            values.append(elevation(lon, lat))
    raw = struct.pack("<%df" % len(values), *values)
    return {
        "z": base64.b64encode(raw).decode("ascii"),
        "w": DEM_WIDTH,
        "h": DEM_HEIGHT,
        "b": {"lo0": lo0, "la0": la0, "lo1": lo1, "la1": la1},
        "layer": "SYNTHETIC MOLA DTM",
        "res": round((la1 - la0) * METERS_PER_DEG_LAT / (DEM_HEIGHT - 1)),
        "data_status": DATA_STATUS,
    }


def haversine_km(a, b):
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * MARS_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def interpolate(a, b, count=12):
    return [
        [a[0] + (b[0] - a[0]) * i / (count - 1), a[1] + (b[1] - a[1]) * i / (count - 1)]
        for i in range(count)
    ]


def inside_polygon(point, polygon):
    lon, lat = point
    hit = False
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[i - 1]
        if (yi > lat) != (yj > lat) and lon < ((xj - xi) * (lat - yi)) / ((yj - yi) or 1e-12) + xi:
            hit = not hit
    return hit


# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------

def default_params():
    import copy
    return copy.deepcopy(DEFAULT_PARAMS)


def _reserve_values(params):
    reserve = params.get("reserve_minimums", {}).get("value", {})
    return {
        "oxygen": float(reserve.get("oxygen", 30)),
        "power": float(reserve.get("power", 20)),
    }


def _param_value(params, key, fallback):
    try:
        return float(params[key]["value"])
    except (KeyError, TypeError, ValueError):
        return float(fallback)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def covering_products(point):
    return [product for product in PRODUCTS if inside_polygon(point, product["poly"])]


def segment_evidence(coordinates, claim, params):
    """Evaluate coverage, scale, age and type checks for a segment."""
    sample_points = coordinates[::2] or coordinates
    highres = [product for product in PRODUCTS if product["inst"] in ("CTX", "HiRISE")]
    covered = [product for product in highres if inside_polygon(coordinates[len(coordinates) // 2], product["poly"])]
    fraction = sum(
        1 for point in sample_points if any(inside_polygon(point, product["poly"]) for product in highres)
    ) / max(len(sample_points), 1)
    all_covering = [product for product in PRODUCTS if inside_polygon(coordinates[len(coordinates) // 2], product["poly"])]
    illustrative = [product for product in all_covering if product["src"] == "ILLUSTRATIVE"]
    value_types = {product["value_type"] for product in all_covering}
    best_res = min((product["res"] for product in covered), default=None)
    claim_type = CLAIM_TYPES.get(claim, "terrain")

    if fraction >= 0.9:
        coverage = {"status": "pass", "reason": f"{fraction * 100:.0f}% of the segment lies in high-resolution imagery."}
    elif fraction >= 0.4:
        coverage = {"status": "warn", "reason": f"Only {fraction * 100:.0f}% of the segment lies in high-resolution imagery."}
    else:
        coverage = {"status": "fail", "reason": "No close-up imagery covers this segment; boulders are not visible."}

    if best_res is not None and best_res <= 1:
        scale = {"status": "pass", "reason": f"Finest covering product is {best_res} m/px.", "value_type": "terrain"}
    elif best_res is not None and best_res <= 18:
        scale = {"status": "pass", "reason": f"Finest covering product is {best_res} m/px.", "value_type": "terrain" if best_res <= 18 else "mineralogy"}
    elif best_res is not None:
        scale = {"status": "warn", "reason": f"Finest covering product is coarse ({best_res} m/px).", "value_type": "thermal"}
    elif all_covering:
        scale = {"status": "warn", "reason": "Only coarse or compositional products cover this segment.", "value_type": sorted(value_types)[0]}
    else:
        scale = {"status": "fail", "reason": "No orbital product covers this segment.", "value_type": "assumed"}

    if illustrative:
        age = {"status": "warn", "reason": f"{illustrative[0]['id']} is illustrative, not a dated archive product."}
    elif all_covering:
        age = {"status": "pass", "reason": "Covering products are archive acquisitions."}
    else:
        age = {"status": "fail", "reason": "Acquisition dates cannot be established without a product."}

    if claim_type in value_types:
        type_check = {"status": "pass", "reason": f"Covering evidence directly addresses the {claim_type} claim."}
    else:
        type_check = {"status": "warn", "reason": f"Covering evidence does not directly address the {claim_type} claim."}

    flags = []
    if coverage["status"] == "fail":
        flags.append({"code": "COVERAGE_GAP", "severity": "high", "reason": coverage["reason"]})
    elif coverage["status"] == "warn":
        flags.append({"code": "PARTIAL_COVERAGE", "severity": "warn", "reason": coverage["reason"]})
    if scale["status"] == "fail":
        flags.append({"code": "NO_PRODUCT", "severity": "high", "reason": scale["reason"]})
    elif scale["status"] == "warn":
        flags.append({"code": "COARSE_SCALE", "severity": "warn", "reason": scale["reason"]})
    if age["status"] == "warn":
        flags.append({"code": "AGE_UNCERTAIN", "severity": "warn", "reason": age["reason"]})
    if age["status"] == "fail":
        flags.append({"code": "AGE_UNKNOWN", "severity": "warn", "reason": age["reason"]})
    if type_check["status"] != "pass":
        flags.append({"code": "TYPE_MISMATCH", "severity": "warn", "reason": type_check["reason"]})

    return {
        "checks": {"coverage": coverage, "scale": scale, "age": age, "type": type_check},
        "flags": flags,
        "highres_coverage_fraction": round(fraction, 3),
        "products": all_covering,
        "claim_type": claim_type,
    }


def verdict_from_flags(flags):
    if any(flag["severity"] == "high" for flag in flags):
        return VERDICT_FRAGILE
    if flags:
        return VERDICT_CHECK
    return VERDICT_SUPPORTED


def needed_observation(evidence, segment_id):
    codes = {flag["code"] for flag in evidence["flags"]}
    if "COVERAGE_GAP" in codes or "PARTIAL_COVERAGE" in codes:
        return f"Acquire one HiRISE or CTX image covering all of {segment_id}; current close-up coverage is {evidence['highres_coverage_fraction'] * 100:.0f}%."
    if "COARSE_SCALE" in codes or "NO_PRODUCT" in codes:
        return f"Add a sub-10 m/px orbital product over {segment_id} to resolve boulders and local relief."
    if "AGE_UNCERTAIN" in codes or "AGE_UNKNOWN" in codes:
        return f"Confirm the acquisition date of the product covering {segment_id}; current local conditions remain unverified."
    if "TYPE_MISMATCH" in codes:
        return f"Acquire evidence that directly addresses the {evidence['claim_type']} claim on {segment_id}."
    return f"No additional observation identified for {segment_id}."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def plan_route(payload, params):
    waypoints = payload.get("waypoints") or []
    if len(waypoints) < 2:
        raise ValueError("At least two waypoints are required.")
    for point in waypoints:
        if not (isinstance(point, (list, tuple)) and len(point) == 2):
            raise ValueError("Waypoints must be [lon, lat] pairs.")
    target = payload.get("target") or {}
    claim = target.get("claim") or "terrain"
    if claim not in CLAIM_TYPES:
        claim = "terrain"
    slope_limit = _param_value(params, "slope_limit_deg", 30)
    slope_margin = _param_value(params, "slope_error_margin_deg", 5)

    segments = []
    for index in range(len(waypoints) - 1):
        coordinates = interpolate(waypoints[index], waypoints[index + 1])
        distance = haversine_km(waypoints[index], waypoints[index + 1])
        slopes = [slope_at(point[0], point[1]) for point in coordinates]
        max_slope = round(max(slopes), 2)
        segment_id = f"S{index + 1}"
        evidence = segment_evidence(coordinates, claim, params)
        flags = list(evidence["flags"])
        if max_slope + slope_margin > slope_limit:
            flags.append({
                "code": "SLOPE_HIGH",
                "severity": "high",
                "reason": f"Maximum slope {max_slope}° plus {slope_margin}° DEM error exceeds the {slope_limit}° limit.",
            })
        segments.append({
            "id": segment_id,
            "coordinates": coordinates,
            "distance_km": round(distance, 3),
            "max_slope_deg": max_slope,
            "verdict": verdict_from_flags(flags),
            "checks": evidence["checks"],
            "flags": flags,
            "highres_coverage_fraction": evidence["highres_coverage_fraction"],
            "needed": needed_observation(evidence, segment_id),
        })

    # Alternate alignment: offset each interior point perpendicular to the route.
    alternate = []
    for index, point in enumerate(waypoints):
        if index in (0, len(waypoints) - 1):
            alternate.append(point)
            continue
        alternate.append([point[0] + 0.035, point[1] + 0.02])

    route_id = "RT-" + uuid.uuid4().hex[:8].upper()
    route = {
        "route_id": route_id,
        "target": {"name": target.get("name") or "Crew selected target", "claim": claim},
        "waypoints": waypoints,
        "segments": segments,
        "alternate": {"coordinates": alternate},
        "stop_count": int(payload.get("stop_count") or 1),
        "data_status": DATA_STATUS,
        "stress_results": {},
        "stress_flags": {"obstacle_route_unavailable": False, "slope_limit_exceeded": False},
        "created_seq": len(ROUTES),
    }
    ROUTES[route_id] = route
    return route


def get_route(route_id):
    route = ROUTES.get(route_id)
    if not route:
        raise KeyError(route_id)
    return route


# ---------------------------------------------------------------------------
# Resources and mission
# ---------------------------------------------------------------------------

def compute_resources(route, params):
    speed = max(_param_value(params, "traverse_speed_kmh", 8.0), 0.005)
    oxygen_rate = _param_value(params, "oxygen_use_pct_per_km", 0.5)
    power_rate = _param_value(params, "power_use_pct_per_km", 0.35)
    rows = []
    for segment in route["segments"]:
        distance = segment["distance_km"]
        slope = segment["max_slope_deg"]
        base_minutes = distance / speed * 60 * (1 + slope / 60)
        oxygen = distance * oxygen_rate * (1 + slope / 45)
        power = distance * power_rate * (1 + slope / 60)
        rows.append({
            "segment_id": segment["id"],
            "oxygen_used_pct": {"best": round(oxygen * 0.85, 1), "worst": round(oxygen, 1)},
            "power_used_pct": {"best": round(power * 0.85, 1), "worst": round(power, 1)},
            "time_minutes": {"best": round(base_minutes * 0.85, 1), "worst": round(base_minutes, 1)},
        })
    return {"route_id": route["route_id"], "segments": rows}


def compute_mission(route, params):
    resources = compute_resources(route, params)
    # The mission must get the crew out and back; margins budget both legs.
    one_way = {
        "oxygen": sum(row["oxygen_used_pct"]["worst"] for row in resources["segments"]),
        "power": sum(row["power_used_pct"]["worst"] for row in resources["segments"]),
        "time": sum(row["time_minutes"]["worst"] for row in resources["segments"]),
        "distance": sum(segment["distance_km"] for segment in route["segments"]),
    }
    totals = {
        "oxygen": one_way["oxygen"] * 2,
        "power": one_way["power"] * 2,
        "time": one_way["time"] * 2,
        "distance": one_way["distance"] * 2,
    }
    reserve = _reserve_values(params)
    daylight = _param_value(params, "daylight_minutes", 960)
    margins = {
        "oxygen_pct": round(100 - totals["oxygen"], 1),
        "power_pct": round(100 - totals["power"], 1),
        "daylight_minutes": round(daylight - totals["time"], 1),
    }
    reserve_breached = margins["oxygen_pct"] < reserve["oxygen"] or margins["power_pct"] < reserve["power"]
    hard_limits = {
        "reserve_breached": reserve_breached,
        "obstacle_route_unavailable": route["stress_flags"]["obstacle_route_unavailable"],
        "slope_limit_exceeded": route["stress_flags"]["slope_limit_exceeded"],
    }
    blocked = any(hard_limits.values())
    weak = any(segment["verdict"] != VERDICT_SUPPORTED for segment in route["segments"])
    tight = margins["oxygen_pct"] < reserve["oxygen"] + 15 or margins["power_pct"] < reserve["power"] + 15

    if blocked:
        verdict = "NO-GO"
        directive = "Return to shelter. One or more hard stops is active."
    elif weak or tight:
        verdict = "CAUTION"
        directive = "Proceed only after resolving the flagged evidence and resource margins."
    else:
        verdict = "GO"
        directive = "Route is supported for planning; no live telemetry."

    fixes = []
    if reserve_breached:
        fixes.append({"action": "Shorten the traverse or add a stop to restore the return reserve."})
    if hard_limits["slope_limit_exceeded"]:
        fixes.append({"action": "Re-align the route around the steep segment."})
    if hard_limits["obstacle_route_unavailable"]:
        fixes.append({"action": "Choose a new route around the unseen obstacle."})
    if weak:
        fixes.append({"action": "Resolve the flagged evidence gap before committing to the route."})
    if tight and not reserve_breached:
        fixes.append({"action": "Reduce distance or increase the daylight window."})

    # Turn-back point: the segment containing half of the one-way distance.
    half = totals["distance"] / 2
    cumulative = 0.0
    point = route["segments"][0]["id"] if route["segments"] else "—"
    for segment in route["segments"]:
        cumulative += segment["distance_km"]
        if cumulative >= half:
            point = segment["id"]
            break
    clock = {
        "point": point,
        "elapsed_outbound_minutes": round(one_way["time"], 1),
        "return_time_minutes": round(one_way["time"], 1),
    }
    return {
        "route_id": route["route_id"],
        "verdict": verdict,
        "directive": directive,
        "clock": clock,
        "safety_margins": margins,
        "hard_limits": hard_limits,
        "fixes": fixes,
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "resources": resources,
        "data_status": DATA_STATUS,
    }


# ---------------------------------------------------------------------------
# Dossiers and stress tests
# ---------------------------------------------------------------------------

def build_dossier(route, segment_id):
    segment = next((item for item in route["segments"] if item["id"] == segment_id), None)
    if not segment:
        raise KeyError(segment_id)
    evidence = segment_evidence(segment["coordinates"], route["target"]["claim"], None)
    results = route["stress_results"].get(segment_id, [])
    flags = list(segment["flags"])
    for result in results:
        if result.get("severity") == "high":
            flags.append({
                "code": result["code"],
                "severity": "high",
                "reason": result["reason"],
            })
    return {
        "segment_id": segment_id,
        "verdict": segment["verdict"],
        "checks": segment["checks"],
        "flags": flags,
        "products": evidence["products"],
        "needed": segment.get("needed") or needed_observation(evidence, segment_id),
        "stress_tests": results,
        "highres_coverage_fraction": segment["highres_coverage_fraction"],
        "data_status": DATA_STATUS,
    }


def run_stress(route, segment_id, scenario, params):
    segment = next((item for item in route["segments"] if item["id"] == segment_id), None)
    if not segment:
        raise KeyError(segment_id)
    if scenario not in ("unseen_obstacle", "slope_error"):
        raise ValueError("Unknown stress scenario.")

    results = route["stress_results"].setdefault(segment_id, [])
    results[:] = [item for item in results if item["scenario"] != scenario]

    if scenario == "unseen_obstacle":
        detour = round(segment["distance_km"] * 0.22 + 0.35, 2)
        no_route = segment["max_slope_deg"] > 18
        route["stress_flags"]["obstacle_route_unavailable"] = no_route
        result = {
            "scenario": scenario,
            "code": "OBSTACLE_DETOUR",
            "severity": "high" if no_route else "warn",
            "reason": (
                "No lateral detour clears the unseen obstacle at the achievable slope; the route is unavailable."
                if no_route else f"A {detour} km detour clears the unseen obstacle."
            ),
            "extra_distance_km": detour,
            "no_route": no_route,
        }
    else:
        limit = _param_value(params, "slope_limit_deg", 30)
        margin = _param_value(params, "slope_error_margin_deg", 5)
        stressed_slope = round(segment["max_slope_deg"] + margin, 2)
        over_limit = stressed_slope > limit
        route["stress_flags"]["slope_limit_exceeded"] = over_limit
        result = {
            "scenario": scenario,
            "code": "SLOPE_LIMIT",
            "severity": "high" if over_limit else "warn",
            "reason": (
                f"Slope plus DEM error reaches {stressed_slope}°, above the {limit}° limit."
                if over_limit else f"Slope plus DEM error reaches {stressed_slope}°, within the {limit}° limit."
            ),
            "extra_distance_km": None,
            "no_route": False,
        }

    results.append(result)
    high = any(item.get("severity") == "high" for item in results)
    if high and segment["verdict"] != VERDICT_FRAGILE:
        segment["verdict"] = VERDICT_FRAGILE
    return result


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------

def build_brief(route, params):
    mission = compute_mission(route, params)
    well_supported = [
        {"id": segment["id"], "verdict": segment["verdict"]}
        for segment in route["segments"] if segment["verdict"] == VERDICT_SUPPORTED
    ]
    caveats = [
        {"segment_id": segment["id"], "flags": segment["flags"]}
        for segment in route["segments"] if segment["flags"]
    ]
    stress_results = [
        result for results in route["stress_results"].values() for result in results
    ]
    weak = next(
        (segment for segment in route["segments"] if segment["verdict"] == VERDICT_FRAGILE),
        next((segment for segment in route["segments"] if segment["verdict"] == VERDICT_CHECK), None),
    )
    sources = []
    seen = set()
    for segment in route["segments"]:
        dossier = build_dossier(route, segment["id"])
        for product in dossier["products"]:
            if product["id"] in seen:
                continue
            seen.add(product["id"])
            sources.append(product)
    return {
        "route_id": route["route_id"],
        "target": route["target"],
        "mission_verdict": mission["verdict"],
        "turn_back_clock": mission["clock"],
        "resource_margins": mission["safety_margins"],
        "well_supported": well_supported,
        "caveats": caveats,
        "stress_test_results": stress_results,
        "next_observation": weak["needed"] if weak else "No additional observation identified; re-check assumptions before departure.",
        "data_status": DATA_STATUS,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Auxiliary listings
# ---------------------------------------------------------------------------

def registry(box=None):
    rows = []
    for product in PRODUCTS:
        rows.append({
            **product,
            "acquired": "2021-02-18" if product["src"] == "PDS" else None,
            "is_placeholder": product["src"] != "PDS",
            "data_status": DATA_STATUS,
        })
    return rows


def rover_photos(rover="perseverance", sol=1):
    """No live NASA key is configured; return an empty context feed honestly."""
    return []


def basemap_seed(layer=""):
    return abs(hash(layer)) % 10_000
