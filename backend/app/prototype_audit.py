"""Testable Python port of the reference prototype's nine audit validations.

This preserves the prototype flag identifiers and verdict behavior as a
characterization contract; Phase 2 will expose the updated public verdict names.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math

KM=59.15
LIMIT=15
MOLA=463
STALE_YR=.1

def samples(a,b,n=30):
    return [(a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n) for i in range(n+1)]

def distance(a,b):
    return math.hypot((a[1]-b[1])*KM,(a[0]-b[0])*KM*math.cos(math.radians((a[1]+b[1])/2)))

def in_polygon(point, polygon):
    x,y=point; inside=False
    for i in range(len(polygon)):
        j=(i-1)%len(polygon); xi,yi=polygon[i];xj,yj=polygon[j]
        if (yi>y)!=(yj>y) and x<(xj-xi)*(y-yi)/(yj-yi)+xi:inside=not inside
    return inside

def coverage(points, instrument, products):
    items=[p for p in products if p["inst"]==instrument]
    if not items:return {"frac":0.0,"best":None,"all":[]}
    hits=0; best=None; found=[]
    for point in points:
        matched=[p for p in items if in_polygon(point,p["poly"])]
        if matched:hits+=1
        for product in matched:
            if product not in found:found.append(product)
            if best is None or product["res"]<best["res"]:best=product
    return {"frac":hits/len(points),"best":best,"all":found}

def audit_segment(a,b,slope,uncertainty,obstacle_scale,claim,products,dem=None):
    pts=samples(a,b);km=distance(a,b);hi=coverage(pts,"HiRISE",products);ctx=coverage(pts,"CTX",products);flags=[]
    flags.append(("SLOPE_FROM_DEM",f"Max slope {slope:.1f}° from {dem['layer']} ({dem['res']} m/px). Coarse DEMs understate local slopes","wa") if dem else ("SLOPE_ASSUMED","Slope is a default or user value, not DEM-derived","wa"))
    flags.append(("DEM_COARSE",f"Terrain context is MOLA (~{MOLA} m/px), far coarser than a {obstacle_scale} m obstacle","wa"))
    good=False
    if hi["frac"]==1 and hi["best"]["res"]<=obstacle_scale:cls="Observed";good=True
    elif hi["frac"]==1:cls="Observed";flags.append(("IMAGE_RES_TOO_COARSE",f"HiRISE {hi['best']['res']} m/px does not resolve {obstacle_scale} m obstacles","bad"))
    elif ctx["frac"]==1:cls="Derived";flags.append(("CTX_ONLY",f"CTX ({ctx['best']['res']} m/px) covers it but cannot resolve {obstacle_scale} m obstacles","wa"))
    elif hi["frac"]>0 or ctx["frac"]>0:
        cls="Interpolated";flags.append(("PARTIAL_COVERAGE",f"HiRISE {round(hi['frac']*100)}%, CTX {round(ctx['frac']*100)}% of segment covered","bad"))
    else:cls="Unknown";flags.append(("NO_IMAGE_COVERAGE","No imagery footprint over this segment","bad"))
    sources=hi["all"]+ctx["all"]
    if hi["all"] and ctx["all"]:flags.append(("MULTI_SOURCE_SCALE",f"CTX ({ctx['best']['res']} m/px) and HiRISE ({hi['best']['res']} m/px) differ in scale; kept separate, not merged","wa"))
    if any(p["src"]=="ILLUSTRATIVE" for p in sources):flags.append(("PLACEHOLDER_DATA","Footprint is illustrative, not real coverage","bad"))
    if any(p["res_src"]=="nominal" and p["src"]=="ODE" for p in sources):flags.append(("RES_NOMINAL","Resolution missing in metadata; nominal value used","wa"))
    if claim=="current":
        flags.append(("NOT_VALID_AS_LOCAL_CURRENT_CONDITION","Orbital observations are not live local conditions. In-situ data is local to the rover and cannot be extended to this route","bad"))
        now=datetime.now(timezone.utc)
        for product in sources:
            if not product.get("date"):flags.append(("OBSERVATION_TIME_UNKNOWN",product["id"]+": no acquisition date","bad"))
            else:
                try:
                    observed=datetime.fromisoformat(product["date"].replace("Z","+00:00"))
                    if observed.tzinfo is None:observed=observed.replace(tzinfo=timezone.utc)
                    age=(now-observed).total_seconds()/31557600
                except (ValueError,TypeError):age=None
                if age is None:flags.append(("OBSERVATION_TIME_UNKNOWN",product["id"]+": no acquisition date","bad"))
                elif age>STALE_YR:flags.append(("OBSERVATION_STALE",f"{product['id']}: {age:.1f} yr old","bad"))
    verdict="NOT SUPPORTED" if slope+uncertainty>LIMIT else ("SUPPORTED" if good else "CONDITIONAL")
    if claim=="current":verdict="NOT SUPPORTED"
    if claim=="thermal":
        thermal=coverage(pts,"THEMIS",products);sources+=thermal["all"]
        if thermal["frac"]==1:flags.append(("THERMAL_REGIONAL_ONLY",f"THEMIS ({thermal['best']['res']} m/px) gives regional thermal properties, not astronaut-level surface temperature","wa"));verdict="CONDITIONAL"
        else:flags.append(("NO_THERMAL_COVERAGE",f"THEMIS covers {round(thermal['frac']*100)}% of this segment","bad"));verdict="NOT SUPPORTED"
    return {"km":km,"sl":slope,"hi":hi,"ct":ctx,"cls":cls,"flags":flags,"v":verdict,"srcs":sources,"unc":round((1-max(hi["frac"],ctx["frac"]))*km,1)}

def dem_slope(dem,a,b):
    points=samples(a,b);bounds=dem["b"]
    if not all(bounds["lo0"]<=p[0]<=bounds["lo1"] and bounds["la0"]<=p[1]<=bounds["la1"] for p in points):return None
    w,h,z=dem["w"],dem["h"],dem["z"]
    def elev(lon,lat):
        fx=(lon-bounds["lo0"])/(bounds["lo1"]-bounds["lo0"])*(w-1);fy=(bounds["la1"]-lat)/(bounds["la1"]-bounds["la0"])*(h-1)
        x=max(0,min(w-2,int(fx)));y=max(0,min(h-2,int(fy)));tx=max(0,min(1,fx-x));ty=max(0,min(1,fy-y))
        return z[y*w+x]*(1-tx)*(1-ty)+z[y*w+x+1]*tx*(1-ty)+z[(y+1)*w+x]*(1-tx)*ty+z[(y+1)*w+x+1]*tx*ty
    dl=(bounds["lo1"]-bounds["lo0"])/(w-1);dg=(bounds["la1"]-bounds["la0"])/(h-1);slopes=[]
    for lon,lat in points:
        gx=(elev(lon+dl,lat)-elev(lon-dl,lat))/(2*dl*KM*1000*math.cos(math.radians(lat)))
        gy=(elev(lon,lat+dg)-elev(lon,lat-dg))/(2*dg*KM*1000)
        slopes.append(math.degrees(math.atan(math.hypot(gx,gy))))
    return {"max":max(slopes),"mean":sum(slopes)/len(slopes),"res":dem["res"],"layer":dem["layer"]}

def meda_local(rover,a,b,radius):
    nearest=min(distance(rover,point) for point in samples(a,b))
    return {"d":nearest,"ok":nearest<=radius}
