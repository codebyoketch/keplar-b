"""Port of cairn9.py's PDS ODE, USGS WMS and MOLA WCS data layer."""
from __future__ import annotations
import array
import base64
import io
import json
import math
import re
import struct
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from .cache import read_bytes, read_json, write_bytes, write_json
from .config import CACHE_DIR

SITES = {"jezero": {"la": (17.6, 19.2), "lo": (76.8, 78.4)}, "gale": {"la": (-6.2, -4.6), "lo": (137.0, 138.6)}}
NOMINAL = {"CTX": 6.0, "HiRISE": 0.25, "CRISM": 18.0, "THEMIS": 100.0}
IH = {"CTX": "MRO", "HiRISE": "MRO", "CRISM": "MRO", "THEMIS": "ODY"}
INSTS = ("CTX", "HiRISE", "CRISM", "THEMIS")
PT = {"CTX": ["EDR"], "HiRISE": ["RDRV11"], "CRISM": ["MTRDR", "TRDR", "TER"], "THEMIS": ["BTR", "ABR"]}
WMS = "https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map&SERVICE=WMS&VERSION=1.1.1"
WCS = "https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map&SERVICE=WCS&VERSION=1.0.0"
KMDEG = 59.15
_memory: dict[str, object] = {}


def _fetch(url: str, timeout: int = 30) -> bytes:
    if url in _memory:
        val = _memory[url]
        return val if isinstance(val, bytes) else json.dumps(val).encode()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cairn/3.1"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
        if body:
            write_bytes(url, body)
        return body
    except Exception:
        cached = read_bytes(url)
        if cached is None:
            raise
        return cached


def _get_json(url: str):
    if url in _memory and not isinstance(_memory[url], bytes):
        return _memory[url]
    try:
        data = json.loads(_fetch(url))
        _memory[url] = data
        return data
    except Exception:
        cached = read_json(url)
        if cached is None:
            raise
        _memory[url] = cached
        return cached


def _fk(product, *parts):
    for key, value in product.items():
        if all(term in key.lower() for term in parts) and value not in (None, ""):
            return value


def _num(value):
    try: return float(value)
    except (TypeError, ValueError): return None


def _polygon(product):
    raw = _fk(product, "footprint", "geometry") or ""
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[eE]-?\d+)?", str(raw))]
    if len(nums) >= 8:
        return [[nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)]
    south, north, west, east = (_num(_fk(product, *keys)) for keys in (("minimum", "lat"), ("maximum", "lat"), ("western", "lon"), ("eastern", "lon")))
    if None in (south, north, west, east): return None
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def _product_id(product):
    for value in product.values():
        match = re.search(r"product_id=([^&\"]+)", str(value))
        if match: return match.group(1)


def _parse_products(products, instrument, seen):
    out, dropped = [], {}
    for product in products:
        pid = _fk(product, "pdsid") or _product_id(product)
        poly = _polygon(product)
        if not pid: dropped["no id"] = dropped.get("no id", 0) + 1; continue
        if not poly: dropped["no footprint"] = dropped.get("no footprint", 0) + 1; continue
        if pid in seen: continue
        seen.add(pid)
        resolution = _num(_fk(product, "pixel", "scale")) or _num(_fk(product, "map", "scale"))
        out.append({"id": pid, "inst": instrument, "poly": poly, "res": resolution or NOMINAL[instrument],
                    "res_src": "metadata" if resolution else "nominal", "date": _fk(product, "start_time") or _fk(product, "observation_time"),
                    "proc": _fk(product, "product", "type") or _fk(product, "data", "set"), "src": "ODE"})
    return out, dropped


def _ode_url(instrument, site, extra, limit=40):
    query = dict(query="product", results="m", output="JSON", target="mars", ihid=IH[instrument], iid=instrument, limit=limit,
                 minlat=site["la"][0], maxlat=site["la"][1], westernlon=site["lo"][0], easternlon=site["lo"][1], **extra)
    return "https://oderest.rsl.wustl.edu/live2/?" + urllib.parse.urlencode(query)


class _PartialOK(Exception):
    def __init__(self, products, message): self.products, self.message = products, message


def _ode(instrument, site):
    out, seen, raw_count, dropped, note = [], set(), 0, {}, ""
    tries = [{"pt": product_type, "loc": "f"} for product_type in dict.fromkeys(PT[instrument])] + [{"pt": product_type} for product_type in dict.fromkeys(PT[instrument])]
    for extra in tries:
        if len(out) >= 20: break
        try: data = _get_json(_ode_url(instrument, site, extra))
        except Exception as exc: note = str(exc)[:50]; continue
        result = data.get("ODEResults") or {}
        products = ((result.get("Products") or {}).get("Product") or [])
        if isinstance(products, dict): products = [products]
        raw_count += len(products)
        parsed, dropped_now = _parse_products(products, instrument, seen)
        out.extend(parsed)
        for reason, count in dropped_now.items(): dropped[reason] = dropped.get(reason, 0) + count
        if not products and not note: note = (str(result.get("Status", "")) + " " + str(result.get("Error", ""))).strip()
    if not out:
        try:
            data = _get_json(_ode_url(instrument, site, {}))
            products = (((data.get("ODEResults") or {}).get("Products") or {}).get("Product") or [])
            parsed, dropped_now = _parse_products([products] if isinstance(products, dict) else products, instrument, seen)
            out.extend(parsed)
            for reason, count in dropped_now.items(): dropped[reason] = dropped.get(reason, 0) + count
        except Exception: pass
    if not out: raise RuntimeError(f"{instrument}: no usable footprint records")
    if dropped: raise _PartialOK(out, f"{instrument}: {raw_count} raw records, dropped {dropped}")
    return out


def footprints(bbox):
    bbox = (math.floor(bbox[0]*10)/10, math.floor(bbox[1]*10)/10, math.ceil(bbox[2]*10)/10, math.ceil(bbox[3]*10)/10)
    site = {"la": (bbox[1], bbox[3]), "lo": (bbox[0], bbox[2])}
    products, errors = [], []
    def one(inst):
        try: return _ode(inst, site), None
        except _PartialOK as exc: return exc.products, exc.message[:120]
        except Exception as exc: return [], f"{inst}: {type(exc).__name__}"
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found, error in pool.map(one, INSTS):
            products.extend(found)
            if error: errors.append(error)
    if products: return {"live": True, "fps": products, "errs": errors}
    center = ((site["la"][0]+site["la"][1])/2, (site["lo"][0]+site["lo"][1])/2)
    def box(south, north, west, east):
        return [[center[1]+west,center[0]+south],[center[1]+east,center[0]+south],[center[1]+east,center[0]+north],[center[1]+west,center[0]+north],[center[1]+west,center[0]+south]]
    illustrative = [("CTX",box(-.35,.35,-.4,.4),6.0),("HiRISE",box(-.06,.08,-.2,0),.25),("CRISM",box(-.12,.12,-.1,.18),18.0),("THEMIS",box(-.5,.5,-.5,.5),100.0)]
    fps = [{"id":"ILLUSTRATIVE-"+inst,"inst":inst,"poly":poly,"res":res,"res_src":"nominal","date":None,"proc":None,"src":"ILLUSTRATIVE"} for inst,poly,res in illustrative]
    return {"live":False,"errs":errors,"fps":fps}


def bbox_from_query(query):
    site = SITES.get(query.get("site", "jezero"), SITES["jezero"])
    def coord(key, default):
        try: return float(query.get(key, default))
        except (TypeError, ValueError): return float(default)
    return (coord("lo0",site["lo"][0]),coord("la0",site["la"][0]),coord("lo1",site["lo"][1]),coord("la1",site["la"][1]))


def basemap_layers():
    if "wms_layers" in _memory: return _memory["wms_layers"]
    body = _fetch(WMS+"&REQUEST=GetCapabilities").decode("utf8","replace")
    names = [name for name in re.findall(r"<Name>([^<]+)</Name>",body) if name.upper() not in ("WMS","MAPSERVER") and "north" not in name.lower() and "south" not in name.lower()]
    names = list(dict.fromkeys(names)); _memory["wms_layers"] = names
    return names


def auto_layer():
    names = basemap_layers()
    exact_mdim21 = next((name for name in names if name.lower() == "mdim21"), None)
    if exact_mdim21: return exact_mdim21
    return next((name for key in ("mdim","viking","themis","mola") for name in names if key in name.lower()), None) or (names[0] if names else None)


def get_basemap(bbox, layer=None):
    layer = layer or auto_layer()
    if not layer: raise RuntimeError("no WMS layers found")
    key = (tuple(round(v,4) for v in bbox),layer)
    memkey = "basemap:"+repr(key)
    if memkey in _memory: return _memory[memkey]
    url = WMS+"&REQUEST=GetMap&LAYERS=%s&STYLES=&SRS=EPSG:4326&BBOX=%s,%s,%s,%s&WIDTH=800&HEIGHT=800&FORMAT=image/png" % (urllib.parse.quote(layer),*bbox)
    image = _fetch(url)
    if image[:4] != b"\x89PNG": raise RuntimeError("WMS response was not PNG")
    _memory[memkey] = (image,layer)
    return image,layer


def parse_tiff(body):
    """Pure Python uncompressed TIFF parser ported from the stdlib prototype."""
    if body[:2] not in (b"II",b"MM"): raise ValueError("not a TIFF")
    order = "<" if body[:2] == b"II" else ">"
    if struct.unpack(order+"H",body[2:4])[0] != 42: raise ValueError("not a TIFF")
    offset = struct.unpack(order+"I",body[4:8])[0]
    count = struct.unpack(order+"H",body[offset:offset+2])[0]
    sizes={1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,16:8}; formats={1:"B",3:"H",4:"I",6:"b",8:"h",9:"i",11:"f",12:"d",16:"Q"}; tags={}
    for i in range(count):
        entry=body[offset+2+12*i:offset+14+12*i]
        tag,kind,n=struct.unpack(order+"HHI",entry[:8]); size=sizes.get(kind,1)*n
        data=entry[8:8+size] if size<=4 else body[struct.unpack(order+"I",entry[8:12])[0:][0]:][:size]
        if kind in formats: tags[tag]=struct.unpack(order+str(n)+formats[kind],data)
    width,height,bits=tags[256][0],tags[257][0],tags[258][0]
    if tags.get(259,(1,))[0]!=1: raise ValueError("compressed TIFF not supported")
    if 322 in tags or 324 in tags: raise ValueError("tiled TIFF not supported")
    pixels=b"".join(body[o:o+n] for o,n in zip(tags[273],tags[279]))
    code={(1,8):"B",(2,16):"h",(1,16):"H",(3,32):"f",(2,32):"i",(3,64):"d"}[(tags.get(339,(1,))[0],bits)]
    values=struct.unpack(order+str(width*height)+code,pixels[:width*height*bits//8])
    return width,height,values


_HIRISE_PATH=CACHE_DIR/"hirise_jezero"/"DTEEC_023524_1985_023379_1985_U01.IMG"


def hirise_dem(bbox, max_dimension=256):
    """Read and resample the released Jezero PDS3 HiRISE DTM for 3D display only."""
    if not _HIRISE_PATH.is_file():
        raise RuntimeError("HiRISE Jezero DTM is not installed; run backend/download_hirise_jezero.py")
    key="hirise-dem:"+repr((tuple(round(float(v),6) for v in bbox),int(max_dimension)))
    if key in _memory:return _memory[key]
    with _HIRISE_PATH.open("rb") as stream:
        header=stream.read(100_000).decode("ascii","ignore")
        projection_path=_HIRISE_PATH.with_name("ESP_023524_1985_RED_C_01_ORTHO.LBL")
        if not projection_path.is_file():
            raise RuntimeError("HiRISE map label is not installed; rerun backend/download_hirise_jezero.py")
        projection=projection_path.read_text(encoding="ascii",errors="ignore")
        label=header.split("\nEND",1)[0]+"\n"+projection.split("\nEND",1)[0]
        def field(name, cast=float):
            match=re.search(r"(?m)^\s*"+re.escape(name)+r"\s*=\s*([+-]?[0-9]+(?:\.[0-9]+)?)",label)
            if not match:raise ValueError("HiRISE label is missing "+name)
            return cast(match.group(1))
        width=field("LINE_SAMPLES",int); height=field("LINES",int)
        record_bytes=field("RECORD_BYTES",int); image_record=field("^IMAGE",int)
        data_offset=(image_record-1)*record_bytes
        west=field("WESTERNMOST_LONGITUDE"); east=field("EASTERNMOST_LONGITUDE")
        south=field("MINIMUM_LATITUDE"); north=field("MAXIMUM_LATITUDE")
        valid_min=field("VALID_MINIMUM"); valid_max=field("VALID_MAXIMUM")
        lo0=max(float(bbox[0]),west); la0=max(float(bbox[1]),south)
        lo1=min(float(bbox[2]),east); la1=min(float(bbox[3]),north)
        if lo0>=lo1 or la0>=la1:raise ValueError("Requested view does not overlap the HiRISE DTM coverage")
        x0=(lo0-west)/(east-west)*(width-1); x1=(lo1-west)/(east-west)*(width-1)
        y0=(north-la1)/(north-south)*(height-1); y1=(north-la0)/(north-south)*(height-1)
        span_x=max(1.0,x1-x0); span_y=max(1.0,y1-y0)
        scale=min(1.0,(max_dimension-1)/max(span_x,span_y))
        out_w=max(2,round(span_x*scale)+1); out_h=max(2,round(span_y*scale)+1)
        values=[]
        for oy in range(out_h):
            sy=min(height-1,max(0,round(y0+oy*(y1-y0)/max(out_h-1,1))))
            sx_start=max(0,round(x0)); sx_end=min(width-1,round(x1))
            stream.seek(data_offset+sy*record_bytes+sx_start*4)
            count=sx_end-sx_start+1
            row=struct.unpack("<"+str(count)+"f",stream.read(count*4))
            for ox in range(out_w):
                sx=min(sx_end-sx_start,max(0,round(x0+ox*(x1-x0)/max(out_w-1,1))-sx_start))
                value=row[sx]
                values.append(value if math.isfinite(value) and valid_min<=value<=valid_max else math.nan)
    valid=[value for value in values if math.isfinite(value)]
    if not valid:raise ValueError("HiRISE DTM crop contains no valid elevations")
    fill=sum(valid)/len(valid)
    arr=array.array("f",(value if math.isfinite(value) else fill for value in values))
    if sys.byteorder=="big":arr.byteswap()
    result={"b":{"lo0":lo0,"la0":la0,"lo1":lo1,"la1":la1},"w":out_w,"h":out_h,
            "z":base64.b64encode(arr.tobytes()).decode(),"res":1.0,"layer":"HiRISE stereo DTM · 1 m source",
            "value_type":"measured","source":"DTEEC_023524_1985_023379_1985_U01"}
    _memory[key]=result
    return result


def hirise_ortho(bbox, max_dimension=2048):
    """Return a small crop of the matching, released HiRISE orthoimage for 3D texturing."""
    image_path=CACHE_DIR/"hirise_jezero"/"ESP_023524_1985_RED_C_01_ORTHO.JP2"
    label_path=CACHE_DIR/"hirise_jezero"/"ESP_023524_1985_RED_C_01_ORTHO.LBL"
    if not image_path.is_file() or not label_path.is_file():
        raise RuntimeError("HiRISE orthoimage is not installed; run backend/download_hirise_jezero.py")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Install Pillow to decode the local HiRISE orthoimage") from exc
    label=label_path.read_text(encoding="ascii",errors="ignore")
    def field(name, cast=float):
        match=re.search(r"(?m)^\s*"+re.escape(name)+r"\s*=\s*([+-]?[0-9]+(?:\.[0-9]+)?)",label)
        if not match:raise ValueError("HiRISE label is missing "+name)
        return cast(match.group(1))
    width=field("LINE_SAMPLES",int); height=field("LINES",int)
    west=field("WESTERNMOST_LONGITUDE"); east=field("EASTERNMOST_LONGITUDE")
    south=field("MINIMUM_LATITUDE"); north=field("MAXIMUM_LATITUDE")
    lo0=max(float(bbox[0]),west); la0=max(float(bbox[1]),south)
    lo1=min(float(bbox[2]),east); la1=min(float(bbox[3]),north)
    if lo0>=lo1 or la0>=la1:raise ValueError("Requested view does not overlap the HiRISE orthoimage")
    x0=max(0,min(width-1,math.floor((lo0-west)/(east-west)*(width-1))))
    x1=max(x0+1,min(width,math.ceil((lo1-west)/(east-west)*(width-1))+1))
    y0=max(0,min(height-1,math.floor((north-la1)/(north-south)*(height-1))))
    y1=max(y0+1,min(height,math.ceil((north-la0)/(north-south)*(height-1))+1))
    with Image.open(image_path) as image:
        image.load()
        crop=image.crop((x0,y0,x1,y1))
        crop.thumbnail((max_dimension,max_dimension),Image.Resampling.LANCZOS)
        output=io.BytesIO(); crop.convert("RGB").save(output,format="JPEG",quality=85,optimize=True)
    return {"b":{"lo0":lo0,"la0":la0,"lo1":lo1,"la1":la1},"w":crop.width,"h":crop.height,
            "image":"data:image/jpeg;base64,"+base64.b64encode(output.getvalue()).decode(),
            "source":"ESP_023524_1985_RED_C_01_ORTHO"}


def get_dem(bbox):
    bbox=tuple(round(v,1) for v in (math.floor(bbox[0]*10)/10,math.floor(bbox[1]*10)/10,math.ceil(bbox[2]*10)/10,math.ceil(bbox[3]*10)/10))
    key="dem:"+repr(bbox)
    if key in _memory:return _memory[key]
    # Route requests use smaller bounds than the nested DEM extents prepared for offline use.
    # Crop the smallest containing prepared grid before attempting another network request.
    local_index=CACHE_DIR/"demo_dem_extents.json"
    try:
        extents=json.loads(local_index.read_text(encoding="utf-8"))
        candidates=[item for item in extents if item["b"]["lo0"]<=bbox[0] and item["b"]["la0"]<=bbox[1]
                   and item["b"]["lo1"]>=bbox[2] and item["b"]["la1"]>=bbox[3]]
        if candidates:
            source=min(candidates,key=lambda item:(item["b"]["lo1"]-item["b"]["lo0"])*(item["b"]["la1"]-item["b"]["la0"]))
            raw=base64.b64decode(source["z"]); values=struct.unpack("<"+str(source["w"]*source["h"])+"f",raw)
            sb=source["b"]; sw=source["w"]; sh=source["h"]
            width=max(2,round((bbox[2]-bbox[0])/(sb["lo1"]-sb["lo0"])*(sw-1))+1)
            height=max(2,round((bbox[3]-bbox[1])/(sb["la1"]-sb["la0"])*(sh-1))+1)
            sampled=[]
            for y in range(height):
                lat=bbox[3]-y/(height-1)*(bbox[3]-bbox[1])
                sy=min(sh-1,max(0,round((sb["la1"]-lat)/(sb["la1"]-sb["la0"])*(sh-1))))
                for x in range(width):
                    lon=bbox[0]+x/(width-1)*(bbox[2]-bbox[0])
                    sx=min(sw-1,max(0,round((lon-sb["lo0"])/(sb["lo1"]-sb["lo0"])*(sw-1))))
                    sampled.append(values[sy*sw+sx])
            arr=array.array("f",sampled)
            if sys.byteorder=="big":arr.byteswap()
            result={"b":{"lo0":bbox[0],"la0":bbox[1],"lo1":bbox[2],"la1":bbox[3]},"w":width,"h":height,
                    "z":base64.b64encode(arr.tobytes()).decode(),"res":source.get("res"),"layer":source.get("layer"),
                    "value_type":"interpolated"}
            _memory[key]=result
            return result
    except (OSError,ValueError,KeyError,TypeError,struct.error,json.JSONDecodeError):
        pass
    caps=_fetch(WCS+"&REQUEST=GetCapabilities").decode("utf8","replace")
    names=re.findall(r"<(?:\w+:)?name>([^<]+)</(?:\w+:)?name>",caps)
    candidates=[name for name in names if "mola" in name.lower() and not any(term in name.lower() for term in ("color","shade","hill","gray","grey"))]
    candidates.sort(key=lambda name:(0 if ("dem" in name.lower() or "elev" in name.lower()) else 1,len(name)))
    if not candidates:raise RuntimeError("no MOLA elevation coverage in WCS")
    mid=(bbox[1]+bbox[3])/2; width=max(32,min(600,round((bbox[2]-bbox[0])*KMDEG*1000*math.cos(math.radians(mid))/463))); height=max(32,min(600,round((bbox[3]-bbox[1])*KMDEG*1000/463)))
    last="no attempt"
    for layer in candidates[:3]:
        for fmt in ("GeoTIFF","image/tiff","GTiff"):
            url=WCS+"&REQUEST=GetCoverage&COVERAGE=%s&CRS=EPSG:4326&BBOX=%s,%s,%s,%s&WIDTH=%d&HEIGHT=%d&FORMAT=%s"%(urllib.parse.quote(layer),*bbox,width,height,urllib.parse.quote(fmt))
            try:
                body=_fetch(url)
                if body[:4] not in (b"II*\x00",b"MM\x00*"):last="WCS response was not TIFF";continue
                try:
                    import rasterio
                    from rasterio.io import MemoryFile
                    with MemoryFile(body) as mem:
                        with mem.open() as ds: values=ds.read(1).astype("float32").ravel().tolist(); tw,th=ds.width,ds.height
                except Exception:
                    tw,th,values=parse_tiff(body)
                arr=array.array("f",(float(v) for v in values))
                if sys.byteorder=="big":arr.byteswap()
                resolution=round((bbox[2]-bbox[0])*KMDEG*1000*math.cos(math.radians(mid))/tw)
                result={"b":{"lo0":bbox[0],"la0":bbox[1],"lo1":bbox[2],"la1":bbox[3]},"w":tw,"h":th,"z":base64.b64encode(arr.tobytes()).decode(),"res":resolution,"layer":layer,"value_type":"measured"}
                _memory[key]=result;return result
            except Exception as exc:last=type(exc).__name__
    raise RuntimeError("WCS gave no usable DEM: "+last)


def cache_demo_area():
    """Fetch footprints, basemap and DEM for several nested Jezero extents."""
    results=[]
    center=SITES["jezero"]
    lat=(center["la"][0]+center["la"][1])/2; lon=(center["lo"][0]+center["lo"][1])/2
    for span in (1.6,0.8,0.4):
        box=(lon-span/2,lat-span/2,lon+span/2,lat+span/2)
        status={"bbox":box}
        try:status["footprints"]=footprints(box)["live"]
        except Exception:status["footprints"]=False
        try:status["basemap_layer"]=get_basemap(box)[1]
        except Exception:status["basemap_layer"]=None
        try:status["dem_layer"]=get_dem(box)["layer"]
        except Exception:status["dem_layer"]=None
        results.append(status)
    return results


def rover_photos(rover="perseverance",sol=1,api_key="DEMO_KEY"):
    rover=rover.lower()
    if rover not in {"curiosity","opportunity","spirit","perseverance"}:raise ValueError("Unknown rover")
    try:sol_value=max(0,int(sol))
    except (TypeError,ValueError):raise ValueError("sol must be an integer")
    url=f"https://api.nasa.gov/mars-photos/api/v1/rovers/{rover}/photos?sol={sol_value}&api_key={urllib.parse.quote(api_key)}"
    try:
        photos=_get_json(url).get("photos",[])
    except Exception:photos=[]
    if photos:
        return [{"id":p.get("id"),"img_src":p.get("img_src"),"earth_date":p.get("earth_date"),"camera":(p.get("camera") or {}).get("full_name"),"label":"context image, not this exact location"} for p in photos[:24]]
    search=f"https://images-api.nasa.gov/search?media_type=image&q={urllib.parse.quote(rover+' Mars rover sol '+str(sol_value))}"
    try:items=_get_json(search).get("collection",{}).get("items",[])[:24]
    except Exception:items=[]
    return [{"id":(item.get("data") or [{}])[0].get("nasa_id"),"title":(item.get("data") or [{}])[0].get("title"),"img_src":(item.get("links") or [{}])[0].get("href"),"label":"context image, not this exact location"} for item in items]


def apod(api_key="DEMO_KEY"):
    url="https://api.nasa.gov/planetary/apod?api_key="+urllib.parse.quote(api_key)
    return _get_json(url)
