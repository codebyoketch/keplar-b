import json
import pytest
import asyncio
from backend.app.cache import cache_path, write_bytes
from backend.app.main import app
from backend.app import data_sources

def api_get(path):
    """Call the ASGI app without adding an HTTP client dependency."""
    scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"GET","scheme":"http",
           "path":path.split("?",1)[0],"raw_path":path.split("?",1)[0].encode(),"query_string":path.partition("?")[2].encode(),
           "root_path":"","headers":[],"client":("test",1234),"server":("test",80)}
    events=[];sent=False
    async def receive():
        nonlocal sent
        if sent:return {"type":"http.request","body":b"","more_body":False}
        sent=True;return {"type":"http.request","body":b"","more_body":False}
    async def send(event):events.append(event)
    asyncio.run(app(scope,receive,send))
    status=next(event["status"] for event in events if event["type"]=="http.response.start")
    body=b"".join(event.get("body",b"") for event in events if event["type"]=="http.response.body")
    return status,body.decode("utf-8")

def test_status_only_discloses_key_class():
    status,body=api_get("/api/status");response=json.loads(body)
    assert status==200 and set(response)=={"key"}
    assert response["key"] in {"custom","DEMO_KEY"}

def test_custom_key_never_appears_in_status_response_or_cache_filename(tmp_path):
    secret="NASA_TEST_SECRET_very_private"
    url="https://api.nasa.gov/planetary/apod?api_key="+secret
    path=cache_path(url,tmp_path)
    assert secret not in str(path)
    assert path.name==cache_path(url.replace(secret,"DEMO_KEY"),tmp_path).name

@pytest.mark.parametrize("endpoint",["/api/status","/api/apod","/api/rover-photos?rover=perseverance&sol=1"])
def test_api_errors_do_not_disclose_key(endpoint,monkeypatch,caplog):
    secret="NASA_TEST_SECRET_very_private"
    monkeypatch.setattr("backend.app.main.NASA_API_KEY",secret)
    monkeypatch.setattr(data_sources,"apod",lambda *a,**k:(_ for _ in ()).throw(RuntimeError("upstream failed with "+secret)))
    monkeypatch.setattr(data_sources,"rover_photos",lambda *a,**k:(_ for _ in ()).throw(RuntimeError("upstream failed with "+secret)))
    status,body=api_get(endpoint)
    assert status in {200,502}
    assert secret not in body
    assert secret not in caplog.text

def test_ode_cache_identity_never_contains_secret(tmp_path):
    secret="NASA_TEST_SECRET_very_private"
    nasa_url=f"https://api.nasa.gov/mars-photos/api/v1/rovers/perseverance/photos?sol=2&api_key={secret}"
    write_bytes(nasa_url,b'{"photos":[]}')
    filename=cache_path(nasa_url,tmp_path).name
    assert secret not in filename and len(filename)==64

def test_illustrative_footprints_are_explicit_when_ode_unavailable(monkeypatch):
    monkeypatch.setattr(data_sources,"_ode",lambda *a:(_ for _ in ()).throw(OSError("offline")))
    result=data_sources.footprints((76.8,17.6,78.4,19.2))
    assert result["live"] is False
    assert len(result["fps"])==4 and all(p["src"]=="ILLUSTRATIVE" for p in result["fps"])
