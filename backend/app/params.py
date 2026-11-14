"""Crew-set assumptions, kept separate from data-derived measurements."""
import json
import math
from pathlib import Path
from threading import RLock

PARAMS_FILE=Path(__file__).resolve().parents[2]/"data"/"params.json"
_lock=RLock()

def get_params():
    with _lock:
        return json.loads(PARAMS_FILE.read_text(encoding="utf-8"))

def update_params(payload):
    current=get_params()
    if not isinstance(payload,dict) or set(payload)!=set(current):
        raise ValueError("Provide exactly the configured parameter keys")
    for key,entry in payload.items():
        if not isinstance(entry,dict) or set(entry)!={"value","unit","label"}:
            raise ValueError(f"Invalid parameter structure: {key}")
        if entry["label"]!="unvalidated assumption" or entry["unit"]!=current[key]["unit"]:
            raise ValueError(f"Parameter metadata is fixed for {key}")
        value=entry["value"]
        values=value.values() if isinstance(value,dict) else (value,)
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in values):
            raise ValueError(f"Parameter values must be non-negative numbers: {key}")
        if key in {"slope_limit_deg","boulder_tolerance","walking_speed","load_factor","coarse_terrain_distance_factor"} and any(v<=0 for v in values):
            raise ValueError(f"Parameter must be greater than zero: {key}")
        if key=="obstacle_test_radius_cells" and (not isinstance(value,int) or isinstance(value,bool)):
            raise ValueError("obstacle_test_radius_cells must be an integer")
        if key=="reserve_minimums" and (not isinstance(value,dict) or set(value)!={"oxygen","power"}):
            raise ValueError("reserve_minimums must contain oxygen and power")
    with _lock:
        PARAMS_FILE.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    return payload
