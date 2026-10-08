"""NovaDrive engine: network reconstruction, scoring, event matching. Everything is derived from
api/data/workbook.json (verbatim case workbook) + api/data/config.json (model weights/rules)."""
import json, os, re, datetime
D = os.path.join(os.path.dirname(__file__), "..", "data")
WB = json.load(open(os.path.join(D, "workbook.json")))
CFG = json.load(open(os.path.join(D, "config.json")))
W, R = CFG["weights"], CFG["rules"]
clamp = lambda x, lo=0.0, hi=1.0: max(lo, min(hi, x))
def norm(v, good, bad): return clamp((v - good) / (bad - good))
stem = lambda n: re.sub(r"\s+(ltd|inc|llc)\.?$", "", n.strip(), flags=re.I)
squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())

# ---------- business + components ----------
PRODUCTS = {p["Product ID"]: {"id": p["Product ID"], "name": p["Product Name"], "revenueM": p["Annual Revenue (USD m)"],
            "units": p["Weekly Units"], "footprint": p["Primary Manufacturing Footprint"]} for p in WB["Business Context"]}
TOTAL_REV = sum(p["revenueM"] for p in PRODUCTS.values())
COMPONENTS = {}
for c in WB["Components Context"]:
    crit = c["Key Criteria for Alternate Supplier Search"]
    m = re.search(r"Products Using This Component:\s*([^\n]+)", crit)
    COMPONENTS[c["Component ID"]] = {"id": c["Component ID"], "name": c["Component Name"], "application": c["Key application"],
        "leadWeeks": c["Indicative supplier Qualification Lead Time (Weeks)"], "criteria": crit,
        "products": [x.strip() for x in m.group(1).split(",")] if m else []}

# ---------- entities ----------
ENT = {}
for e in WB["Supplier Universe"]:
    ENT[e["Entity ID"]] = {"id": e["Entity ID"], "name": e["Legal Name"], "short": stem(e["Legal Name"]), "type": e["Entity Type"],
        "capability": e["Public Capability"], "market": e["Registered Market"], "zone": e["Facility Zone"], "site": e["Primary Facility ID"],
        "siteName": e["Primary Facility Name"], "siteRole": e["Facility Role"], "note": e["Other Known Site / Note"], "external": False}
BY_STEM = {squash(e["short"]): e["id"] for e in ENT.values()}
IND = {}
for r in WB["Supplier business Indicators"]:
    IND[r["Entity ID"]] = {"CurrentRatio": r["Current Ratio"], "NetDebtToEBITDA": r["Net Debt / EBITDA"],
        "Timeliness3M": r["Shipment Timeliness - 3M Avg (%)"], "TimelinessChangePP": r["Timeliness Change - Jan To Latest (pp)"],
        "AssuranceGap": r["Assurance Gap Index"], "Hazard": r["Physical Hazard Index"],
        "LogisticsFriction": r["Logistics Friction Index"], "Infrastructure": r["Infrastructure Index"]}
EV = {e["Evidence ID"]: {"id": e["Evidence ID"], "date": e["Evidence Date"], "type": e["Evidence Type"], "family": e["Source Family ID"],
      "title": e["Title / Parties"], "detail": e["Evidence Detail"], "status": e["Record Status"], "locator": e["Source Locator"]}
      for e in WB["Relationship Evidence"]}

def ents_in(text):
    t = squash(text); return [i for s, i in BY_STEM.items() if s in t]

# ---------- relationship extraction (regex over evidence text) ----------
P_T1 = re.compile(r"^(?P<s>.+?) has been named a production supplier to NovaDrive Technologies for component (?P<c>\w+), used in (?P<p>[P\d, ]+)\. Production takes place at (?P<site>SITE-\d+)\..*?approximately (?P<a>\d+)%")
P_UP = re.compile(r"^(?P<c>.+?) identifies (?P<s>.+?) as an active production input supplier for its (?P<g>[\w/]+) programs\. The supplied input is (?P<i>.+?), manufactured at (?P<site>SITE-\d+)")
EDGES, OUTSIDE = [], []   # OUTSIDE = ruled-out / not-in-network findings
def add_edge(**k): EDGES.append(k)
nm = lambda n: BY_STEM.get(squash(stem(n)))
for d in EV.values():
    t = d["detail"]; m1 = P_T1.match(t); m2 = P_UP.match(t)
    if m1:
        s = nm(m1["s"]); add_edge(kind="supply", frm=s, to="NOVADRIVE", status="confirmed", components=[m1["c"]],
            products=[x.strip() for x in m1["p"].split(",")], alloc=int(m1["a"]) / 100, input=COMPONENTS[m1["c"]]["name"], site=m1["site"], docs=[d["id"]])
    elif m2:
        s, c = nm(m2["s"]), nm(m2["c"]); add_edge(kind="supply", frm=s, to=c, status="confirmed", components=m2["g"].split("/"),
            alloc=None, input=m2["i"], site=m2["site"], docs=[d["id"]])
    elif "consolidates" in t or "accounting parent" in t:
        ids = re.findall(r"ORG-\d+", t)
        kids = [ids[1]] if "accounting parent" in t else [i for i in ents_in(t) if i != ids[0]]
        for k in kids: add_edge(kind="control", frm=ids[0], to=k, status="confirmed", components=[], docs=[d["id"]], input="ownership")
    elif d["status"] == "Current disclosure" and re.search(r"candidate link|research lead only|sample evaluation", t):
        a, _, b = d["title"].partition(" / ")
        sup = nm(a.split(" program")[0]) or nm(a)
        if not sup and " / " in d["title"]:   # supplier outside the universe (e.g. Alder Bauxite)
            nmx = a.strip(); sup = "EXT-" + squash(nmx)[:8].upper()
            ENT[sup] = {"id": sup, "name": nmx + " Ltd.", "short": nmx, "type": "Unverified (not in universe)", "capability": "trade-directory mention only",
                "market": None, "zone": None, "site": None, "siteName": None, "siteRole": None, "note": None, "external": True}
        cust = nm(b.split(" program")[0]) if b else None
        if not sup:   # title has no "A / B": first entity named in title is supplier, other named in detail is customer
            named = sorted(set(ents_in(d["detail"])), key=lambda i: squash(d["detail"]).find(squash(ENT[i]["short"]))); sup = named[0] if named else None
        if not cust: cust = next((i for i in ents_in(t) if i != sup), None)
        if sup and cust:
            inferred = "candidate link" in t
            comp = re.findall(r"\bM\d0|C\d0|H\d0|B\d0", t); sup_in = re.search(r"([\w ]+?)(?: Ltd\.)? lists", t)
            add_edge(kind="supply", frm=sup, to=cust, status="inferred" if inferred else "hypothesis", components=sorted(set(comp)) or None,
                alloc=None, input=ENT[sup]["capability"], site=ENT[sup]["site"], docs=[d["id"]])
# resolve missing component scope on inferred/hypothesis edges from customer's own edges
def comps_of(n): return sorted({c for e in EDGES if e["frm"] == n and e["status"] == "confirmed" for c in (e["components"] or [])})
for e in EDGES:
    if e["components"] is None: e["components"] = comps_of(e["to"]) if e["to"] != "NOVADRIVE" else []
# merge duplicate (frm,to,status) edges: more records != more independent evidence
merged = {}
for e in EDGES:
    k = (e["kind"], e["frm"], e["to"], e["status"], e["input"] if e["to"] != "NOVADRIVE" else tuple(e["components"]))
    if k in merged: merged[k]["docs"] += e["docs"]
    else: merged[k] = e
EDGES = list(merged.values())
# attach shipment observations to tier-1 suppliers
SHIP = [d for d in EV.values() if d["type"] == "Shipment observation"]
OCEAN = set()
for d in SHIP:
    m = re.search(r"shipper '([^']+)' to consignee '([^']+)'.*mode (\w+)", d["detail"])
    if m and "NOVADRIVE" in m[2].upper():
        i = nm(m[1].title().replace("Llc", "")) or next(iter(ents_in(m[1])), None)
        if i and m[3] == "Ocean":
            OCEAN.add(i)
        for e in EDGES:
            if e["to"] == "NOVADRIVE" and e["frm"] == i: e["docs"].append(d["id"])

SUP = [e for e in EDGES if e["kind"] == "supply"]
CTRL = [e for e in EDGES if e["kind"] == "control"]
CHAIN = [e for e in SUP if e["status"] != "hypothesis"]          # edges that carry exposure
# ---------- tiers (BFS from NovaDrive over supply edges) ----------
TIER = {}
for e in SUP:
    if e["to"] == "NOVADRIVE": TIER[e["frm"]] = 1
ch = True
while ch:
    ch = False
    for e in SUP:
        if e["to"] in TIER and e["frm"] not in TIER or (e["to"] in TIER and TIER[e["frm"]] < TIER[e["to"]] + 1 and e["frm"] not in TIER):
            TIER[e["frm"]] = TIER[e["to"]] + 1; ch = True
NET = {i: ENT[i] for i in TIER}
for e in CTRL: TIER.setdefault(e["frm"], 0)   # holdings: control layer, not supply tier
CUST = {i: [e["to"] for e in SUP if e["frm"] == i and e["to"] != "NOVADRIVE"] for i in ENT}
CUSTC = {i: [e["to"] for e in CHAIN if e["frm"] == i and e["to"] != "NOVADRIVE"] for i in ENT}
def downstream(n, chain=True):
    seen, st = set(), [n]
    while st:
        x = st.pop()
        for c in (CUSTC if chain else CUST)[x]:
            if c not in seen: seen.add(c); st.append(c)
    return seen
CONTROLLER = {e["to"]: e["frm"] for e in CTRL}

# ---------- evidence ledger per entity ----------
def ledger(n):
    e = ENT[n]; out = []
    for d in EV.values():
        t = d["title"] + " " + d["detail"]
        if e["id"] in t or (e["site"] and e["site"] in t) or squash(e["short"]) in squash(t): out.append(d)
    return out
def fam_count(docs, only_ok=True):
    return len({d["family"] for d in docs if not only_ok or d["status"] != "Expired"})

# ---------- revenue exposure: per (component, product) share propagated upstream ----------
FRAC = {}   # node -> {(component, product): share of that requirement carried by node}
for e in CHAIN:
    if e["to"] == "NOVADRIVE":
        for p in e["products"]: FRAC.setdefault(e["frm"], {})[(e["components"][0], p)] = e["alloc"]
for _ in range(6):
    for e in CHAIN:
        if e["to"] == "NOVADRIVE" or e["to"] not in FRAC: continue
        for (c, p), f in list(FRAC[e["to"]].items()):
            if c in e["components"]:
                cur = FRAC.setdefault(e["frm"], {}); cur[(c, p)] = max(cur.get((c, p), 0), 0)
# parallel customers add up (capped at 1) on the same (component, product); weight of an upstream edge is 1 (stated assumption: no spend data)
for n in list(FRAC):
    if TIER.get(n) != 1: del FRAC[n]
def calc_frac(n, memo={}):
    if n in memo: return memo[n]
    if TIER.get(n) == 1: memo[n] = FRAC.get(n, {}); return memo[n]
    acc = {}
    for e in CHAIN:
        if e["frm"] == n and e["to"] != "NOVADRIVE":
            for (c, p), f in calc_frac(e["to"]).items():
                if c in e["components"]: acc[(c, p)] = clamp(acc.get((c, p), 0) + f)
    memo[n] = acc; return acc
PROD_FRAC = {}
for n in ENT:
    pf = {}
    for (c, p), f in calc_frac(n).items(): pf[p] = max(pf.get(p, 0), f)
    PROD_FRAC[n] = pf
def exposure(n): return round(sum(PRODUCTS[p]["revenueM"] * f for p, f in PROD_FRAC.get(n, {}).items()), 1)
def exposure_walk(n):
    rows = []
    for (c, p), f in sorted(calc_frac(n).items()):
        rows.append({"component": c, "product": p, "productRevenueM": PRODUCTS[p]["revenueM"], "share": round(f, 3), "revenueM": round(PRODUCTS[p]["revenueM"] * f, 1)})
    return rows

# ---------- structural flags ----------
def flags(n):
    fl = {"hub": False, "sole": False, "soleFull": False, "noAlt": False, "common": False}
    t1_cust = {c for c in CUSTC[n] if TIER.get(c) == 1}
    fl["hub"] = len(CUSTC[n]) >= 2 and len({c for c in CUSTC[n]}) >= 2
    peers = [e for e in CHAIN if e["to"] != "NOVADRIVE" and e["input"] == next((x["input"] for x in CHAIN if x["frm"] == n and x["to"] != "NOVADRIVE"), None) and e["frm"] != n and e["to"] in CUSTC[n]]
    fl["sole"] = not peers
    if TIER.get(n) == 1:
        a = [e["alloc"] for e in CHAIN if e["frm"] == n and e["to"] == "NOVADRIVE"]
        fl["soleFull"] = any(x == 1.0 for x in a)
    docs = ledger(n)
    fl["noAlt"] = any(re.search(r"no second .{0,30}source is currently qualified|no presently qualified independent", d["detail"], re.I) for d in docs)
    if n in CONTROLLER:
        sib = [k for k, v in CONTROLLER.items() if v == CONTROLLER[n] and k != n]
        fl["common"] = bool(sib)
    return fl
FLAGS = {n: flags(n) for n in NET}
def independent_alts(n):
    """Peers supplying the same component at same tier with no shared upstream hub and no common controller."""
    if TIER[n] != 1: return 0
    comps = set(c for e in CHAIN if e["frm"] == n and e["to"] == "NOVADRIVE" for c in e["components"])
    cnt = 0
    for o in NET:
        if o == n or TIER[o] != 1: continue
        oc = set(c for e in CHAIN if e["frm"] == o and e["to"] == "NOVADRIVE" for c in e["components"])
        if not (oc & comps): continue
        up_n = {e["frm"] for e in CHAIN if e["to"] == n}; up_o = {e["frm"] for e in CHAIN if e["to"] == o}
        if (up_n & up_o) or (CONTROLLER.get(n) and CONTROLLER.get(n) == CONTROLLER.get(o)): continue
        cnt += 1
    return cnt
def lead_weeks(n):
    cs = {c for (c, p) in calc_frac(n)}; return max([COMPONENTS[c]["leadWeeks"] for c in cs] or [R["maxLeadWeeks"]])
def conf(n):
    own = [e for e in SUP if e["frm"] == n]
    if own and all(e["status"] == "hypothesis" for e in own): return "hypothesis", 0
    docs = [d for d in ledger(n) if d["status"] != "Expired"]; k = fam_count(docs)
    st = "inferred" if own and all(e["status"] != "confirmed" for e in own) else "confirmed"
    lv = "low" if st == "inferred" else ("high" if k >= 3 else "medium" if k == 2 else "low")
    return lv, k

# ---------- events: classification + matching ----------
def parse_days(a, b):
    f = lambda s: datetime.date.fromisoformat(s); return (f(a) - f(b)).days
EVENTS = []
seen_fam = {}
for e in sorted(WB["Risk Event Flags"], key=lambda x: x["Event ID"]):
    txt = e["Title"] + ". " + e["Event Detail"]; low = txt.lower()
    cls = next((k for k, ws in CFG["eventClasses"].items() if any(w in low for w in ws)), "other")
    zones = re.findall(r"\bZ\d\d\b", txt)
    hits = []
    for s, i in BY_STEM.items():
        for m in re.finditer(re.escape(s), squash(txt)): hits.append(i)
    # negation: "not X" / "unrelated" mentions are collisions, not matches
    neg = set()
    for i in set(hits):
        nmn = ENT[i]["short"]; 
        if re.search(r"\bnot\s+(?:the\s+)?" + re.escape(nmn), txt, re.I) or re.search(r"\bnot\s+" + re.escape(nmn.split()[0]) , txt, re.I) and nmn.split()[0].lower() in low and False: neg.add(i)
    for i in list(set(hits)):
        if i in neg: continue
    alias = []
    if not hits and not zones:   # alias on first word only (never a place name like "East Delta")
        for w in re.findall(r"(?<!East )(?<!Harbor )\b[A-Z][a-z]+\b", e["Title"] + " " + e["Event Detail"]):
            c = [i for i in NET if ENT[i]["short"].split()[0] == w]
            if c: alias += c
    pos = [i for i in dict.fromkeys(hits) if i not in neg]
    # a holding/HQ-only entity or a trading/logistics entity never carries production exposure
    inn = [i for i in pos if i in NET]; out = [i for i in pos if i not in NET]
    alias = [i for i in dict.fromkeys(alias) if i in NET]
    ev = {"id": e["Event ID"], "title": e["Title"], "detail": e["Event Detail"], "published": e["Published At"], "effective": e["Effective At"],
          "family": e["Source Family ID"], "cls": cls, "zones": zones, "matchedEntities": inn or alias, "notInNetwork": out, "collisions": sorted(neg),
          "ambiguous": len(alias) > 1 and not inn}
    # status
    lag = parse_days(e["Published At"], e["Effective At"])
    dup_of = seen_fam.get(e["Source Family ID"])
    if dup_of: ev["status"] = "duplicate"; ev["dupOf"] = dup_of
    elif lag > CFG["staleDays"]: ev["status"] = "stale"
    elif out and not inn: ev["status"] = "not_in_network"
    elif cls == "corporate": ev["status"] = "no_impact"
    elif cls == "identity" and not inn: ev["status"] = "not_in_network"
    else: ev["status"] = "active"
    if not dup_of: seen_fam[e["Source Family ID"]] = e["Event ID"]
    # affected nodes
    nodes = []
    if ev["status"] == "active":
        if cls == "hazard": nodes = [i for i in NET if ENT[i]["zone"] in zones and ENT[i]["siteRole"] == "Manufacturing" and TIER[i] > 0]
        elif cls == "financial": nodes = inn
        elif cls == "logistics": nodes = sorted(OCEAN)
    ev["nodes"] = nodes
    EVENTS.append(ev)
for ev in EVENTS:
    dups = [x for x in EVENTS if x["family"] == ev["family"]]
    ev["dupes"] = len(dups); ev["dupIds"] = [x["id"] for x in dups]
    # revenue on path
    pf = {}
    for n in ev["nodes"]:
        for p, f in PROD_FRAC.get(n, {}).items(): pf[p] = max(pf.get(p, 0), f)
    ev["revenueOnPathM"] = round(sum(PRODUCTS[p]["revenueM"] * f for p, f in pf.items()), 1)
    ev["products"] = sorted(pf)
    share = ev["revenueOnPathM"] / TOTAL_REV
    unconf = bool(re.search(r"\bno\b[^.]*\b(confirmed|assessed)", ev["detail"], re.I))
    sev = "HIGH" if share >= .5 else "ELEVATED" if share >= .25 else "MODERATE" if share > 0 else "INFO"
    if unconf and sev == "HIGH": sev = "ELEVATED"
    if ev["cls"] == "logistics" and sev in ("HIGH",): sev = "ELEVATED"
    ev["severity"] = sev if ev["status"] == "active" else "INFO"
    ev["unconfirmed"] = unconf

# ---------- scenario effects ----------
def scenario(apply=(), outage=None):
    add, fric, floors = {}, {}, {}
    def put(n, term, delta, reason, ev=None): add.setdefault(n, []).append({"term": term, "delta": delta, "reason": reason, "eventId": ev})
    def prop(src, amt, label, ev):
        for c in downstream(src):
            if c not in src_set: put(c, "propagation:" + label, amt, f"downstream of {ENT[src]['short']} via {label}", ev)
    for ev in EVENTS:
        if ev["id"] not in apply or ev["status"] != "active": continue
        src_set = set(ev["nodes"])
        if ev["cls"] == "hazard":
            for n in ev["nodes"]: put(n, "addOn:event:" + ev["id"], R["hazardEventAddon"], f"{ev['title']} in {','.join(ev['zones'])}", ev["id"])
            for n in ev["nodes"]: prop(n, R["hazardPropagation"], ev["id"], ev["id"])
        elif ev["cls"] == "financial":
            for n in ev["nodes"]:
                put(n, "addOn:event:" + ev["id"], R["financialAddon"], ev["title"], ev["id"])
                if FLAGS[n]["soleFull"] or FLAGS[n]["noAlt"] or FLAGS[n]["sole"] and TIER[n] > 1: floors[n] = (R["financialSoleFloor"], ev["id"])
                for c in CUSTC[n]: put(c, "propagation:" + ev["id"], R["financialPropagation"], f"customer of distressed {ENT[n]['short']}", ev["id"])
        elif ev["cls"] == "logistics":
            for n in ev["nodes"]: fric[n] = fric.get(n, 0) + R["logisticsFrictionPoints"]
    if outage in NET:
        src_set = {outage}
        put(outage, "addOn:outage", R["outageAddon"], f"simulated facility outage at {ENT[outage]['site']}", "SIM")
        floors[outage] = (R["outageFloor"], "SIM"); prop(outage, R["outagePropagation"], "outage", "SIM")
    return {"add": add, "fric": fric, "floors": floors}

# ---------- scoring (takes NO tier argument) ----------
def band(s): return "HIGH" if s >= CFG["bands"]["HIGH"] else "ELEVATED" if s >= CFG["bands"]["ELEVATED"] else "MODERATE" if s >= CFG["bands"]["MODERATE"] else "LOW"
def calculate_score(node_id, sc=None):
    sc = sc or scenario(); ind = dict(IND.get(node_id, {})); fl = FLAGS[node_id]; S = CFG["scales"]; U = CFG["unknown"]
    unknown = [k for k, v in ind.items() if v is None]
    if node_id in sc["fric"] and ind.get("LogisticsFriction") is not None: ind["LogisticsFriction"] = min(100, ind["LogisticsFriction"] + sc["fric"][node_id])
    u = lambda v, f: U["neutral"] if v is None else f(v)
    ex = exposure(node_id)
    fin = (u(ind.get("CurrentRatio"), lambda v: norm(v, *S["currentRatio"])) + u(ind.get("NetDebtToEBITDA"), lambda v: norm(v, *S["netDebtEbitda"]))) / 2
    ops = (u(ind.get("Timeliness3M"), lambda v: norm(v, *S["timeliness"])) + u(ind.get("TimelinessChangePP"), lambda v: norm(v, *S["timelinessChangePP"]))) / 2
    geo = u(ind.get("Hazard"), lambda v: v / 100)
    conc = clamp((0.4 if fl["soleFull"] else 0.25 if fl["sole"] else 0) + (0.3 if fl["hub"] else 0) + (0.15 if fl["common"] else 0) + (0.3 if fl["noAlt"] else 0))
    alts = independent_alts(node_id) if TIER[node_id] == 1 else (0 if fl["noAlt"] else 0)
    sub = clamp(lead_weeks(node_id) / R["maxLeadWeeks"]) * (1 / (1 + alts))
    if TIER[node_id] > 1 and not fl["noAlt"]: sub *= 0.6   # upstream alternates unknown (not documented as none): partial credit, stated assumption
    t1 = {c for c in downstream(node_id) if TIER.get(c) == 1} | ({node_id} if TIER[node_id] == 1 else set())
    net = 0.5 * clamp(len(t1) / 4) + 0.5 * (ex / TOTAL_REV)
    asr = (sum(u(ind.get(k), lambda v: v / 100) for k in ("AssuranceGap", "LogisticsFriction", "Infrastructure"))) / 3
    raw = {"revenue": ex / TOTAL_REV, "financial": fin, "operational": ops, "geographic": geo, "concentration": conc, "substitutability": sub, "network": net, "assurance": asr}
    inputs = {"revenue": {"revenueAtRiskM": ex, "totalM": TOTAL_REV}, "financial": {k: ind.get(k) for k in ("CurrentRatio", "NetDebtToEBITDA")},
              "operational": {k: ind.get(k) for k in ("Timeliness3M", "TimelinessChangePP")}, "geographic": {"Hazard": ind.get("Hazard")},
              "concentration": {"soleInNetwork": fl["sole"], "soleFullAllocation": fl["soleFull"], "sharedHub": fl["hub"], "commonControl": fl["common"], "documentedNoAlternate": fl["noAlt"]},
              "substitutability": {"leadWeeks": lead_weeks(node_id), "independentAlternatesInNetwork": alts},
              "network": {"downstreamTier1Nodes": len(t1), "revenueShare": round(ex / TOTAL_REV, 3)},
              "assurance": {k: ind.get(k) for k in ("AssuranceGap", "LogisticsFriction", "Infrastructure")}}
    br = [{"term": k, "weight": W[k], "raw": round(raw[k], 3), "contribution": round(100 * W[k] * raw[k], 1), "inputs": inputs[k]} for k in W]
    if fl["hub"]: br.append({"term": "addOn:shared_hub", "delta": R["sharedHubAddon"], "reason": f"feeds {len(CUSTC[node_id])} downstream nodes (shared dependency)"})
    for a in sc["add"].get(node_id, []): br.append(dict(a))
    if node_id in sc["fric"]: br.append({"term": "input:logistics_friction", "delta": 0.0, "reason": f"+{sc['fric'][node_id]} LogisticsFriction pts (port congestion, shipment impact unassessed)", "eventId": "EV-010"})
    if unknown: br.append({"term": "penalty:unknown", "delta": U["penalty"], "reason": "missing: " + ", ".join(unknown) + " (treated as neutral 0.5, never green)"})
    total = sum(b.get("contribution", b.get("delta", 0)) for b in br)
    floor = None
    if fl["soleFull"] or fl["noAlt"]: floor = (R["soleSourceFloor"], "sole source / no qualified alternate")
    if node_id in sc["floors"]: fv, fe = sc["floors"][node_id]; floor = max(floor or (0, ""), (fv, fe)) if not floor else ((fv, fe) if fv > floor[0] else floor)
    if floor and total < floor[0]: br.append({"term": "floor", "delta": round(floor[0] - total, 1), "reason": f"floor {floor[0]} ({floor[1]})"}); total = floor[0]
    score = round(min(100.0, max(0.0, total)), 1)
    cl, k = conf(node_id)
    return {"nodeId": node_id, "score": score, "band": band(score), "confidence": cl, "evidenceFamilies": k, "unknownFields": unknown,
            "breakdown": br, "tier": TIER[node_id], "tierNote": "Tier is metadata; score is effect-based (scorer takes no tier argument)."}
