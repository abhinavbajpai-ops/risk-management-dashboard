import re, datetime
import engine as E, alternates as A
def sc_for(q):
    ap = [x for x in (q.get("apply", "") or "").split(",") if x]; return ap, E.scenario(ap, q.get("outage") or None)
def node_card(n, sc, base):
    r = E.calculate_score(n, sc); e = E.ENT[n]; hyp = all(x["status"] == "hypothesis" for x in E.SUP if x["frm"] == n) and n not in [c["frm"] for c in E.CTRL]
    return {"id": n, "name": e["name"], "short": e["short"], "tier": E.TIER[n], "zone": e["zone"], "site": e["site"], "capability": e["capability"],
        "score": r["score"], "band": r["band"], "base": base[n], "confidence": r["confidence"], "families": r["evidenceFamilies"], "unknown": r["unknownFields"],
        "exposureM": E.exposure(n), "customers": E.CUST[n], "status": "hypothesis" if hyp else ("inferred" if r["confidence"] == "low" and any(x["status"] == "inferred" for x in E.SUP if x["frm"] == n) else "confirmed"),
        "flags": E.FLAGS[n], "unscored": hyp, "eligibleAlternates": A.eligible(n, r["score"]), "ocean": n in E.OCEAN, "kind": "supplier"}
def snapshot(q):
    ap, sc = sc_for(q); b0 = E.scenario(); base = {n: E.calculate_score(n, b0)["score"] for n in E.NET}
    nodes = [node_card(n, sc, base) for n in E.NET]
    for h in [c["frm"] for c in E.CTRL]:
        if h not in E.NET and not any(x["id"] == h for x in nodes):
            e = E.ENT[h]; nodes.append({"id": h, "name": e["name"], "short": e["short"], "tier": 0, "zone": e["zone"], "site": e["site"], "kind": "holding", "score": None, "band": None, "confidence": "high", "exposureM": 0, "customers": [], "status": "confirmed", "unscored": True, "capability": e["capability"], "flags": {}, "unknown": []})
    scored = [x for x in nodes if not x["unscored"]]
    cnt = {k: sum(1 for x in scored if x["band"] == k) for k in ("HIGH", "ELEVATED", "MODERATE", "LOW")}
    events = []
    for ev in E.EVENTS:
        d = dict(ev); d["applied"] = ev["id"] in ap
        if ev["status"] == "active":
            s1 = E.scenario([ev["id"]]); ch = [(n, round(E.calculate_score(n, s1)["score"] - base[n], 1)) for n in E.NET]
            d["impact"] = [{"id": n, "short": E.ENT[n]["short"], "delta": x} for n, x in sorted(ch, key=lambda t: -t[1]) if x > 0][:8]
            d["impactCount"] = sum(1 for _, x in ch if x > 0)
        d["alert"] = alert(ev); events.append(d)
    events.sort(key=lambda x: (["HIGH", "ELEVATED", "MODERATE", "INFO"].index(x["severity"]), -x["revenueOnPathM"]))
    ruled = []
    for i, e in E.ENT.items():
        if i not in E.TIER and not e["external"]:
            ds = E.ledger(i); ruled.append({"id": i, "name": e["name"], "site": e["site"], "reason": (ds[0]["detail"] if ds else e["capability"]), "docs": [d["id"] for d in ds]})
    for e in E.ENT.values():
        if e["note"]: m = re.match(r"(SITE-\d+) - (.+)", e["note"]); ruled.append({"id": m[1], "name": m[2], "site": m[1], "reason": e["note"], "docs": [d["id"] for d in E.EV.values() if m[1] in d["detail"]]})
    for d in E.EV.values():
        if d["status"] == "Expired": ruled.append({"id": d["id"], "name": d["title"], "site": None, "reason": d["detail"], "docs": [d["id"]]})
    edges = [{"from": e["frm"], "to": e["to"], "kind": e["kind"], "status": e["status"], "alloc": e.get("alloc"), "components": e["components"], "input": e["input"], "docs": e["docs"], "families": len({E.EV[x]["family"] for x in e["docs"]})} for e in E.EDGES]
    return {"meta": {"generatedAt": datetime.datetime.utcnow().isoformat() + "Z", "mode": "dataset", "source": "Samanvay_Consularium_NovaDrive_Data workbook", "applied": ap, "outage": q.get("outage") or None},
        "products": list(E.PRODUCTS.values()), "totalRevenueM": E.TOTAL_REV, "components": list(E.COMPONENTS.values()), "nodes": nodes, "edges": edges, "bands": cnt,
        "events": events, "ruledOut": ruled, "weights": E.W, "bandThresholds": E.CFG["bands"],
        "assumptions": ["Allocations are planning shares from disclosures, not purchase ledgers (DOC-001..).", "No supplier spend is provided: an upstream edge is assumed to carry 100% of the downstream node's requirement for that input (conservative); shares add up and cap at 1.", "Missing indicators score a neutral 0.5 plus an 8-point uncertainty penalty - never green, never zero.", "Hypotheses carry no exposure and are not scored.", "Zone distances are not provided in the workbook, so proximity is not used in alternate ranking."]}
def alert(ev):
    nm = lambda ids: ", ".join(E.ENT[i]["short"] for i in ids)
    if ev["status"] == "duplicate": return f"Duplicate of {ev['dupOf']} (same source family {ev['family']}) - no independent evidence, no score change."
    if ev["status"] == "stale": return f"STALE: effective {ev['effective']} but published {ev['published']}. Original dispute ended; no score change."
    if ev["status"] == "not_in_network":
        who = nm(ev["notInNetwork"]) if ev["notInNetwork"] else "an unrelated entity"; col = nm(ev["collisions"])
        return f"NOT IN NETWORK: matches {who}, which has no supply relationship to NovaDrive ({'not ' + col if col else 'identity collision'}). No score change."
    if ev["status"] == "no_impact": return "No production impact: corporate/HQ change only; production site unchanged. Log only."
    sites = ", ".join(E.ENT[i]["site"] for i in ev["nodes"]); sh = ev["revenueOnPathM"] / E.TOTAL_REV
    why = f"{len(ev['nodes'])} node(s) affected, USD {ev['revenueOnPathM']:,.0f}m ({sh:.0%}) of revenue on path, products {', '.join(ev['products'])}."
    act = {"hazard": f"Verify operating status of {sites} within 24h; confirm inventory cover; start alternate search for the highest-scoring affected node.",
           "financial": f"Request covenant and payment-status update from {nm(ev['nodes'])}; review sole-source exposure; open alternate search.",
           "logistics": f"Ask {nm(ev['nodes'])} for in-transit shipments through the affected port; shipment-specific impact is unassessed."}.get(ev["cls"], "Verify.")
    return f"Signal: {ev['title']}. Why it matters: {why} Next: {act}" + (" Confidence note: no damage/impact confirmed." if ev["unconfirmed"] else "")
def focus(q):
    n = q["id"]; ap, sc = sc_for(q)
    if n not in E.NET: raise KeyError(n)
    r = E.calculate_score(n, sc); e = E.ENT[n]; docs = E.ledger(n)
    up = [x for x in E.SUP if x["to"] == n]; dn = [x for x in E.SUP if x["frm"] == n]
    path = {"downstream": sorted(E.downstream(n, chain=False)), "products": sorted(E.PROD_FRAC.get(n, {})), "upstream": []}
    st = [n]; seen = set()
    while st:
        x = st.pop()
        for y in E.SUP:
            if y["to"] == x and y["frm"] not in seen: seen.add(y["frm"]); st.append(y["frm"])
    path["upstream"] = sorted(seen)
    fam = {}
    for d in docs: fam.setdefault(d["family"], []).append(d["id"])
    ledger = [{**d, "dupNote": (f"same source family as {', '.join(x for x in fam[d['family']] if x != d['id'])}" if len(fam[d['family']]) > 1 else None)} for d in docs]
    return {"node": node_card(n, sc, {n: r["score"]}), "entity": e, "score": r, "indicators": E.IND.get(n, {}), "exposure": {"revenueAtRiskM": E.exposure(n), "totalM": E.TOTAL_REV,
        "share": round(E.exposure(n) / E.TOTAL_REV, 3), "walk": E.exposure_walk(n), "formula": "revenueAtRisk(n) = Σ_p productRevenue(p) × share(n carries the component for p); share = allocation (Tier-1) or Σ downstream shares capped at 1"},
        "suppliesTo": [{"to": x["to"], "components": x["components"], "alloc": x["alloc"], "status": x["status"], "input": x["input"], "docs": x["docs"]} for x in dn],
        "suppliedBy": [{"from": x["frm"], "input": x["input"], "status": x["status"], "docs": x["docs"]} for x in up],
        "controlledBy": E.CONTROLLER.get(n), "path": path, "ledger": ledger, "leadWeeks": E.lead_weeks(n),
        "events": [{"id": ev["id"], "title": ev["title"], "status": ev["status"]} for ev in E.EVENTS if n in ev["nodes"]]}
def export_html(q):
    f = focus(q); s = f["score"]; rows = "".join(f"<tr><td>{b['term']}</td><td>{b.get('contribution', b.get('delta'))}</td><td>{b.get('reason','')}</td></tr>" for b in s["breakdown"])
    ev = "".join(f"<li><b>{d['id']}</b> ({d['date']}, {d['family']}, {d['status']}): {d['detail']}</li>" for d in f["ledger"])
    return f"<!doctype html><meta charset=utf-8><title>Dossier {f['entity']['name']}</title><style>body{{font:14px Inter,sans-serif;max-width:900px;margin:30px auto;color:#111}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}table{{border-collapse:collapse}}</style><h1>{f['entity']['name']} ({q['id']})</h1><p>Score <b>{s['score']}</b> [{s['band']}] · confidence {s['confidence']} ({s['evidenceFamilies']} source families) · revenue at risk USD {f['exposure']['revenueAtRiskM']}m ({f['exposure']['share']:.0%})</p><h2>Score breakdown</h2><table><tr><th>Term</th><th>Points</th><th>Reason</th></tr>{rows}</table><h2>Evidence</h2><ul>{ev}</ul><h2>RFI draft</h2><pre>{A.rfi(q['id'], s['score'])}</pre>"
