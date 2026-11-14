"""Nine validation cases ported from cairn9.py's in-app validation suite."""
import math
import pytest
from backend.app.prototype_audit import audit_segment, dem_slope, meda_local

def square(x,y,d):return [[x,y],[x+d,y],[x+d,y+d],[x,y+d],[x,y]]
def product(inst,poly,res,date):return {"id":"TEST-"+inst,"inst":inst,"poly":poly,"res":res,"res_src":"metadata","date":date,"src":"ODE"}
def flag(result,name):return any(item[0]==name for item in result["flags"])
A=(0,0);B=(1,1);BIG=square(-1,-1,3)

def test_1_spatial_coverage_mismatch():
    e=audit_segment(A,B,8,0,.5,"terrain",[product("HiRISE",square(50,50,1),.25,"2020-01-01")])
    assert flag(e,"NO_IMAGE_COVERAGE") and e["cls"]=="Unknown" and e["v"]!="SUPPORTED"

def test_2_resolution_mismatch():
    e=audit_segment(A,B,8,0,.5,"terrain",[product("CTX",BIG,6,"2020-01-01")])
    assert flag(e,"CTX_ONLY") and flag(e,"DEM_COARSE") and e["v"]=="CONDITIONAL"

def test_3_temporal_mismatch():
    e=audit_segment(A,B,8,0,.5,"current",[product("HiRISE",BIG,.25,"2020-01-01")])
    assert flag(e,"NOT_VALID_AS_LOCAL_CURRENT_CONDITION") and flag(e,"OBSERVATION_STALE") and e["v"]=="NOT SUPPORTED"

def test_4_evidence_conflict_keeps_scales_separate():
    e=audit_segment(A,B,8,0,.5,"terrain",[product("HiRISE",BIG,.25,"2020-01-01"),product("CTX",BIG,6,"2015-01-01")])
    assert flag(e,"MULTI_SOURCE_SCALE") and len(e["srcs"])==2 and e["cls"]=="Observed"

def test_5_sensitivity_flips_verdict():
    products=[product("HiRISE",BIG,.25,"2020-01-01")]
    baseline=audit_segment(A,B,11,0,.5,"terrain",products)
    stressed=audit_segment(A,B,11,6,.5,"terrain",products)
    assert baseline["v"]=="SUPPORTED" and stressed["v"]=="NOT SUPPORTED"

def test_6_traceability():
    backed=audit_segment(A,B,8,0,.5,"terrain",[product("HiRISE",BIG,.25,"2020-01-01")])
    empty=audit_segment(A,B,8,0,.5,"terrain",[])
    assert backed["srcs"] and all(p.get("id") for p in backed["srcs"])
    assert not empty["srcs"] and flag(empty,"NO_IMAGE_COVERAGE")

def test_7_dem_slope_ramp():
    width=height=40; target=10; z=[]
    for y in range(height):
        for x in range(width):z.append(.5*x/(width-1)*KM_METERS*math.tan(math.radians(target)))
    dem={"b":{"lo0":0,"la0":0,"lo1":.5,"la1":.5},"w":width,"h":height,"z":z,"res":463,"layer":"synthetic test ramp"}
    result=dem_slope(dem,(.1,.1),(.4,.2))
    assert result is not None and abs(result["max"]-target)<.6

KM_METERS=59.15*1000

def test_8_thermal_claim_is_regional_only():
    thermal=[product("THEMIS",BIG,100,"2010-01-01")]
    covered=audit_segment(A,B,8,0,.5,"thermal",thermal)
    empty=audit_segment(A,B,8,0,.5,"thermal",[])
    assert flag(covered,"THERMAL_REGIONAL_ONLY") and covered["v"]=="CONDITIONAL"
    assert flag(empty,"NO_THERMAL_COVERAGE") and empty["v"]=="NOT SUPPORTED"

def test_9_rover_local_data():
    assert not meda_local((5,5),(0,0),(.01,.01),1)["ok"]
    assert meda_local((0,0),(0,0),(.001,.001),1)["ok"]
