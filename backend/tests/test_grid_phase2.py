import array
import base64
import sys
import pytest
from backend.app.grid import from_dem

def payload(values,width,height):
    data=array.array("f",values)
    if sys.byteorder=="big":data.byteswap()
    return {"b":{"lo0":0,"la0":0,"lo1":.1,"la1":.1},"w":width,"h":height,
            "z":base64.b64encode(data.tobytes()).decode(),"res":463}

def test_dem_payload_builds_measured_elevation_and_derived_slope_grid():
    grid=from_dem(payload([0,0,0,10,10,10,20,20,20],3,3))
    assert (grid.width,grid.height)==(3,3)
    assert grid.elevation_type=="measured" and grid.slope_type=="derived"
    assert max(grid.slopes_deg)>0

def test_dem_dimension_mismatch_is_rejected():
    with pytest.raises(ValueError,match="dimensions"):
        from_dem(payload([1,2,3],2,2))

def test_large_dem_is_downsampled_and_resolution_adjusted():
    grid=from_dem(payload([1.0]*250*250,250,250))
    assert max(grid.width,grid.height)<=220
    assert grid.resolution_m>463
