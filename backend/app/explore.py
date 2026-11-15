"""Bounded exploration recommendations using measured orbital footprints."""
import math
from . import data_sources as sources
from .grid import from_dem
from .routing import plan_route, NoRouteError
from .prototype_audit import in_polygon
from .evidence import audit_segment
from .params import get_params
from .resources import estimate_resources, evaluate_mission


def suggest(payload):
    site = payload.get('site', 'jezero')
    claim = payload.get('claim', 'terrain')
    if site not in sources.SITES or claim not in {'terrain', 'current', 'thermal'}:
        raise ValueError('Unknown site or claim')
    bounds = sources.SITES[site]
    bbox = (*[bounds['lo'][0], bounds['la'][0]], bounds['lo'][1], bounds['la'][1])
    start = payload.get('start')
    assumed = start is None
    if assumed:
        start = [(bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2]
    if not isinstance(start, list) or len(start) != 2 or any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in start):
        raise ValueError('Start must be two finite coordinates')
    if not bbox[0] <= start[0] <= bbox[2] or not bbox[1] <= start[1] <= bbox[3]:
        raise ValueError('Start lies outside the selected site')
    grid = from_dem(sources.get_dem(bbox))
    origin = grid.cell(*start)
    footprints = sources.footprints(bbox)
    products = [p for p in footprints['fps'] if p.get('src') == 'ODE']
    instruments = {'THEMIS'} if claim == 'thermal' else {'HiRISE', 'CTX'}
    relevant = [p for p in products if p.get('inst') in instruments]
    params = get_params()
    limit = float(params['slope_limit_deg']['value'])
    candidates = {}
    for y in range(grid.height):
        for x in range(grid.width):
            cell = (x, y)
            point = list(grid.coordinate(*cell))
            hits = [p for p in relevant if in_polygon(point, p.get('poly', []))]
            if cell != origin and hits:
                quality = min(float(p.get('res') or math.inf) for p in hits)
                candidates[cell] = (quality, math.dist(cell, origin), point)
    results = []
    unreachable = 0
    over_budget = 0
    for cell, (_, _, point) in sorted(candidates.items(), key=lambda item: (item[1][1], item[1][0], item[0]))[:24]:
        try:
            route = plan_route(grid, [start, point], limit)
        except NoRouteError:
            unreachable += 1
            continue
        segment = route['segments'][0]
        audit = audit_segment('preview', segment['coordinates'], products,
                              float(params['boulder_tolerance']['value']), claim,
                              segment['max_slope_deg'], limit,
                              age_limit_years=float(params['current_observation_age_limit_years']['value']))
        resources = estimate_resources(route['segments'], params, grid.resolution_m)
        mission = evaluate_mission(resources, [])
        if mission['verdict'] == 'NO-GO':
            over_budget += 1
            continue
        coverage = sum(any(in_polygon(p, product.get('poly', [])) for product in relevant) for p in segment['coordinates']) / len(segment['coordinates'])
        results.append({'destination': point, 'cell': cell, 'preview': route['main'], 'coverage': coverage,
                        'verdict': audit['verdict'], 'warnings': audit['flags'], 'resources': resources,
                        'resource_margins': mission['safety_margins'], 'distance_km': segment['distance_km']})
    results.sort(key=lambda r: (-r['coverage'], {'Supported':0,'Check':1,'Fragile':2}.get(r['verdict'],3), -min(r['resources']['safety_margins_worst'].values()), r['distance_km'], r['destination']))
    selected = []
    for result in results:
        if all(math.dist(result['cell'], old['cell']) >= 2 for old in selected):
            selected.append(result)
        if len(selected) == 3:
            break
    if not relevant:
        message = 'No real observation footprints are available for this claim. Retry the data sources or choose another claim.'
    elif not candidates:
        message = 'Real observations are loaded, but no covered destinations fall on the terrain grid in this area.'
    elif over_budget:
        message = 'Covered destinations were found, but tested routes exceed the current resource or mission limits. Move the start closer to a footprint or review mission assumptions.'
    else:
        message = 'Covered destinations were found, but no tested route satisfies the slope limit from this start.'
    return {'diagnostics': {'real_products': len(products), 'claim_products': len(relevant),
                            'covered_cells': len(candidates), 'unreachable': unreachable,
                            'over_budget': over_budget, 'source_errors': footprints.get('errs', [])},
            'start': start, 'start_source': 'site_center' if assumed else 'waypoint', 'suggestions': selected,
            'message': '' if selected else message}
