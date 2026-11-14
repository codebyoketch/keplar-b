"""Slope-aware A* routing with waypoint legs and a distinct alternate path."""
from __future__ import annotations
import heapq
import math
from .grid import MarsGrid, KM_PER_DEGREE

class NoRouteError(ValueError):
    pass


def _distance(grid: MarsGrid, a: tuple[int, int], b: tuple[int, int]) -> float:
    lon1, lat1 = grid.coordinate(*a)
    lon2, lat2 = grid.coordinate(*b)
    return math.hypot((lat2-lat1)*KM_PER_DEGREE,
                      (lon2-lon1)*KM_PER_DEGREE*math.cos(math.radians((lat1+lat2)/2)))


def _heuristic(grid, a, b):
    return _distance(grid, a, b)


def find_path(grid: MarsGrid, start: tuple[int,int], goal: tuple[int,int], slope_limit_deg: float,
              avoid: set[tuple[int,int]] | None = None,
              blocked_cells: set[tuple[int,int]] | None = None) -> list[tuple[int,int]]:
    if slope_limit_deg <= 0:
        raise ValueError("slope_limit_deg must be greater than zero")
    avoid = avoid or set()
    blocked_cells = blocked_cells or set()
    def blocked(cell):
        x,y=cell
        return cell in blocked_cells or grid.slopes_deg[grid.index(x,y)] > slope_limit_deg
    if blocked(start) or blocked(goal):
        raise NoRouteError("Waypoint is on a cell above the slope limit")
    queue=[(_heuristic(grid,start,goal),0.0,start)]
    costs={start:0.0}; parents={}; closed=set()
    while queue:
        _,cost,current=heapq.heappop(queue)
        if current in closed: continue
        if current==goal:
            path=[current]
            while current in parents:
                current=parents[current];path.append(current)
            return list(reversed(path))
        closed.add(current)
        x,y=current
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                if dx==0 and dy==0:continue
                nx,ny=x+dx,y+dy
                if not (0<=nx<grid.width and 0<=ny<grid.height):continue
                nxt=(nx,ny)
                if blocked(nxt):continue
                if nxt in avoid and nxt not in (start,goal):continue
                # Do not cut diagonally through a blocked corner.
                if dx and dy and (blocked((x+dx,y)) or blocked((x,y+dy))):continue
                slope=(grid.slopes_deg[grid.index(x,y)]+grid.slopes_deg[grid.index(nx,ny)])/2
                step=_distance(grid,current,nxt)*(1+slope/slope_limit_deg)
                new_cost=cost+step
                if new_cost < costs.get(nxt,float("inf")):
                    costs[nxt]=new_cost;parents[nxt]=current
                    heapq.heappush(queue,(new_cost+_heuristic(grid,nxt,goal),new_cost,nxt))
    raise NoRouteError("No path satisfies the configured slope limit")


def _collapse(legs):
    points=[]
    for leg in legs:
        points.extend(leg if not points else leg[1:])
    return points


def _path_summary(grid, path):
    coords=[list(grid.coordinate(*cell)) for cell in path]
    dist=sum(_distance(grid,a,b) for a,b in zip(path,path[1:]))
    maximum=max((grid.slopes_deg[grid.index(*cell)] for cell in path),default=0)
    return {"cells":[list(c) for c in path],"coordinates":coords,"distance_km":round(dist,4),
            "max_slope_deg":round(maximum,3),"elevation_type":grid.elevation_type,"slope_type":grid.slope_type}


def path_distance_km(grid: MarsGrid, path: list[tuple[int,int]]) -> float:
    return sum(_distance(grid,a,b) for a,b in zip(path,path[1:]))


def plan_route(grid: MarsGrid, waypoints: list[list[float]], slope_limit_deg: float) -> dict:
    if len(waypoints)<2:raise ValueError("At least two waypoints are required")
    cells=[grid.cell(float(point[0]),float(point[1])) for point in waypoints]
    main_legs=[find_path(grid,a,b,slope_limit_deg) for a,b in zip(cells,cells[1:])]
    main_path=_collapse(main_legs)
    avoid=set(main_path[1:-1])
    alternate_legs=[]
    try:
        for start,goal in zip(cells,cells[1:]):
            alternate_legs.append(find_path(grid,start,goal,slope_limit_deg,avoid))
        alternate_path=_collapse(alternate_legs)
        if alternate_path==main_path:alternate_path=None
    except NoRouteError:
        alternate_path=None
    return {"main":_path_summary(grid,main_path),
            "alternate":_path_summary(grid,alternate_path) if alternate_path else None,
            "segments":[_path_summary(grid,leg) for leg in main_legs],
            "waypoint_cells":[list(cell) for cell in cells]}
