import pytest
from backend.app.grid import from_elevations
from backend.app.routing import NoRouteError, find_path, plan_route

BOUNDS={"lo0":0.0,"la0":0.0,"lo1":0.1,"la1":0.1}

def flat_grid(width=31,height=31):
    return from_elevations([0.0]*(width*height),width,height,BOUNDS)

def test_astar_returns_path_from_start_to_goal():
    grid=flat_grid()
    path=find_path(grid,(1,1),(29,29),15)
    assert path[0]==(1,1) and path[-1]==(29,29)
    assert all(abs(a[0]-b[0])<=1 and abs(a[1]-b[1])<=1 for a,b in zip(path,path[1:]))

def test_steep_wall_is_blocked():
    width=height=15
    values=[0.0 if x<7 else 1000.0 for y in range(height) for x in range(width)]
    grid=from_elevations(values,width,height,BOUNDS)
    with pytest.raises(NoRouteError):
        find_path(grid,(1,7),(13,7),10)

def test_waypoints_are_preserved_and_alternate_differs():
    grid=flat_grid()
    a=grid.coordinate(2,15);b=grid.coordinate(28,15)
    result=plan_route(grid,[a,b],15)
    assert result["waypoint_cells"]==[[2,15],[28,15]]
    assert result["main"]["cells"][0]==[2,15] and result["main"]["cells"][-1]==[28,15]
    assert result["alternate"] is not None
    assert result["alternate"]["cells"]!=result["main"]["cells"]

def test_multiple_waypoint_legs_become_segments():
    grid=flat_grid()
    waypoints=[grid.coordinate(2,2),grid.coordinate(15,10),grid.coordinate(28,28)]
    result=plan_route(grid,waypoints,15)
    assert len(result["segments"])==2
    assert result["segments"][0]["cells"][0]==[2,2]
    assert result["segments"][1]["cells"][-1]==[28,28]
