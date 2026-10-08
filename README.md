# NovaDrive Consularium – supply-network risk terminal

Free, no-card deploy on Vercel Hobby: static `index.html` + one Python function `api/index.py` (stdlib only; `duckduckgo-search` optional).

## Run
    python server.py            # http://localhost:3000
    vercel deploy               # Hobby plan, no keys required

## Where everything comes from
- `api/data/workbook.json` – verbatim dump of the case workbook (`python scripts/build_data.py <xlsx>` regenerates it).
- `api/_lib/engine.py` – derives tiers, links, allocations, exposure, scores and event matches from that data by parsing the evidence text. No supplier, score or link is typed in.
- `api/data/config.json` – model method only: weights, bands, rule add-ons (editable).
- `api/data/alternates_seed.json` – offline fallback of public sources for alternate search (re-verify URLs; `urlVerified` marks what was opened).

## Handbook tasks → where
1 Network (confirmed / inferred / hypothesis, evidence per link) · 2 Scorecard (waterfall, confidence kept separate, unknown ≠ safe) · 3 Event feed matching + alerts (dedupe, stale, name collisions) · 4 Alternate search (fitment rubric and supplier risk in separate columns, validation checklist) · 5 Dashboard (focus mode, evidence ledger, quick actions).

## Notes
- Aster = $988.0m and Boreal = $572.0m by the workbook's allocations (the earlier brief's 998.4 / 478.4 do not follow from them).
- Updates arrive by 8s polling; Vercel Hobby functions do not hold SSE streams open. "Replay feed" simulates arrival of the workbook events.
