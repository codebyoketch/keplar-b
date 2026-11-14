from datetime import datetime, timedelta, timezone
from backend.app.evidence import audit_segment

def square(x0,y0,x1,y1):
    return [[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]

def product(inst="HiRISE",res=.25,date=None,source="ODE",bounds=(-1,-1,1,1)):
    return {"id":f"TEST-{inst}","inst":inst,"res":res,"date":date,"src":source,
            "res_src":"metadata","poly":square(*bounds)}

ROUTE=[[-.2,0],[.2,0]]

def test_coverage_passes_when_product_covers_entire_segment():
    dossier=audit_segment("S1",ROUTE,[product()],.5)
    assert dossier["checks"]["coverage"]["status"]=="pass"

def test_coverage_fails_without_footprints_and_marks_fragile():
    dossier=audit_segment("S1",ROUTE,[],.5)
    assert dossier["checks"]["coverage"]["status"]=="fail"
    assert dossier["verdict"]=="Fragile"
    assert any(flag["code"]=="NO_IMAGE_COVERAGE" for flag in dossier["flags"])

def test_scale_check_marks_ctx_as_coarse_and_check_verdict():
    dossier=audit_segment("S1",ROUTE,[product("CTX",6)],.5)
    assert dossier["checks"]["scale"]["status"]=="warn"
    assert dossier["verdict"]=="Check"
    assert any(flag["code"]=="CTX_ONLY" for flag in dossier["flags"])

def test_age_check_flags_stale_and_current_claim_is_fragile():
    old=(datetime.now(timezone.utc)-timedelta(days=365)).date().isoformat()
    dossier=audit_segment("S1",ROUTE,[product(date=old)],.5,claim="current")
    assert dossier["checks"]["age"]["status"]=="fail"
    assert any(flag["code"]=="OBSERVATION_STALE" for flag in dossier["flags"])
    assert dossier["verdict"]=="Fragile"

def test_type_check_marks_placeholder_as_assumed():
    dossier=audit_segment("S1",ROUTE,[product(source="ILLUSTRATIVE")],.5)
    assert dossier["checks"]["type"]["value_type"]=="assumed"
    assert dossier["checks"]["type"]["status"]=="warn"
    assert any(flag["code"]=="PLACEHOLDER_DATA" for flag in dossier["flags"])

def test_type_check_reports_measured_source():
    dossier=audit_segment("S1",ROUTE,[product()],.5)
    assert dossier["checks"]["type"]["value_type"]=="measured"
    assert dossier["checks"]["type"]["status"]=="pass"
