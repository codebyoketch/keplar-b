#!/usr/bin/env python3
"""Cairn v3.0 - evidence-aware Mars planning. Stdlib only, runs in Termux.
Usage:  python cairn.py YOUR_NASA_KEY     (or: NASA_API_KEY=... python cairn.py)
Open:   http://127.0.0.1:8000
"""
import array, base64, hashlib, json, math, os, re, socket, struct, sys, zlib, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
LAN = "--lan" in sys.argv
KEY = (ARGS[0] if ARGS else os.environ.get("NASA_API_KEY", "DEMO_KEY")).strip()
PROJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cairn_project.json")
PORT = 8000
CACHE = {}

HERE = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(HERE, "cairn_cache")
os.makedirs(CDIR, exist_ok=True)
cfile = lambda u: os.path.join(CDIR, hashlib.md5(u.encode()).hexdigest())

def get(url):
    if url in CACHE:
        return CACHE[url]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cairn/3.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
        data = json.loads(body)
        if isinstance(data, dict) and (data.get("ODEResults", {}).get("Products") or "ODEResults" not in data):
            open(cfile(url), "wb").write(body)
    except Exception:
        if os.path.exists(cfile(url)):
            data = json.loads(open(cfile(url), "rb").read())
        else:
            raise
    CACHE[url] = data
    return data

SITES = {"jezero": dict(la=(17.6, 19.2), lo=(76.8, 78.4)), "gale": dict(la=(-6.2, -4.6), lo=(137.0, 138.6))}
NOMINAL = {"CTX": 6.0, "HiRISE": 0.25, "CRISM": 18.0, "THEMIS": 100.0}
IH = {"CTX": "MRO", "HiRISE": "MRO", "CRISM": "MRO", "THEMIS": "ODY"}
INSTS = ("CTX", "HiRISE", "CRISM", "THEMIS")

def fk(p, *subs):
    for k, v in p.items():
        if all(x in k.lower() for x in subs) and v not in (None, ""):
            return v

def num(v):
    try: return float(v)
    except Exception: return None

def poly_of(p):
    w = fk(p, "footprint", "geometry") or ""
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[eE]-?\d+)?", str(w))]
    if len(nums) >= 8:
        return [[nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)]
    a, b, c, d = (num(fk(p, *k)) for k in (("minimum", "lat"), ("maximum", "lat"), ("western", "lon"), ("eastern", "lon")))
    if None in (a, b, c, d): return None
    return [[c, a], [d, a], [d, b], [c, b], [c, a]]

PT = {"CTX": ["EDR"], "HiRISE": ["RDRV11"], "CRISM": ["MTRDR", "TRDR", "TER"], "THEMIS": ["BTR", "ABR"]}

def ode_query(iid, st, extra, limit=40):
    q = dict(query="product", results="m", output="JSON", target="mars", ihid=IH[iid], iid=iid, limit=limit,
             minlat=st["la"][0], maxlat=st["la"][1], westernlon=st["lo"][0], easternlon=st["lo"][1], **extra)
    return "https://oderest.rsl.wustl.edu/live2/?" + urllib.parse.urlencode(q)

def pid_from_urls(p):
    for v in p.values():
        m = re.search(r"product_id=([^&\"]+)", str(v))
        if m: return m.group(1)

def parse(prods, iid, seen):
    out, why = [], {}
    for p in prods:
        pid = fk(p, "pdsid") or pid_from_urls(p)
        pg = poly_of(p)
        if not pid: why["no id"] = why.get("no id", 0) + 1; continue
        if not pg: why["no footprint"] = why.get("no footprint", 0) + 1; continue
        if pid in seen: continue
        seen.add(pid)
        sc = num(fk(p, "pixel", "scale")) or num(fk(p, "map", "scale"))
        out.append({"id": pid, "inst": iid, "poly": pg, "res": sc or NOMINAL[iid],
                    "res_src": "metadata" if sc else "nominal", "date": fk(p, "start_time") or fk(p, "observation_time"),
                    "proc": fk(p, "product", "type") or fk(p, "data", "set"), "src": "ODE"})
    return out, why

def ode(iid, st):
    out, seen, raw, why, note = [], set(), 0, {}, ""
    tries = []
    for pt in dict.fromkeys(PT[iid]):
        tries += [{"pt": pt, "loc": "f"}, {"pt": pt}]
    for extra in tries:
        if len(out) >= 20: break
        try: d = get(ode_query(iid, st, extra))
        except Exception as e: note = str(e)[:50]; continue
        res = d.get("ODEResults") or {}
        prods = (res.get("Products") or {}).get("Product") or []
        if isinstance(prods, dict): prods = [prods]
        raw += len(prods)
        o, w = parse(prods, iid, seen)
        out += o
        for k, v in w.items(): why[k] = why.get(k, 0) + v
        if not prods and not note: note = (str(res.get("Status", "")) + " " + str(res.get("Error", ""))).strip()
    if not out:
        try:
            d = get(ode_query(iid, st, {}))
            prods = ((d.get("ODEResults") or {}).get("Products") or {}).get("Product") or []
            o, w = parse([prods] if isinstance(prods, dict) else prods, iid, seen)
            out += o
        except Exception: pass
    if not out: raise Exception("%d raw, none usable %s %s" % (raw, why, note))
    if why: raise PartialOk(out, "%d raw, dropped %s" % (raw, why))
    return out

class PartialOk(Exception):
    def __init__(self, out, msg): self.out, self.msg = out, msg

def footprints(bb):
    bb = (math.floor(bb[0] * 10) / 10, math.floor(bb[1] * 10) / 10, math.ceil(bb[2] * 10) / 10, math.ceil(bb[3] * 10) / 10)
    st = {"la": (bb[1], bb[3]), "lo": (bb[0], bb[2])}
    fps, errs = [], []
    def one(iid):
        try: return ode(iid, st), None
        except PartialOk as e: return e.out, iid + ": " + e.msg[:90]
        except Exception as e: return [], iid + ": " + str(e)[:120]
    with ThreadPoolExecutor(4) as ex:
        for o, er in ex.map(one, INSTS):
            fps += o
            if er: errs.append(er)
    if fps: return {"live": True, "fps": fps, "errs": errs}
    c = ((st["la"][0] + st["la"][1]) / 2, (st["lo"][0] + st["lo"][1]) / 2)
    box = lambda a, b, x, y: [[c[1] + x, c[0] + a], [c[1] + y, c[0] + a], [c[1] + y, c[0] + b], [c[1] + x, c[0] + b], [c[1] + x, c[0] + a]]
    ill = [("CTX", box(-.35, .35, -.4, .4), 6.0), ("HiRISE", box(-.06, .08, -.2, 0), 0.25), ("CRISM", box(-.12, .12, -.1, .18), 18.0), ("THEMIS", box(-.5, .5, -.5, .5), 100.0)]
    return {"live": False, "errs": errs, "fps": [{"id": "ILLUSTRATIVE-" + i, "inst": i, "poly": p, "res": r,
            "res_src": "nominal", "date": None, "proc": None, "src": "ILLUSTRATIVE"} for i, p, r in ill]}

WMS = "https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map&SERVICE=WMS&VERSION=1.1.1"
IMG, LAYERS = {}, []

def raw(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Cairn/3.0"}), timeout=30) as r:
            body = r.read()
        if len(body) > 200: open(cfile(url), "wb").write(body)
        return body
    except Exception:
        if os.path.exists(cfile(url)): return open(cfile(url), "rb").read()
        raise

def wms_layers():
    if not LAYERS:
        names = [n for n in re.findall(r"<Name>([^<]+)</Name>", raw(WMS + "&REQUEST=GetCapabilities").decode("utf8", "replace"))
                 if n.upper() not in ("WMS", "MAPSERVER") and "north" not in n.lower() and "south" not in n.lower()]
        LAYERS.extend(dict.fromkeys(names))
    return LAYERS

def auto_layer():
    names = wms_layers()
    return next((n for k in ("mdim", "viking", "themis", "mola") for n in names if k in n.lower()), None) or (names[0] if names else None)

def bbox(q):
    f = lambda k, d: float(q.get(k, [d])[0])
    site = SITES.get(q.get("site", ["jezero"])[0], SITES["jezero"])
    return (f("lo0", site["lo"][0]), f("la0", site["la"][0]), f("lo1", site["lo"][1]), f("la1", site["la"][1]))

def basemap(bb, layer):
    layer = layer or auto_layer()
    if not layer: raise Exception("no WMS layers found")
    key = (tuple(round(x, 4) for x in bb), layer)
    if key in IMG: return IMG[key]
    url = WMS + "&REQUEST=GetMap&LAYERS=%s&STYLES=&SRS=EPSG:4326&BBOX=%s,%s,%s,%s&WIDTH=800&HEIGHT=800&FORMAT=image/png" % (
        urllib.parse.quote(layer), bb[0], bb[1], bb[2], bb[3])
    img = raw(url)
    if img[:4] != b"\x89PNG": raise Exception("WMS replied: " + img[:120].decode("utf8", "replace"))
    if len(IMG) > 40: IMG.clear()
    IMG[key] = (img, layer)
    return IMG[key]

WCS = "https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map&SERVICE=WCS&VERSION=1.0.0"
DEMC = {}

def parse_tiff(b):
    bo = "<" if b[:2] == b"II" else ">"
    if struct.unpack(bo + "H", b[2:4])[0] != 42: raise Exception("not a TIFF")
    off = struct.unpack(bo + "I", b[4:8])[0]
    n = struct.unpack(bo + "H", b[off:off + 2])[0]
    sz = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
    fm = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}
    tg = {}
    for i in range(n):
        e = b[off + 2 + 12 * i: off + 14 + 12 * i]
        tag, typ, cnt = struct.unpack(bo + "HHI", e[:8])
        size = sz.get(typ, 1) * cnt
        rawv = e[8:8 + size] if size <= 4 else b[struct.unpack(bo + "I", e[8:12])[0]:][:size]
        if typ in fm: tg[tag] = struct.unpack(bo + str(cnt) + fm[typ], rawv)
    w, h, bits = tg[256][0], tg[257][0], tg[258][0]
    if tg.get(259, (1,))[0] != 1: raise Exception("compressed TIFF not supported")
    if 322 in tg or 324 in tg: raise Exception("tiled TIFF not supported")
    data = b"".join(b[o:o + c] for o, c in zip(tg[273], tg[279]))
    code = {(1, 8): "B", (2, 16): "h", (1, 16): "H", (3, 32): "f", (2, 32): "i", (3, 64): "d"}[(tg.get(339, (1,))[0], bits)]
    vals = struct.unpack(bo + str(w * h) + code, data[:w * h * bits // 8])
    return w, h, vals

def dem(bb):
    bb = tuple(round(x, 1) for x in (math.floor(bb[0] * 10) / 10, math.floor(bb[1] * 10) / 10, math.ceil(bb[2] * 10) / 10, math.ceil(bb[3] * 10) / 10))
    if bb in DEMC: return DEMC[bb]
    caps = raw(WCS + "&REQUEST=GetCapabilities").decode("utf8", "replace")
    names = re.findall(r"<(?:\w+:)?name>([^<]+)</(?:\w+:)?name>", caps)
    cand = [n for n in names if "mola" in n.lower() and not any(x in n.lower() for x in ("color", "shade", "hill", "gray", "grey"))]
    cand.sort(key=lambda n: (0 if ("dem" in n.lower() or "elev" in n.lower()) else 1, len(n)))
    if not cand: raise Exception("no MOLA elevation coverage in WCS (saw: %s)" % ",".join(names[:6]))
    mid = (bb[1] + bb[3]) / 2
    W = max(32, min(600, round((bb[2] - bb[0]) * KMDEG * 1000 * math.cos(math.radians(mid)) / 463)))
    Hh = max(32, min(600, round((bb[3] - bb[1]) * KMDEG * 1000 / 463)))
    last = "no attempt"
    for layer in cand[:3]:
        for fmt in ("GeoTIFF", "image/tiff", "GTiff"):
            url = WCS + "&REQUEST=GetCoverage&COVERAGE=%s&CRS=EPSG:4326&BBOX=%s,%s,%s,%s&WIDTH=%d&HEIGHT=%d&FORMAT=%s" % (
                urllib.parse.quote(layer), bb[0], bb[1], bb[2], bb[3], W, Hh, urllib.parse.quote(fmt))
            try:
                body = raw(url)
                if body[:4] not in (b"II*\x00", b"MM\x00*"): last = body[:100].decode("utf8", "replace"); continue
                w, h, vals = parse_tiff(body)
                arr = array.array("f", [float(v) for v in vals])
                if sys.byteorder == "big": arr.byteswap()
                res = round((bb[2] - bb[0]) * KMDEG * 1000 * math.cos(math.radians(mid)) / w)
                DEMC[bb] = {"b": {"lo0": bb[0], "la0": bb[1], "lo1": bb[2], "la1": bb[3]}, "w": w, "h": h,
                            "z": base64.b64encode(arr.tobytes()).decode(), "res": res, "layer": layer}
                return DEMC[bb]
            except Exception as e: last = str(e)[:100]
    raise Exception("WCS gave no usable DEM: " + last)

KMDEG = 59.15
_ICON = {}
def icon(n):
    if n in _ICON: return _ICON[n]
    rows = b""
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            d = math.hypot(x - n / 2, y - n / 2)
            row += bytes((232, 98, 63) if d < n * 0.3 else ((22, 27, 36) if d < n * 0.46 else (13, 17, 23)))
        rows += bytes(row)
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    _ICON[n] = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(rows)) + ch(b"IEND", b"")
    return _ICON[n]

MANIFEST = json.dumps({"name": "Cairn", "short_name": "Cairn", "start_url": "/", "display": "standalone", "background_color": "#0d1117",
    "theme_color": "#0d1117", "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]})
SW = """const C='cairn-v3';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(clients.claim()));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin)return;
 e.respondWith(fetch(e.request).then(r=>{if(r.ok){const c=r.clone();caches.open(C).then(x=>x.put(e.request,c))}return r}).catch(()=>caches.match(e.request)))});"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, ctype="application/json", code=200):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_POST(self):
        if self.path != "/api/project": return self.send("not found", "text/plain", 404)
        n = int(self.headers.get("Content-Length", 0))
        if n > 2_000_000: return self.send("too large", "text/plain", 413)
        body = self.rfile.read(n)
        try: json.loads(body)
        except Exception: return self.send("bad json", "text/plain", 400)
        open(PROJ, "wb").write(body)
        self.send(json.dumps({"ok": True}))
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                return self.send(PAGE, "text/html")
            if u.path == "/api/status":
                return self.send(json.dumps({"key": "custom" if KEY != "DEMO_KEY" else "DEMO_KEY"}))
            if u.path == "/api/basemap":
                img, name = basemap(bbox(q), q.get("layer", [""])[0])
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("X-Layer", name)
                self.send_header("Access-Control-Expose-Headers", "X-Layer")
                self.send_header("Content-Length", str(len(img)))
                self.end_headers()
                return self.wfile.write(img)
            if u.path == "/manifest.json": return self.send(MANIFEST, "application/manifest+json")
            if u.path == "/sw.js": return self.send(SW, "application/javascript")
            if u.path in ("/icon-192.png", "/icon-512.png"):
                b = icon(192 if "192" in u.path else 512)
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(b))); self.end_headers()
                return self.wfile.write(b)
            if u.path == "/api/dem": return self.send(json.dumps(dem(bbox(q))))
            if u.path == "/api/layers":
                return self.send(json.dumps({"layers": wms_layers(), "auto": auto_layer()}))
            if u.path == "/api/project":
                return self.send(open(PROJ).read() if os.path.exists(PROJ) else "{}")
            if u.path == "/api/debug":
                st = SITES.get(q.get("site", ["gale"])[0], SITES["gale"])
                iid = q.get("iid", ["CTX"])[0]
                url = ode_query(iid, st, {"pt": PT.get(iid, "EDR"), "loc": "f"})
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Cairn/1.0"}), timeout=20) as r:
                    return self.send(url + "\n\n" + r.read(3000).decode("utf8", "replace"), "text/plain")
            if u.path == "/api/footprints":
                return self.send(json.dumps(footprints(bbox(q))))
            if u.path == "/api/apod":
                return self.send(json.dumps(get("https://api.nasa.gov/planetary/apod?api_key=" + urllib.parse.quote(KEY))))
            if u.path == "/api/images":
                term = q.get("q", ["mars surface"])[0][:80]
                d = get("https://images-api.nasa.gov/search?media_type=image&q=" + urllib.parse.quote(term))
                out = []
                for it in d["collection"]["items"][:24]:
                    m = it["data"][0]
                    out.append({"id": m.get("nasa_id"), "title": m.get("title"),
                                "date": m.get("date_created"), "center": m.get("center"),
                                "desc": (m.get("description") or "")[:400],
                                "thumb": (it.get("links") or [{}])[0].get("href"),
                                "url": "https://images.nasa.gov/details/" + str(m.get("nasa_id"))})
                return self.send(json.dumps(out))
            self.send("not found", "text/plain", 404)
        except Exception as e:
            self.send(json.dumps({"error": str(e)}), code=502)

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cairn</title><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0d1117"><link rel="icon" href="/icon-192.png"><style>
:root{--bg:#0d1117;--card:#161b24;--line:#283040;--tx:#e8ecf2;--mu:#8b95a7;--ac:#e8623f;--ok:#3fb97a;--wa:#e8b341;--bad:#e5484d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 system-ui,sans-serif;padding:14px 14px 80px}
h1{font-size:26px;margin:2px 0}h1 span{color:var(--ac)}.mu{color:var(--mu);font-size:13px}
nav{display:flex;gap:6px;margin:10px 0;position:sticky;top:0;background:var(--bg);padding:6px 0;z-index:2;overflow-x:auto}
nav button,.seg button{flex:1 0 auto;padding:9px 12px;border:1px solid var(--line);background:var(--card);color:var(--mu);border-radius:10px;font-size:14px}
nav button.on,.seg button.on{color:var(--tx);border-color:var(--ac)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:10px}
input,select{width:100%;padding:9px;border-radius:10px;border:1px solid var(--line);background:#0d1117;color:var(--tx);font-size:15px}
input[type=range]{padding:0}input[type=checkbox]{width:auto}label{display:block;font-size:13px;color:var(--mu);margin:8px 0 3px}
.go{padding:10px 14px;background:var(--ac);color:#fff;border:0;border-radius:10px;font-size:15px;margin-right:6px}
.row{display:flex;gap:8px}.seg{display:flex;gap:6px;margin:8px 0}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line);margin:2px 4px 2px 0}
.ok{color:var(--ok);border-color:var(--ok)}.wa{color:var(--wa);border-color:var(--wa)}.bad{color:var(--bad);border-color:var(--bad)}
canvas{width:100%;max-width:100%;aspect-ratio:1;background:#0a0e14;border:1px solid var(--line);border-radius:12px;touch-action:manipulation;display:block}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:5px 0;border-bottom:1px solid var(--line);vertical-align:top}td:first-child{color:var(--mu);width:34%}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.grid img{width:100%;height:105px;object-fit:cover;border-radius:10px}
.hide{display:none}
@media print{body{background:#fff;color:#000}body>*:not(#br){display:none!important}#br{display:block!important}#br .go{display:none}.card{border:0}}
</style></head><body>
<h1>Cairn<span>.</span></h1><div class="mu">Every Mars decision, with its evidence. <span id="key"></span></div>
<nav><button data-t="mp" class="on">Map</button><button data-t="gp">Gaps</button><button data-t="rg">Registry</button><button data-t="ts">Tests</button><button data-t="br">Brief</button><button data-t="md">MEDA</button><button data-t="pj">Project</button><button data-t="im">NASA</button></nav>

<section id="mp">
 <div class="row"><select id="site" onchange="loadSite(this.value)"><option value="jezero">Jezero Crater</option><option value="gale">Gale Crater</option></select>
 <select id="claim" onchange="render()"><option value="terrain">Claim: terrain / bedrock</option><option value="current">Claim: current surface conditions</option><option value="thermal">Claim: thermal context</option></select></div>
 <div id="demst" class="card mu" style="margin-bottom:8px">DEM: loading&hellip;</div>
 <div id="src" class="card mu" style="margin-top:8px">Loading footprints&hellip;</div>
 <div class="mu">Layers used as evidence (turning one off is a stress test):</div>
 <div class="row" style="margin:4px 0 8px"><label><input type="checkbox" checked onchange="on.CTX=this.checked;render()"> <span style="color:#4da3ff">CTX</span></label><label><input type="checkbox" checked onchange="on.HiRISE=this.checked;render()"> <span style="color:#e8b341">HiRISE</span></label><label><input type="checkbox" checked onchange="on.CRISM=this.checked;render()"> <span style="color:#c77dff">CRISM</span></label><label><input type="checkbox" checked onchange="on.THEMIS=this.checked;render()"> <span style="color:#ff7a59">THEMIS</span></label></div>
 <div class="row" style="margin-bottom:8px"><select id="layer" onchange="loadBase()"><option value="">Basemap: auto</option></select></div>
 <div class="seg"><button id="m1" class="on" onclick="mode(1)">+ Route</button><button id="m2" onclick="mode(2)">+ Stop</button><button onclick="undo()">Undo</button><button onclick="clr()">Clear</button></div>
 <div class="seg"><button onclick="zoomAt(.5,.5,1/1.6)">Zoom +</button><button onclick="zoomAt(.5,.5,1.6)">Zoom &minus;</button><button onclick="fit()">Fit</button><button id="b3" onclick="toggle3D()">3D</button></div>
 <div class="seg"><button onclick="demo()">Demo walkthrough</button><button onclick="exportImg()">Save map image</button></div><div id="guide"></div>
 <canvas id="cv" width="700" height="700"></canvas><canvas id="cv3" class="hide" width="700" height="700"></canvas>
 <div id="x3" class="hide"><label>Relief exaggeration (visual only): <span id="exv">0.5</span></label><input type="range" id="ex" min="0" max="1.5" step="0.05" value="0.5" oninput="$('exv').textContent=this.value;build3D()"></div>
 <div id="bm" class="mu" style="margin:6px 0">Loading basemap&hellip;</div>
 <div class="card"><b>Stress tests</b>
  <label>Slope uncertainty: &plusmn;<span id="uv">0</span>&deg;</label><input type="range" id="unc" min="0" max="15" value="0" oninput="render()">
  <label>Obstacle size to resolve: <span id="ov">0.5</span> m</label><input type="range" id="obs" min="0.1" max="2" step="0.05" value="0.5" oninput="render()"></div>
 <div id="rs"></div><div id="segs"></div><div id="stops"></div>
</section>
<section id="gp" class="hide"><div id="gaps"></div></section>
<section id="rg" class="hide"><div id="reg"></div></section>
<section id="ts" class="hide"><div class="card mu">Deliberately introduced mismatches, run against the audit engine with synthetic fixtures. A pass means the audit caught the problem.</div><button class="go" onclick="tests()">Run validation tests</button><div id="tres" style="margin-top:10px"></div></section>
<section id="br" class="hide"><div class="card"><pre id="brief" style="white-space:pre-wrap;font:12px/1.5 monospace;margin:0"></pre></div><button class="go" onclick="copyBrief()">Copy</button><button class="go" onclick="window.print()">Print / PDF</button></section>
<section id="md" class="hide">
 <div class="card"><b>Rover weather (MEDA) context</b><div class="mu">Load a MEDA CSV you downloaded from the official bundle. Cairn summarises it and checks how far each route segment is from where the rover measured it. In-situ data is local to the rover and is never treated as live conditions along your route.</div>
 <label>Rover position (default is the landing site; the rover has since moved)</label><div class="row"><input id="rvla" value="18.4446" onchange="meda()"><input id="rvlo" value="77.4509" onchange="meda()"></div>
 <label>Treat data as valid within (km of rover)</label><input id="rvr" value="1" onchange="meda()">
 <div style="margin-top:10px"><button class="go" onclick="$('mf').click()">Load MEDA CSV</button><input type="file" id="mf" accept=".csv,.txt" class="hide" onchange="loadMeda(this.files[0])"></div>
 <div class="mu" style="margin-top:8px">Official data: <a style="color:var(--ac)" href="https://pds.nasa.gov/data/pds4/releases/atmos/mars2020_meda-20260811/readme.txt" target="_blank">Mars 2020 MEDA bundle readme</a></div></div>
 <div id="mres"></div></section>
<section id="pj" class="hide">
 <div class="card"><b>Take it with you</b><div class="mu">Your route, stops, view and settings. Move them between phone and PC.</div>
 <div style="margin-top:10px"><button class="go" onclick="exportP()">Export file</button><button class="go" onclick="$('imp').click()">Import file</button><input type="file" id="imp" accept=".json" class="hide" onchange="importP(this.files[0])"></div>
 <div style="margin-top:10px"><button class="go" onclick="srvSave()">Save to server</button><button class="go" onclick="srvLoad()">Load from server</button></div><div id="pjm" class="mu" style="margin-top:8px"></div></div>
 <div class="card mu"><b style="color:var(--tx)">Same project on phone and PC</b><br>1. File: Export on one device, send the file to the other (WhatsApp, Drive, cable), Import there.<br>2. Live: run Cairn with <code>--lan</code> on one device. Open the printed Wi-Fi address on the other. Both then share one saved project via &ldquo;Save / Load from server&rdquo;.<br>Your work also autosaves in this browser.</div></section>
<section id="im" class="hide">
 <div class="card"><div class="mu">NASA APOD</div><div id="apod" class="mu">Loading&hellip;</div></div>
 <div class="row"><input id="q" value="Jezero crater"><button class="go" onclick="search()">Search</button></div>
 <div id="res" class="grid" style="margin-top:10px"></div></section>

<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const SITES={jezero:{la:18.4,lo:77.6},gale:{la:-5.4,lo:137.8}};
let V={lo0:76.8,la1:19.2,span:1.6},BV=null;
const KM=59.15,LIMIT=15,MOLA=463,STALE_YR=0.1;
const COL={CTX:'#4da3ff',HiRISE:'#e8b341',CRISM:'#c77dff',THEMIS:'#ff7a59'};
let BASE=null,FP=[],LIVE=false,wp=[],stops=[],slopes=[],md=1,ERR='',on={CTX:true,HiRISE:true,CRISM:true,THEMIS:true},SITE='jezero';
const TABS=['mp','gp','rg','ts','br','md','pj','im'];
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));
 TABS.forEach(t=>$(t).classList.toggle('hide',t!==b.dataset.t));
 if(b.dataset.t==='br')brief();if(b.dataset.t==='rg')registry();});
fetch('/api/status').then(r=>r.json()).then(s=>$('key').textContent=s.key==='custom'?'\u00b7 API key active':'\u00b7 DEMO_KEY');
fetch('/api/apod').then(r=>r.json()).then(a=>$('apod').innerHTML=a.error?esc(a.error):`<b style="color:var(--tx)">${esc(a.title)}</b><br>${esc((a.explanation||'').slice(0,240))}&hellip;`);
let bt=0;
const bboxQ=v=>`lo0=${v.lo0.toFixed(4)}&la0=${(v.la1-v.span).toFixed(4)}&lo1=${(v.lo0+v.span).toFixed(4)}&la1=${v.la1.toFixed(4)}`;
function settle(){clearTimeout(bt);bt=setTimeout(()=>{loadBase();loadFP();save()},600)}
function loadBase(){const v={...V};$('bm').textContent='Loading basemap\u2026';
 fetch('/api/basemap?'+bboxQ(v)+'&layer='+encodeURIComponent($('layer').value)).then(r=>{if(!r.ok)return r.text().then(t=>{throw new Error(t)});const n=r.headers.get('X-Layer');return r.blob().then(b=>[n,b])})
 .then(([n,b])=>{const im=new Image();im.onload=()=>{BASE=im;BV=v;$('bm').innerHTML='Basemap: USGS <b>'+esc(n)+'</b>. Regional context only, <u>not evidence</u>.';redraw();if(T3)build3D()};im.src=URL.createObjectURL(b)})
 .catch(e=>{$('bm').textContent='Basemap unavailable: '+String(e.message).slice(0,140)})}
function loadFP(){loadDEM();if(V.span>3.5){$('src').textContent='Zoom in to load footprints.';return}
 fetch('/api/footprints?'+bboxQ(V)).then(r=>r.json()).then(d=>{LIVE=d.live;ERR=(d.errs||[])[0]||'';
  if(d.live){FP=FP.filter(p=>p.src==='ODE');const ids=new Set(FP.map(p=>p.id));d.fps.forEach(p=>{if(!ids.has(p.id))FP.push(p)})}else if(!FP.length)FP=d.fps;
  $('src').innerHTML=LIVE?`<span class="tag ok">LIVE</span> ${FP.length} real footprints from NASA PDS (${['CTX','HiRISE','CRISM','THEMIS'].map(i=>i+' '+FP.filter(p=>p.inst===i).length).join(', ')}).${(d.errs||[]).length?' <span class="tag wa">note</span> '+esc(d.errs.join('; ')):''}`
  :`<span class="tag bad">ILLUSTRATIVE</span> PDS ODE unreachable${ERR?' ('+esc(ERR)+')':''}. Footprints are <b>placeholders</b>, not real coverage.`;render()}).catch(()=>{})}
function loadSite(k){SITE=k;const c=SITES[k];V={lo0:c.lo-0.8,la1:c.la+0.8,span:1.6};FP=[];wp=[];stops=[];slopes=[];BASE=null;render();loadBase();loadFP()}
function fit(){const pts=[...wp,...stops];if(!pts.length)return loadSite(SITE);
 const lo=pts.map(p=>p[0]),la=pts.map(p=>p[1]),sp=Math.max(Math.max(...lo)-Math.min(...lo),Math.max(...la)-Math.min(...la),0.05)*1.5;
 V={lo0:(Math.min(...lo)+Math.max(...lo))/2-sp/2,la1:(Math.min(...la)+Math.max(...la))/2+sp/2,span:sp};redraw();settle()}
function zoomAt(fx,fy,f){const lo=V.lo0+fx*V.span,la=V.la1-fy*V.span;V.span=Math.min(8,Math.max(0.02,V.span*f));V.lo0=lo-fx*V.span;V.la1=la+fy*V.span;redraw();settle()}
fetch('/api/layers').then(r=>r.json()).then(d=>{$('layer').innerHTML='<option value="">Basemap: auto ('+esc(d.auto||'?')+')</option>'+(d.layers||[]).map(n=>`<option>${esc(n)}</option>`).join('')}).catch(()=>{});

// ---- project save/restore ----
const state=()=>({cairn:2,site:SITE,view:V,wp,stops,slopes,claim:$('claim').value,unc:$('unc').value,obs:$('obs').value,on,layer:$('layer').value});
function save(){try{localStorage.setItem('cairn',JSON.stringify(state()))}catch(e){}}
function apply(o){if(!o||!o.view)return false;SITE=o.site||'jezero';$('site').value=SITE;V=o.view;wp=o.wp||[];stops=o.stops||[];slopes=o.slopes||[];
 $('claim').value=o.claim||'terrain';$('unc').value=o.unc||0;$('obs').value=o.obs||0.5;on={...on,...(o.on||{})};if(o.layer)$('layer').value=o.layer;return true}
function exportP(){const b=new Blob([JSON.stringify(state(),null,1)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='cairn-project.json';a.click();$('pjm').textContent='Exported.'}
function importP(f){if(!f)return;const r=new FileReader();r.onload=()=>{try{if(apply(JSON.parse(r.result))){FP=[];BASE=null;render();loadBase();loadFP();save();$('pjm').textContent='Imported.'}else $('pjm').textContent='Not a Cairn project file.'}catch(e){$('pjm').textContent='Could not read file.'}};r.readAsText(f)}
function srvSave(){fetch('/api/project',{method:'POST',body:JSON.stringify(state())}).then(r=>r.ok?'Saved to this server.':'Save failed.').then(t=>$('pjm').textContent=t).catch(()=>$('pjm').textContent='Save failed.')}
function srvLoad(){fetch('/api/project').then(r=>r.json()).then(o=>{if(apply(o)){FP=[];BASE=null;render();loadBase();loadFP();save();$('pjm').textContent='Loaded from server.'}else $('pjm').textContent='No saved project on this server yet.'}).catch(()=>$('pjm').textContent='Load failed.')}

// ---- geometry ----
const vlat=()=>V.la1-V.span/2;
const px=(lo,la,v=V,S=700)=>[(lo-v.lo0)/v.span*S,(v.la1-la)/v.span*S];
const unpx=(x,y)=>[V.lo0+x/700*V.span,V.la1-y/700*V.span];
const dist=(a,b)=>Math.hypot((a[1]-b[1])*KM,(a[0]-b[0])*KM*Math.cos(vlat()*Math.PI/180));
function inPoly(pt,poly){let c=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){
 const[xi,yi]=poly[i],[xj,yj]=poly[j];if((yi>pt[1])!=(yj>pt[1])&&pt[0]<(xj-xi)*(pt[1]-yi)/(yj-yi)+xi)c=!c}return c}
const samples=(a,b,n=30)=>Array.from({length:n+1},(_,i)=>[a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n]);
const FPa=()=>FP.filter(p=>on[p.inst]);
let DEMS=[],SPD=2,MEDA=null,DS=-1;
const age=d=>{const t=Date.parse(d);return isNaN(t)?null:(Date.now()-t)/3.15576e10};

// ---- DEM (real elevation) ----
const demHas=(d,p)=>p[0]>=d.b.lo0&&p[0]<=d.b.lo1&&p[1]>=d.b.la0&&p[1]<=d.b.la1;
function elev(d,lo,la){const fx=(lo-d.b.lo0)/(d.b.lo1-d.b.lo0)*(d.w-1),fy=(d.b.la1-la)/(d.b.la1-d.b.la0)*(d.h-1);
 const x0=Math.max(0,Math.min(d.w-2,Math.floor(fx))),y0=Math.max(0,Math.min(d.h-2,Math.floor(fy))),tx=Math.min(1,Math.max(0,fx-x0)),ty=Math.min(1,Math.max(0,fy-y0)),z=(x,y)=>d.z[y*d.w+x];
 return z(x0,y0)*(1-tx)*(1-ty)+z(x0+1,y0)*tx*(1-ty)+z(x0,y0+1)*(1-tx)*ty+z(x0+1,y0+1)*tx*ty}
function slopeAt(d,lo,la){const dl=(d.b.lo1-d.b.lo0)/(d.w-1),dg=(d.b.la1-d.b.la0)/(d.h-1),cx=KM*1000*Math.cos(la*Math.PI/180);
 const gx=(elev(d,lo+dl,la)-elev(d,lo-dl,la))/(2*dl*cx),gy=(elev(d,lo,la+dg)-elev(d,lo,la-dg))/(2*dg*KM*1000);return Math.atan(Math.hypot(gx,gy))*180/Math.PI}
function demSlope(list,a,b){const pts=samples(a,b),d=list.find(t=>pts.every(p=>demHas(t,p)));if(!d)return null;
 const s=pts.map(p=>slopeAt(d,p[0],p[1]));return{max:s.reduce((x,y)=>Math.max(x,y),0),mean:s.reduce((x,y)=>x+y,0)/s.length,res:d.res,layer:d.layer}}
function loadDEM(){if(V.span>3.5)return;
 fetch('/api/dem?'+bboxQ(V)).then(r=>r.json()).then(d=>{
  if(d.error){$('demst').innerHTML='<span class="tag wa">DEM</span> unavailable: '+esc(String(d.error).slice(0,120))+'. Slopes use your assumed values.';return}
  const bin=atob(d.z),u8=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u8[i]=bin.charCodeAt(i);
  d.z=new Float32Array(u8.buffer);DEMS=DEMS.filter(t=>t.b.lo0!==d.b.lo0||t.b.la0!==d.b.la0);DEMS.push(d);if(DEMS.length>6)DEMS.shift();
  $('demst').innerHTML=`<span class="tag ok">DEM</span> ${esc(d.layer)}, ~${d.res} m/px. Real elevation, but coarse: it smooths out steep local slopes.`;render()}).catch(()=>{})}

// ---- evidence audit engine ----
function covBy(pts,inst){const f=FPa().filter(p=>p.inst===inst);if(!f.length)return{frac:0,best:null,all:[]};
 let hit=0,best=null;const all=new Set();pts.forEach(p=>{const h=f.filter(x=>inPoly(p,x.poly));if(h.length)hit++;h.forEach(x=>{all.add(x);if(!best||x.res<best.res)best=x})});
 return{frac:hit/pts.length,best,all:[...all]}}
function auditSeg(a,b,sl,u,scale,claim,dem){
 const pts=samples(a,b),km=dist(a,b),hi=covBy(pts,'HiRISE'),ct=covBy(pts,'CTX'),flags=[];
 flags.push(dem?['SLOPE_FROM_DEM',`Max slope ${(+sl).toFixed(1)}\u00b0 from ${dem.layer} (${dem.res} m/px). Coarse DEMs understate local slopes`,'wa']:['SLOPE_ASSUMED','Slope is a default or user value, not DEM-derived','wa']);
 flags.push(['DEM_COARSE',`Terrain context is MOLA (~${MOLA} m/px), far coarser than a ${scale} m obstacle`,'wa']);
 let cls,good=false;
 if(hi.frac===1&&hi.best.res<=scale){cls='Observed';good=true}
 else if(hi.frac===1){cls='Observed';flags.push(['IMAGE_RES_TOO_COARSE',`HiRISE ${hi.best.res} m/px does not resolve ${scale} m obstacles`,'bad'])}
 else if(ct.frac===1){cls='Derived';flags.push(['CTX_ONLY',`CTX (${ct.best.res} m/px) covers it but cannot resolve ${scale} m obstacles`,'wa'])}
 else if(hi.frac>0||ct.frac>0){cls='Interpolated';flags.push(['PARTIAL_COVERAGE',`HiRISE ${Math.round(hi.frac*100)}%, CTX ${Math.round(ct.frac*100)}% of segment covered`,'bad'])}
 else{cls='Unknown';flags.push(['NO_IMAGE_COVERAGE','No imagery footprint over this segment','bad'])}
 const srcs=[...hi.all,...ct.all];
 if(hi.all.length&&ct.all.length)flags.push(['MULTI_SOURCE_SCALE',`CTX (${ct.best.res} m/px) and HiRISE (${hi.best.res} m/px) differ in scale; kept separate, not merged`,'wa']);
 if(srcs.some(x=>x.src==='ILLUSTRATIVE'))flags.push(['PLACEHOLDER_DATA','Footprint is illustrative, not real coverage','bad']);
 if(srcs.some(x=>x.res_src==='nominal'&&x.src==='ODE'))flags.push(['RES_NOMINAL','Resolution missing in metadata; nominal value used','wa']);
 if(claim==='current'){
  flags.push(['NOT_VALID_AS_LOCAL_CURRENT_CONDITION','Orbital observations are not live local conditions. In-situ data (e.g. MEDA) is local to the rover and cannot be extended to this route','bad']);
  srcs.forEach(x=>{const y=age(x.date);if(y==null)flags.push(['OBSERVATION_TIME_UNKNOWN',x.id+': no acquisition date','bad']);else if(y>STALE_YR)flags.push(['OBSERVATION_STALE',`${x.id}: ${y.toFixed(1)} yr old`,'bad'])})}
 let v=(+sl+u>LIMIT)?'NOT SUPPORTED':(good?'SUPPORTED':'CONDITIONAL');
 if(claim==='current')v='NOT SUPPORTED';
 if(claim==='thermal'){const th=covBy(pts,'THEMIS');srcs.push(...th.all);
  if(th.frac===1){flags.push(['THERMAL_REGIONAL_ONLY',`THEMIS (${th.best.res} m/px) gives regional thermal properties, not astronaut-level surface temperature`,'wa']);v='CONDITIONAL'}
  else{flags.push(['NO_THERMAL_COVERAGE',`THEMIS covers ${Math.round(th.frac*100)}% of this segment`,'bad']);v='NOT SUPPORTED'}}
 return{km,sl,hi,ct,cls,flags,v,srcs,unc:Math.round((1-Math.max(hi.frac,ct.frac))*km*10)/10}}
function evalSeg(i,u,sc,cl){const a=wp[i],b=wp[i+1],o=slopes[i],dm=(o==null)?demSlope(DEMS,a,b):null;
 const e=auditSeg(a,b,dm?dm.max:(o??8),u,sc,cl,dm);if(dm)e.srcs.push({id:'DEM '+dm.layer,inst:'DEM',res:dm.res,res_src:'metadata',date:null,src:'WCS'});e.dm=dm;return e}
const vc=v=>v==='SUPPORTED'?'ok':v==='CONDITIONAL'?'wa':'bad';
function evalStop(s){
 const cr=FPa().filter(p=>p.inst==='CRISM'),dir=cr.find(p=>inPoly(s,p.poly));
 let near=null;if(!dir&&cr.length)near=Math.min(...cr.flatMap(p=>p.poly.map(v=>dist(s,v))));
 const hi=FPa().find(p=>p.inst==='HiRISE'&&inPoly(s,p.poly));
 return{dir,near,hi,match:dir?'Direct overlap':near!=null?`Nearby (~${near.toFixed(1)} km from nearest CRISM footprint)`:'No coverage'}}
const srcLine=x=>`${x.id} (${x.inst}, ${x.res} m/px ${x.res_src}${x.date?', '+String(x.date).slice(0,10):', date n/a'}${x.proc?', '+x.proc:''})`;

// ---- map UI ----
const claim=()=>$('claim').value;
function mode(m){md=m;$('m1').classList.toggle('on',m===1);$('m2').classList.toggle('on',m===2)}
function undo(){md===2?stops.pop():wp.pop();slopes.length=Math.max(0,wp.length-1);save();render()}
function clr(){wp=[];stops=[];slopes=[];save();render()}
const stepOf=sp=>[0.005,0.01,0.02,0.05,0.1,0.2,0.5,1,2,5].find(x=>sp/x<=6)||5;
function drawMap(c,S,v,u,scale){
 const k=S/700;c.setTransform(1,0,0,1,0,0);c.clearRect(0,0,S,S);c.setLineDash([]);
 if(BASE&&BV){c.globalAlpha=.9;c.drawImage(BASE,(BV.lo0-v.lo0)/v.span*S,(v.la1-BV.la1)/v.span*S,BV.span/v.span*S,BV.span/v.span*S);c.globalAlpha=1}
 c.font=(16*k)+'px system-ui';c.lineWidth=1;const st=stepOf(v.span),dp=st<0.01?3:st<0.1?2:1;
 for(let l=Math.ceil(v.lo0/st)*st;l<v.lo0+v.span;l+=st){const x=(l-v.lo0)/v.span*S;c.strokeStyle='#ffffff22';c.beginPath();c.moveTo(x,0);c.lineTo(x,S);c.stroke();c.fillStyle='#cfd6e4';c.fillText(l.toFixed(dp)+'\u00b0E',x+3,S-6*k)}
 for(let l=Math.floor(v.la1/st)*st;l>v.la1-v.span;l-=st){const y=(v.la1-l)/v.span*S;c.strokeStyle='#ffffff22';c.beginPath();c.moveTo(0,y);c.lineTo(S,y);c.stroke();c.fillStyle='#cfd6e4';c.fillText(l.toFixed(dp)+'\u00b0',4,y-3*k)}
 FPa().forEach(p=>{c.beginPath();p.poly.forEach((q,i)=>{const[x,y]=px(q[0],q[1],v,S);i?c.lineTo(x,y):c.moveTo(x,y)});c.closePath();
  c.fillStyle=COL[p.inst]+'30';c.fill();c.strokeStyle=COL[p.inst]+(p.src==='ILLUSTRATIVE'?'88':'dd');c.lineWidth=1.5*k;c.setLineDash(p.src==='ILLUSTRATIVE'?[6,5]:[]);c.stroke();c.setLineDash([])});
 const css=getComputedStyle(document.documentElement);
 for(let i=0;i<wp.length-1;i++){const e=evalSeg(i,u,scale,claim()),[x1,y1]=px(...wp[i],v,S),[x2,y2]=px(...wp[i+1],v,S);
  c.strokeStyle=css.getPropertyValue('--'+vc(e.v));c.lineWidth=5*k;c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.stroke()}
 c.lineWidth=1;wp.forEach((w,i)=>{const[x,y]=px(w[0],w[1],v,S);c.fillStyle='#fff';c.beginPath();c.arc(x,y,9*k,0,7);c.fill();c.fillStyle='#000';c.fillText(String.fromCharCode(65+i),x-5*k,y+5*k)});
 stops.forEach((q,i)=>{const[x,y]=px(q[0],q[1],v,S);c.fillStyle='#e8623f';c.beginPath();c.moveTo(x,y-13*k);c.lineTo(x+12*k,y+9*k);c.lineTo(x-12*k,y+9*k);c.closePath();c.fill();c.fillStyle='#fff';c.fillText('S'+(i+1),x+14*k,y)})}
function redraw(){drawMap($('cv').getContext('2d'),700,V,+$('unc').value,+$('obs').value);if(T3)upd3D()}
// pan / pinch / tap
const cv=$('cv'),P=new Map();let mv=0;cv.style.touchAction='none';
cv.addEventListener('pointerdown',e=>{if(!P.size)mv=0;cv.setPointerCapture(e.pointerId);P.set(e.pointerId,[e.clientX,e.clientY])});
cv.addEventListener('pointermove',e=>{if(!P.has(e.pointerId))return;const r=cv.getBoundingClientRect(),o=P.get(e.pointerId);
 if(P.size===1){const dx=e.clientX-o[0],dy=e.clientY-o[1];mv+=Math.abs(dx)+Math.abs(dy);V.lo0-=dx/r.width*V.span;V.la1+=dy/r.height*V.span;P.set(e.pointerId,[e.clientX,e.clientY]);redraw();settle()}
 else if(P.size===2){const ids=[...P.keys()],a=P.get(ids[0]),b=P.get(ids[1]),d0=Math.hypot(a[0]-b[0],a[1]-b[1]);P.set(e.pointerId,[e.clientX,e.clientY]);
  const a2=P.get(ids[0]),b2=P.get(ids[1]),d1=Math.hypot(a2[0]-b2[0],a2[1]-b2[1]);mv+=99;
  if(d0>0&&d1>0)zoomAt(((a2[0]+b2[0])/2-r.left)/r.width,((a2[1]+b2[1])/2-r.top)/r.height,d0/d1)}});
const pup=e=>{if(P.size===1&&mv<8&&e.type==='pointerup'){const r=cv.getBoundingClientRect(),p=unpx((e.clientX-r.left)/r.width*700,(e.clientY-r.top)/r.height*700);
  if(md===1){wp.push(p);if(wp.length>1)slopes.push(null)}else stops.push(p);save();render()}P.delete(e.pointerId)};
cv.addEventListener('pointerup',pup);cv.addEventListener('pointercancel',pup);
cv.addEventListener('wheel',e=>{e.preventDefault();const r=cv.getBoundingClientRect();zoomAt((e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height,e.deltaY>0?1.2:1/1.2)},{passive:false});

// ---- 3D (visual aid only) ----
let T3=null;
function toggle3D(){const go=$('cv3').classList.contains('hide');$('cv3').classList.toggle('hide',!go);$('cv').classList.toggle('hide',go);$('x3').classList.toggle('hide',!go);$('b3').classList.toggle('on',go);
 if(go){if(!BASE){$('bm').textContent='Wait for the basemap to load, then press 3D again.';$('cv3').classList.add('hide');$('cv').classList.remove('hide');$('x3').classList.add('hide');$('b3').classList.remove('on');return}
  const go2=()=>{build3D();$('bm').innerHTML='3D relief comes from basemap <u>brightness</u>: <b>visual only, not measured elevation</b>, and never used in the audit.'};
  if(window.THREE)go2();else{const sc=document.createElement('script');sc.src='https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';sc.onload=go2;sc.onerror=()=>{$('bm').textContent='3D needs internet to load Three.js.'};document.head.appendChild(sc)}}
 else{T3=null}}
function build3D(){if(!window.THREE||!BASE)return;const c3=$('cv3'),W=c3.clientWidth||350;
 if(T3&&T3.r)T3.r.dispose();
 const r=new THREE.WebGLRenderer({canvas:c3,antialias:true});r.setPixelRatio(Math.min(devicePixelRatio,2));r.setSize(W,W,false);
 const sc=new THREE.Scene();sc.background=new THREE.Color(0x0a0e14);const cam=new THREE.PerspectiveCamera(45,1,0.1,200);
 const tc=document.createElement('canvas');tc.width=tc.height=1024;
 const tex=new THREE.CanvasTexture(tc);
 const hc=document.createElement('canvas');hc.width=hc.height=128;const hx=hc.getContext('2d');hx.drawImage(BASE,0,0,128,128);const hd=hx.getImageData(0,0,128,128).data;
 const g=new THREE.PlaneGeometry(10,10,127,127);g.rotateX(-Math.PI/2);const ex=+$('ex').value,pos=g.attributes.position;
 for(let i=0;i<pos.count;i++){const l=(hd[i*4]*0.3+hd[i*4+1]*0.59+hd[i*4+2]*0.11)/255;pos.setY(i,l*ex*1.2)}g.computeVertexNormals();
 const m=new THREE.Mesh(g,new THREE.MeshLambertMaterial({map:tex}));sc.add(m);sc.add(new THREE.AmbientLight(0xffffff,.55));const dl=new THREE.DirectionalLight(0xffffff,.8);dl.position.set(6,8,4);sc.add(dl);
 T3={r,sc,cam,tc,tex,th:0.6,ph:1.0,rad:13};upd3D();
 const el=c3,Q=new Map();el.style.touchAction='none';
 el.onpointerdown=e=>{el.setPointerCapture(e.pointerId);Q.set(e.pointerId,[e.clientX,e.clientY])};
 el.onpointerup=el.onpointercancel=e=>Q.delete(e.pointerId);
 el.onpointermove=e=>{if(!Q.has(e.pointerId)||!T3)return;const o=Q.get(e.pointerId);
  if(Q.size===1){T3.th-=(e.clientX-o[0])*0.008;T3.ph=Math.min(1.5,Math.max(0.15,T3.ph-(e.clientY-o[1])*0.006))}
  else{const ids=[...Q.keys()],a=Q.get(ids[0]),b=Q.get(ids[1]),d0=Math.hypot(a[0]-b[0],a[1]-b[1]);Q.set(e.pointerId,[e.clientX,e.clientY]);
   const a2=Q.get(ids[0]),b2=Q.get(ids[1]),d1=Math.hypot(a2[0]-b2[0],a2[1]-b2[1]);if(d1>0)T3.rad=Math.min(30,Math.max(4,T3.rad*d0/d1))}
  Q.set(e.pointerId,[e.clientX,e.clientY]);cam3()};
 el.onwheel=e=>{e.preventDefault();if(T3){T3.rad=Math.min(30,Math.max(4,T3.rad*(e.deltaY>0?1.1:0.9)));cam3()}};cam3()}
function cam3(){const t=T3;if(!t)return;t.cam.position.set(t.rad*Math.sin(t.ph)*Math.sin(t.th),t.rad*Math.cos(t.ph),t.rad*Math.sin(t.ph)*Math.cos(t.th));t.cam.lookAt(0,0,0);t.r.render(t.sc,t.cam)}
function upd3D(){if(!T3||!BV)return;drawMap(T3.tc.getContext('2d'),1024,BV,+$('unc').value,+$('obs').value);T3.tex.needsUpdate=true;cam3()}

const L=i=>String.fromCharCode(65+i)+'\u2192'+String.fromCharCode(66+i);
function render(){
 const u=+$('unc').value,scale=+$('obs').value,cl=claim();$('uv').textContent=u;$('ov').textContent=scale;redraw();
 $('segs').innerHTML=wp.slice(1).map((_,i)=>{const e=evalSeg(i,u,scale,cl),b=evalSeg(i,0,0.5,cl);
  return `<div class="card"><b>Segment ${L(i)}</b> <span class="mu">${e.km.toFixed(1)} km</span>
  <div style="margin:6px 0"><span class="tag">${e.cls}</span><span class="tag ${vc(e.v)}">${e.v}</span>${b.v!==e.v?`<span class="tag bad">FLIPPED (was ${b.v})</span>`:''}</div>
  <label>${slopes[i]!=null?'Slope OVERRIDE':(e.dm?'Slope from DEM (max)':'Slope (assumed default)')}: ${(+e.sl).toFixed(1)}&deg; / limit ${LIMIT}&deg;${e.dm?' &middot; mean '+e.dm.mean.toFixed(1)+'&deg;':''}</label>
  <input type="range" min="0" max="25" step="0.5" value="${e.sl}" onchange="slopes[${i}]=+this.value;save();render()">${slopes[i]!=null?`<button class="go" style="margin-top:6px" onclick="slopes[${i}]=null;save();render()">Use ${DEMS.length?'DEM':'default'} value</button>`:''}
  ${e.flags.map(f=>`<div><span class="tag ${f[2]}">${f[0]}</span><span class="mu">${esc(f[1])}</span></div>`).join('')}
  <div class="mu" style="margin-top:6px"><b>Sources:</b> ${e.srcs.length?e.srcs.slice(0,4).map(x=>esc(srcLine(x))).join('<br>')+(e.srcs.length>4?'<br>+'+(e.srcs.length-4)+' more':''):'none'}</div></div>`}).join('');
 $('stops').innerHTML=stops.map((s,i)=>{const e=evalStop(s);
  return `<div class="card"><b>Science stop S${i+1}</b> <span class="mu">${s[1].toFixed(3)}\u00b0N ${s[0].toFixed(3)}\u00b0E</span>
  <table><tr><td>Evidence class</td><td><span class="tag">Inferred</span> candidate interpretation</td></tr>
  <tr><td>CRISM match</td><td>${e.match}${e.dir?'<div class="mu">'+esc(srcLine(e.dir))+'</div>':''}</td></tr>
  <tr><td>HiRISE at target</td><td>${e.hi?esc(srcLine(e.hi)):'<span class="tag bad">NONE</span>'}</td></tr>
  <tr><td>Caveat</td><td class="mu">Orbital spectral signal is not a ground-truth sample.${e.dir?'':' Target is not directly under a spectral footprint.'}</td></tr></table></div>`}).join('');
 summary();meda();gaps()}

function summary(){if(wp.length<2){$('rs').innerHTML='';return}
 let km=0,pts=[],asc=0,desc=0,ok=true,prev=null;
 for(let i=0;i<wp.length-1;i++){const sm=samples(wp[i],wp[i+1]);sm.forEach((p,j)=>{if(i&&!j)return;if(pts.length)km+=dist(pts[pts.length-1].p,p);pts.push({p,km,z:null})})}
 pts.forEach(q=>{const d=DEMS.find(t=>demHas(t,q.p));if(d)q.z=elev(d,q.p[0],q.p[1]);else ok=false});
 if(ok)pts.forEach(q=>{if(prev!=null){const dz=q.z-prev;dz>0?asc+=dz:desc-=dz}prev=q.z});
 const hrs=km/SPD,hh=Math.floor(hrs),mm=Math.round((hrs-hh)*60);
 $('rs').innerHTML=`<div class="card"><b>Route</b> ${km.toFixed(1)} km &middot; ~${hh} h ${mm} min
 <label>Walking speed (km/h, assumed, not an operational estimate)</label><input value="${SPD}" onchange="SPD=Math.max(0.1,+this.value||2);render()">
 <div class="mu" style="margin-top:6px">${ok?`Ascent ${asc.toFixed(0)} m, descent ${desc.toFixed(0)} m (DEM-derived, smoothed; real terrain is rougher).`:'Elevation profile needs a DEM covering the whole route.'}</div>
 ${ok?'<canvas id="pf" width="700" height="180" style="aspect-ratio:auto;height:120px;margin-top:6px"></canvas>':''}</div>`;
 if(ok){const c=$('pf').getContext('2d'),zs=pts.map(q=>q.z),mn=Math.min(...zs),mx=Math.max(...zs),R=Math.max(mx-mn,1);c.strokeStyle='#e8623f';c.lineWidth=3;c.beginPath();
  pts.forEach((q,i)=>{const x=q.km/Math.max(km,0.001)*680+10,y=165-(q.z-mn)/R*140;i?c.lineTo(x,y):c.moveTo(x,y)});c.stroke();
  c.fillStyle='#8b95a7';c.font='18px system-ui';c.fillText(mx.toFixed(0)+' m',10,18);c.fillText(mn.toFixed(0)+' m',10,178)}}

// ---- MEDA context ----
function parseCSV(t){const L=t.split(/\r?\n/).filter(x=>x.trim()),h=L.findIndex(l=>/[A-Za-z]/.test(l)&&l.split(',').length>2);if(h<0)return null;
 const H=L[h].split(',').map(x=>x.replace(/"/g,'').trim()),cols=H.map(()=>[]);
 for(let i=h+1;i<L.length;i++){const c=L[i].split(',');for(let j=0;j<H.length;j++){const v=parseFloat(c[j]);if(isFinite(v))cols[j].push(v)}}
 return H.map((n,j)=>({n,v:cols[j]})).filter(c=>c.v.length>2).slice(0,14)}
function loadMeda(f){if(!f)return;const r=new FileReader();r.onload=()=>{const c=parseCSV(String(r.result));MEDA=c?{name:f.name,cols:c}:null;meda()};r.readAsText(f)}
function medaLocal(rv,a,b,radius){const d=Math.min(...samples(a,b).map(p=>dist(rv,p)));return{d,ok:d<=radius}}
function meda(){const o=$('mres');if(!o)return;
 if(!MEDA){o.innerHTML='<div class="card mu">No MEDA file loaded.</div>';return}
 const rv=[+$('rvlo').value,+$('rvla').value],rad=+$('rvr').value||1;
 const st=c=>{let mn=Infinity,mx=-Infinity,sm=0;for(const v of c.v){if(v<mn)mn=v;if(v>mx)mx=v;sm+=v}return[mn,sm/c.v.length,mx]};
 o.innerHTML=`<div class="card"><b>${esc(MEDA.name)}</b><div class="mu">Your file; provenance (sol, version) is not verified by Cairn.</div>
 <table>${MEDA.cols.map(c=>{const[a,m,b]=st(c);return `<tr><td>${esc(c.n)}</td><td class="mu">n=${c.v.length}<br>min ${a.toPrecision(4)} / mean ${m.toPrecision(4)} / max ${b.toPrecision(4)}</td></tr>`}).join('')}</table></div>
 <div class="card"><b>Where this applies</b><div class="mu">These readings describe the rover's surroundings only. Segments farther than ${rad} km are flagged.</div>
 ${wp.slice(1).map((_,i)=>{const m=medaLocal(rv,wp[i],wp[i+1],rad);return `<div style="margin-top:6px"><b>${L(i)}</b> ${m.d.toFixed(1)} km from rover <span class="tag ${m.ok?'wa':'bad'}">${m.ok?'NEARBY, still not live':'NOT_VALID_AS_LOCAL_CURRENT_CONDITION'}</span></div>`}).join('')||'<div class="mu">Draw a route to check it.</div>'}</div>`}

// ---- demo + export ----
const cen=p=>p?[p.poly.reduce((a,q)=>a+q[0],0)/p.poly.length,p.poly.reduce((a,q)=>a+q[1],0)/p.poly.length]:null;
const nav=t=>document.querySelector(`nav button[data-t=${t}]`).click();
const STEPS=[['Demo route','A route is drawn across real coverage. Segment colours show each verdict.',()=>{}],
 ['Open a dossier','Scroll to Segment A\u2192B: evidence class, flags and exact sources.',()=>{const e=document.querySelector('#segs .card');e&&e.scrollIntoView({behavior:'smooth'})}],
 ['Stress test','Add \u00b16\u00b0 of slope uncertainty. See whether any verdict changes (a FLIPPED tag marks one that does).',()=>{$('unc').value=6;render();$('unc').scrollIntoView({behavior:'smooth'})}],
 ['Tighten the claim','Now require resolving 0.2 m obstacles. Even HiRISE may no longer be enough.',()=>{$('obs').value=0.2;render()}],
 ['Evidence gaps','The Gaps tab ranks the next most useful observations.',()=>nav('gp')],
 ['Mission brief','Export or print the brief, with sources and caveats.',()=>nav('br')]];
function demo(){nav('mp');const f=n=>FPa().filter(p=>p.inst===n),h=cen(f('HiRISE')[0]),c=cen(f('CTX')[0]),k=cen(f('CRISM')[0]),m=[V.lo0+V.span/2,V.la1-V.span/2];
 const A=h||[m[0]-V.span*.2,m[1]-V.span*.1],B=c&&c.join()!==A.join()?c:[A[0]+V.span*.25,A[1]+V.span*.15],C=[B[0]+(B[0]-A[0])*.8,B[1]+(B[1]-A[1])*.8];
 wp=[A,B,C];slopes=[null,null];stops=[k||[(A[0]+B[0])/2,(A[1]+B[1])/2]];$('unc').value=0;$('obs').value=0.5;$('claim').value='terrain';DS=0;render();step(0)}
function step(i){DS=i;const s=STEPS[i];STEPS[i][2]();$('guide').innerHTML=`<div class="card" style="border-color:var(--ac)"><b>${i+1}/${STEPS.length} ${s[0]}</b><div class="mu">${s[1]}</div><div style="margin-top:8px">${i<STEPS.length-1?`<button class="go" onclick="step(${i+1})">Next</button>`:''}<button class="go" style="background:var(--line)" onclick="$('guide').innerHTML=''">Close</button></div></div>`}
function exportImg(){const c=$('cv3').classList.contains('hide')?$('cv'):$('cv3');if(c.id==='cv3')cam3();const a=document.createElement('a');a.href=c.toDataURL('image/png');a.download='cairn-map.png';a.click()}
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});

function gapList(){const u=+$('unc').value,sc=+$('obs').value,cl=claim(),g=[];
 wp.slice(1).forEach((_,i)=>{const e=evalSeg(i,u,sc,cl);
  if(e.cls!=='Observed'||e.flags.some(f=>f[0]==='IMAGE_RES_TOO_COARSE'))g.push({w:e.unc||e.km*0.3,t:`Acquire or inspect HiRISE-grade imagery along segment ${L(i)} (${e.unc||e.km.toFixed(1)} km lacks adequate coverage) so ${sc} m obstacles can be checked.`});
  if(e.sl+u>LIMIT-3)g.push({w:e.km*0.5,t:`Segment ${L(i)} slope is within ${Math.max(0,LIMIT-e.sl-u).toFixed(0)}\u00b0 of the limit. Get a DEM finer than MOLA before relying on it.`});
  if(cl==='current')g.push({w:e.km,t:`Segment ${L(i)}: a current-conditions claim needs an in-situ or recent local measurement, which orbital products cannot provide.`})});
 stops.forEach((s,i)=>{const e=evalStop(s);
  if(!e.hi)g.push({w:2,t:`Stop S${i+1}: no HiRISE at target. Closer imagery or a rover scout would reduce uncertainty.`});
  if(!e.dir)g.push({w:3,t:`Stop S${i+1}: spectral evidence is not directly over the target. Do not treat it as a sample.`})});
 return g.sort((a,b)=>b.w-a.w).map(x=>x.t)}
function gaps(){const g=gapList();$('gaps').innerHTML=g.length?`<div class="mu" style="margin-bottom:8px">Ranked by how much each would improve a decision (rule-based).</div>`+g.map((t,i)=>`<div class="card"><b>${i+1}.</b> ${esc(t)}</div>`).join(''):'<div class="card mu">Draw a route on the Map tab to see evidence gaps.</div>'}

function registry(){$('reg').innerHTML=`<div class="mu" style="margin-bottom:8px">Evidence registry: every product behind the map. Native resolution is never upscaled.</div>`+
 (FP.map(p=>`<div class="card"><b>${esc(p.id)}</b> <span class="tag ${p.src==='ODE'?'ok':'bad'}">${p.src}</span><table>
 <tr><td>Instrument</td><td><span style="color:${COL[p.inst]}">${p.inst}</span> (MRO)</td></tr>
 <tr><td>Resolution</td><td>${p.res} m/px <span class="mu">(${p.res_src})</span></td></tr>
 <tr><td>Acquired</td><td>${p.date?esc(String(p.date).slice(0,19)):'not supplied'}${p.date&&age(p.date)!=null?' <span class="mu">('+age(p.date).toFixed(1)+' yr ago)</span>':''}</td></tr>
 <tr><td>Processing</td><td>${esc(p.proc||'not supplied')}</td></tr>
 <tr><td>Footprint</td><td class="mu">${p.poly.length-1} vertices, as published</td></tr></table></div>`).join('')||'<div class="card mu">No products loaded.</div>')}

// ---- validation tests ----
const sq=(x,y,d)=>[[x,y],[x+d,y],[x+d,y+d],[x,y+d],[x,y]];
const mk=(inst,poly,res,date)=>({id:'TEST-'+inst,inst,poly,res,res_src:'metadata',date,src:'ODE'});
function withFP(f,fn){const s=[FP,on];FP=f;on={CTX:1,HiRISE:1,CRISM:1,THEMIS:1};try{return fn()}finally{[FP,on]=s}}
function tests(){const A=[0,0],Bp=[1,1],big=sq(-1,-1,3),R=[];
 const t=(n,d,ok)=>R.push([n,d,ok]);
 let e=withFP([mk('HiRISE',sq(50,50,1),0.25,'2020-01-01')],()=>auditSeg(A,Bp,8,0,0.5,'terrain'));
 t('1 Spatial coverage mismatch','Target outside the footprint must be flagged',e.flags.some(f=>f[0]==='NO_IMAGE_COVERAGE')&&e.cls==='Unknown'&&e.v!=='SUPPORTED');
 e=withFP([mk('CTX',big,6,'2020-01-01')],()=>auditSeg(A,Bp,8,0,0.5,'terrain'));
 t('2 Resolution mismatch','Regional product cannot support human-scale obstacle claim',e.flags.some(f=>f[0]==='CTX_ONLY')&&e.flags.some(f=>f[0]==='DEM_COARSE')&&e.v==='CONDITIONAL');
 e=withFP([mk('HiRISE',big,0.25,'2020-01-01')],()=>auditSeg(A,Bp,8,0,0.5,'current'));
 t('3 Temporal mismatch','Old orbital data must not pass as current local condition',e.flags.some(f=>f[0]==='NOT_VALID_AS_LOCAL_CURRENT_CONDITION')&&e.flags.some(f=>f[0]==='OBSERVATION_STALE')&&e.v==='NOT SUPPORTED');
 e=withFP([mk('HiRISE',big,0.25,'2020-01-01'),mk('CTX',big,6,'2015-01-01')],()=>auditSeg(A,Bp,8,0,0.5,'terrain'));
 t('4 Evidence conflict','Different-scale products shown separately, not averaged',e.flags.some(f=>f[0]==='MULTI_SOURCE_SCALE')&&e.srcs.length===2&&e.cls==='Observed');
 const b=withFP([mk('HiRISE',big,0.25,'2020-01-01')],()=>auditSeg(A,Bp,11,0,0.5,'terrain'));
 e=withFP([mk('HiRISE',big,0.25,'2020-01-01')],()=>auditSeg(A,Bp,11,6,0.5,'terrain'));
 t('5 Sensitivity','Adding slope uncertainty flips SUPPORTED to NOT SUPPORTED',b.v==='SUPPORTED'&&e.v==='NOT SUPPORTED');
 const e1=withFP([mk('HiRISE',big,0.25,'2020-01-01')],()=>auditSeg(A,Bp,8,0,0.5,'terrain')),e2=withFP([],()=>auditSeg(A,Bp,8,0,0.5,'terrain'));
 t('6 Traceability','Every recommendation links to a source or states that none exists',e1.srcs.length>0&&e1.srcs.every(x=>x.id)&&e2.srcs.length===0&&e2.flags.some(f=>f[0]==='NO_IMAGE_COVERAGE'));
 const W=40,Hh=40,z=new Float32Array(W*Hh),tn=Math.tan(10*Math.PI/180);for(let y=0;y<Hh;y++)for(let x=0;x<W;x++)z[y*W+x]=(0.5*x/(W-1))*KM*1000*tn;
 const dm=demSlope([{b:{lo0:0,la0:0,lo1:0.5,la1:0.5},w:W,h:Hh,z,res:463,layer:'T'}],[0.1,0.1],[0.4,0.2]);
 t('7 DEM slope','A synthetic 10\u00b0 ramp must be measured as about 10\u00b0',!!dm&&Math.abs(dm.max-10)<0.6);
 e=withFP([mk('THEMIS',big,100,'2010-01-01')],()=>auditSeg(A,Bp,8,0,0.5,'thermal'));const e2b=withFP([],()=>auditSeg(A,Bp,8,0,0.5,'thermal'));
 t('8 Thermal claim','Regional thermal data is caveated; no coverage is unsupported',e.flags.some(f=>f[0]==='THERMAL_REGIONAL_ONLY')&&e.v==='CONDITIONAL'&&e2b.flags.some(f=>f[0]==='NO_THERMAL_COVERAGE')&&e2b.v==='NOT SUPPORTED');
 t('9 Rover-local data','MEDA-style readings far from the rover must be flagged',!medaLocal([5,5],[0,0],[0.01,0.01],1).ok&&medaLocal([0,0],[0,0],[0.001,0.001],1).ok);
 $('tres').innerHTML=R.map(r=>`<div class="card"><span class="tag ${r[2]?'ok':'bad'}">${r[2]?'PASS':'FAIL'}</span> <b>${r[0]}</b><div class="mu">${r[1]}</div></div>`).join('')+`<div class="mu">${R.filter(r=>r[2]).length}/${R.length} passed</div>`}

function brief(){const u=+$('unc').value,sc=+$('obs').value,cl=claim();
 let t=`CAIRN EVIDENCE BRIEF\n${new Date().toISOString().slice(0,10)} | Site: ${SITE}\nPlanning aid only. Not a flight product.\nFootprints: ${LIVE?'LIVE from PDS ODE':'ILLUSTRATIVE PLACEHOLDERS (not real coverage)'}\nClaim type: ${cl} | Layers on: ${Object.keys(on).filter(k=>on[k]).join(', ')||'none'}\nStress: slope +/-${u} deg, obstacle ${sc} m\n\nROUTE\n`;
 if(wp.length<2)t+='(no route)\n';
 wp.slice(1).forEach((_,i)=>{const e=evalSeg(i,u,sc,cl),b=evalSeg(i,0,0.5,cl);
  t+=`- ${L(i).replace('\u2192','->')} ${e.km.toFixed(1)} km | ${e.cls} | slope ${(+e.sl).toFixed(1)} deg (${slopes[i]!=null?'override':e.dm?'DEM '+e.dm.res+' m/px':'assumed'})\n  baseline ${b.v} -> stressed ${e.v}${b.v!==e.v?' [FLIPPED]':''}\n  flags: ${e.flags.map(f=>f[0]).join(', ')}\n  sources: ${e.srcs.slice(0,3).map(srcLine).join('; ')||'none'}\n`});
 t+='\nSCIENCE STOPS\n';if(!stops.length)t+='(none)\n';
 stops.forEach((s,i)=>{const e=evalStop(s);t+=`- S${i+1} (${s[1].toFixed(3)}N, ${s[0].toFixed(3)}E): spectral match ${e.match}; HiRISE ${e.hi?'yes':'none'}; class Inferred (not a sample)\n`});
 t+='\nNEXT USEFUL OBSERVATIONS\n'+(gapList().map((x,i)=>`${i+1}. ${x}`).join('\n')||'(none)')+'\n';
 $('brief').textContent=t}
function copyBrief(){brief();navigator.clipboard.writeText($('brief').textContent).catch(()=>{})}

async function search(){$('res').innerHTML='<div class="mu">Searching&hellip;</div>';
 const d=await (await fetch('/api/images?q='+encodeURIComponent($('q').value))).json();
 if(d.error){$('res').innerHTML=esc(d.error);return}
 $('res').innerHTML=d.map(it=>`<a href="${esc(it.url)}" target="_blank" style="color:inherit;text-decoration:none"><img loading="lazy" src="${esc(it.thumb)}"><div class="mu">${esc(it.title)}</div></a>`).join('')}
search();(function(){let o=null;try{o=JSON.parse(localStorage.getItem('cairn')||'null')}catch(e){}if(o&&apply(o)){render();loadBase();loadFP()}else loadSite('jezero')})();
</script></body></html>
"""

if __name__ == "__main__":
    host = "0.0.0.0" if LAN else "127.0.0.1"
    print("Cairn v3.0 | key:", "custom" if KEY != "DEMO_KEY" else "DEMO_KEY")
    print("Open http://127.0.0.1:%d" % PORT)
    if LAN:
        try:
            t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); t.connect(("8.8.8.8", 80)); ip = t.getsockname()[0]
            print("On your Wi-Fi network, other devices open http://%s:%d" % (ip, PORT))
        except Exception:
            print("LAN mode on: find this device's Wi-Fi IP and open it on port %d" % PORT)
        print("LAN mode: anyone on this network can open Cairn. Use trusted Wi-Fi only.")
    print("Ctrl+C to stop.")
    ThreadingHTTPServer((host, PORT), H).serve_forever()
