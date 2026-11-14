"""Pre-fetch the Jezero demo area so the app can be demonstrated offline."""
import json
from pathlib import Path
from app.data_sources import cache_demo_area, get_dem

if __name__ == "__main__":
    results=cache_demo_area()
    cache_dir=Path(__file__).resolve().parent/"cache"
    output=cache_dir/"prep_manifest.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    dem_extents=[]
    for item in results:
        try:dem_extents.append(get_dem(tuple(item["bbox"])))
        except Exception:continue
    if dem_extents:
        (cache_dir/"demo_dem_extents.json").write_text(json.dumps(dem_extents),encoding="utf-8")
    print(f"Prepared {len(results)} extents; manifest: {output}")
    if dem_extents:print(f"Saved {len(dem_extents)} reusable DEM extents for offline route planning.")
