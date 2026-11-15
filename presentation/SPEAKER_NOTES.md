# Cairn Project Introduction — Speaker Notes

Seven slides total. Approximate delivery time: 5–6 minutes.

## 1. Title — Cairn: Plan the traverse

**Say:** “Cairn is a Marswalk planning prototype. Its goal is to make the basis and uncertainty behind a proposed route easier to inspect.”

**Show:** The title and route illustration. Keep the opening short; introduce the problem on slide 2.

## 2. Introduction — A route line alone is not a mission plan

**Say:** “A map can show where a crew might travel, but it does not answer whether terrain is steep, whether images cover the route at a useful scale, or whether modeled supplies are sufficient for the return. Cairn puts those questions in one workflow. It helps a team inspect the evidence and assumptions behind a route.”

**Emphasize:** Cairn is advisory software. It is not flight-certified and does not receive live surface or crew telemetry.

## 3. Route workflow — From map clicks to a terrain-aware path

**Say:** “The user selects Jezero or Gale, names a target, and clicks at least two waypoints. The backend gets an elevation model, turns it into a grid, and derives slope from neighboring elevation samples. A* searches neighboring grid cells, blocks cells over the configured slope limit, and makes steeper steps more expensive. It can also produce an alternate path.”

**Show:** Point to the four workflow steps, then the route rule. If the app is open, briefly place two map points.

## 4. Evidence audit — Three reviews for every route

**Say:** “Cairn checks Terrain, Current conditions, and Thermal context. It samples each route segment against orbital image footprints and checks coverage, pixel scale, observation age, and source type. Supported, Check, and Fragile describe the evidence for a segment. They are not the mission-level GO or NO-GO result.”

**Emphasize:** An image footprint does not prove obstacle-scale detail. Orbital observations are not current local conditions, and THEMIS provides regional thermal context.

## 5. Mission check — Test the route and model the return

**Say:** “The team can stress-test an unseen obstacle or add slope error to coarse terrain. Cairn then estimates best and worst resource use from route distance, slope, walking and stop time, load, and crew assumptions. The turn-back clock identifies the latest modeled checkpoint that preserves the configured reserves.”

**Emphasize:** The values are unvalidated assumptions. A stress scenario explores a possibility; it does not claim an obstacle is present.

## 6. Product and architecture — One planner, three ways to use the result

**Say:** “Plan is where the crew draws a route and reviews its map and evidence. Field visor turns a selected segment into text directions, with optional browser speech. Mission brief gathers the result into a printable page. Technically, a React frontend calls a same-origin FastAPI backend. The backend connects to USGS map and elevation services and the ODE footprint service, then runs the route, evidence, stress, and resource logic.”

**Emphasize:** A NASA key is optional for the core map and route workflow; it is used for NASA APOD and rover-photo features. Route state is held in backend memory, so a restart requires recalculating.

## 7. Limits and next steps — Useful because uncertainty is visible

**Say:** “Cairn does not replace mission procedures or human review. Its resource assumptions need validation, its orbital imagery cannot establish current local conditions, and placeholder footprints must never be presented as observations. The next steps are to validate assumptions with mission specialists, add more current and local data, and review every route against mission procedures.”

**Close:** “The live demo is at cairn-xfny.onrender.com.”
