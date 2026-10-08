"""Alternate-supplier discovery: live DuckDuckGo (optional) + curated seed. Fitment is computed from attributes
(technical 30 / application 25 / footprint 15 / presence 15 / qualification 15); supplier risk is a separate column."""
import json, os, re, datetime
import engine as E
SEED = json.load(open(os.path.join(E.D, "alternates_seed.json")))
tok = lambda s: {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in re.findall(r"[a-z0-9]{3,}", s.lower())} - {"and", "for", "the", "with", "use", "case"}
def profile(n):
    ins = sorted({e["input"] for e in E.SUP if e["frm"] == n and e["input"]}) or [E.ENT[n]["capability"]]
    comps = sorted({c for (c, p) in E.calc_frac(n)})
    app = " ".join(E.COMPONENTS[c]["application"] + " " + re.sub(r"\n?\d\. ", " ", E.COMPONENTS[c]["criteria"]) for c in comps)
    return {"inputs": ins, "components": comps, "applicationText": app,
            "query": f"{' / '.join(ins)} manufacturer {E.COMPONENTS[comps[0]]['application'].split(';')[0] if comps else ''} industrial power electronics"}
def eligible(n, score):
    f = E.FLAGS[n]; return score >= 70 or f["hub"] or f["soleFull"] or f["noAlt"]
def live(query):
    try:
        from duckduckgo_search import DDGS
        with DDGS(timeout=4) as d: return [{"title": r["title"], "url": r["href"], "snippet": r["body"]} for r in d.text(query, max_results=6)], "DDG"
    except Exception as ex: return [], "SEED"
def fit(c, req, app, inc_hazard):
    Wt = E.CFG["fitmentWeights"]; ct = tok(c["tags"]); at = tok(c["applications"])
    rows = {"technical": len(req & ct) / max(1, len(req)), "application": len(app & at) / max(1, min(len(app), 8)),
            "footprint": min(1, c["regions"] / 3), "presence": 0.5 * c["listed"] + 0.5 * len(set(c["endMarkets"]) & {"automotive", "industrial", "energy"}) / 3,
            "qualification": min(1, len(c["certs"]) / 3)}
    rows = {k: round(min(1, v), 2) for k, v in rows.items()}
    return rows, round(sum(Wt[k] * v for k, v in rows.items()), 1)
def search(n, score):
    pr = profile(n); req = set().union(*[tok(i) for i in pr["inputs"]]); app = tok(pr["applicationText"])
    excl = {E.squash(e["short"]) for e in E.ENT.values()}
    hits, prov = live(pr["query"]); out = []
    for c in SEED["candidates"]:
        if E.squash(c["name"].split(" (")[0]) in excl: continue
        rows, f = fit(c, req, app, E.IND.get(n, {}).get("Hazard"))
        if rows["technical"] < 0.34: continue
        risk = "Lower" if c["listed"] and c["regions"] >= 2 else "Medium"
        out.append({"id": c["id"], "name": c["name"], "hq": c["hq"], "fitment": f, "rubric": rows, "url": c["url"], "urlVerified": c["urlVerified"],
            "evidence": [{"text": c["evidence"], "url": c["url"], "accessed": SEED["accessed"], "verified": c["urlVerified"]}],
            "supplierRisk": {"level": risk, "notes": c["riskNotes"] + ["Not scored on case indicators (public sources only)"]}, "source": "SEED"})
    out.sort(key=lambda x: -x["fitment"])
    live_cards = [{"id": "ddg%d" % i, "name": h["title"][:70], "url": h["url"], "snippet": h["snippet"][:200], "source": "DDG", "accessed": SEED["accessed"]} for i, h in enumerate(hits)]
    f = E.FLAGS[n]; lead = E.lead_weeks(n); checks = [f"Match voltage/current class, thermal design and quality systems to the incumbent part ({', '.join(pr['inputs'])})",
        f"Requalification lead time is about {lead} weeks (workbook) - start before disruption",
        f"Confirm alternate site is outside {E.ENT[n]['zone']} (incumbent Physical Hazard {E.IND.get(n, {}).get('Hazard')})"]
    for e in E.CHAIN:
        if e["to"] == n and E.FLAGS[e["frm"]]["noAlt"]: checks.append(f"Confirm the alternate does not rely on {E.ENT[e['frm']]['short']} ({e['site']}) - no independent source currently qualified")
    if E.TIER[n] == 1 and any(E.FLAGS[u["frm"]]["hub"] for u in E.CHAIN if u["to"] == n): checks.append("A different assembler does not remove the shared upstream die/substrate dependency")
    notes = [d["detail"] for d in E.EV.values() if "not a qualified replacement" in d["detail"] and E.ENT[n]["site"] in d["detail"]]
    return {"nodeId": n, "profile": pr, "provider": prov, "mode": "live+seed" if hits else "seed (offline)", "candidates": out[:6], "liveResults": live_cards,
            "validation": checks, "excluded": notes, "weights": E.CFG["fitmentWeights"],
            "note": "Fitment and supplier risk are separate. Proximity is not used: the workbook gives no inter-zone distances."}
def rfi(n, score):
    pr = profile(n); ex = E.exposure(n); e = E.ENT[n]
    return (f"Subject: RFI - alternate source for {', '.join(pr['inputs'])}\n\nWe are assessing qualified second sources for {', '.join(pr['inputs'])} used in {', '.join(sorted({p for (c,p) in E.calc_frac(n)}))} "
            f"(approx. USD {ex:,.0f}m annual revenue on path, {ex/E.TOTAL_REV:.0%} of portfolio). Application: {E.COMPONENTS[pr['components'][0]]['application'] if pr['components'] else 'power electronics'}.\n\n"
            f"Please confirm: capability and capacity for this part class; qualification status (IATF/ISO); manufacturing sites and regions (we require a site outside {e['zone']}); typical qualification lead time (our baseline: {E.lead_weeks(n)} weeks); and any dependency on single-source upstream inputs.\n\nRegards,\nNovaDrive Supply Risk Office")
