import copy
import json
import pytest
from backend.app import params

def test_assumptions_keep_explicit_unvalidated_label():
    current=params.get_params()
    assert current["slope_limit_deg"]["label"]=="unvalidated assumption"
    assert current["boulder_tolerance"]["unit"]=="meters"
    assert "walking_speed" in current

def test_params_update_accepts_values_but_rejects_metadata_changes(tmp_path,monkeypatch):
    monkeypatch.setattr(params,"PARAMS_FILE",tmp_path/"params.json")
    original={"slope_limit_deg":{"value":15,"unit":"degrees","label":"unvalidated assumption"},
              "boulder_tolerance":{"value":.5,"unit":"meters","label":"unvalidated assumption"}}
    params.PARAMS_FILE.write_text(json.dumps(original))
    changed=copy.deepcopy(original);changed["slope_limit_deg"]["value"]=12
    assert params.update_params(changed)==changed
    changed["slope_limit_deg"]["unit"]="meters"
    with pytest.raises(ValueError,match="metadata"):
        params.update_params(changed)

def test_params_reject_nonfinite_or_negative_values(tmp_path,monkeypatch):
    monkeypatch.setattr(params,"PARAMS_FILE",tmp_path/"params.json")
    original={"slope_limit_deg":{"value":15,"unit":"degrees","label":"unvalidated assumption"}}
    params.PARAMS_FILE.write_text(json.dumps(original))
    for bad in (-1,float("inf"),float("nan")):
        changed=copy.deepcopy(original);changed["slope_limit_deg"]["value"]=bad
        with pytest.raises(ValueError,match="non-negative"):
            params.update_params(changed)
