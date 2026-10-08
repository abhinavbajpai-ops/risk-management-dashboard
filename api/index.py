import sys, os, json, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
from http.server import BaseHTTPRequestHandler
import engine as E, alternates as A, views as V

def route(op, q):
    if op == "snapshot": return V.snapshot(q)
    if op == "focus": return V.focus(q)
    if op == "score":
        ap, sc = V.sc_for(q); return E.calculate_score(q["id"], sc)
    if op == "alternates":
        ap, sc = V.sc_for(q); return A.search(q["id"], E.calculate_score(q["id"], sc)["score"])
    if op == "rfi":
        ap, sc = V.sc_for(q); return {"text": A.rfi(q["id"], E.calculate_score(q["id"], sc)["score"])}
    if op == "reason":
        ap, sc = V.sc_for(q); r = E.calculate_score(q["id"], sc); top = sorted(r["breakdown"], key=lambda b: -(b.get("contribution", b.get("delta", 0))))[:3]
        txt = f"Signal: {E.ENT[q['id']]['short']} scores {r['score']} ({r['band']}), evidence confidence {r['confidence']}. Why: " + "; ".join(f"{b['term']} {b.get('contribution', b.get('delta'))}" for b in top) + f". Revenue on path USD {E.exposure(q['id']):,.0f}m. Action: verify status, start alternate search, confirm unknown fields {r['unknownFields'] or 'none'}."
        return {"provider": "local-deterministic", "text": txt}
    if op == "events": return {"events": V.snapshot(q)["events"]}
    raise KeyError(op)

class handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body if isinstance(body, bytes) else body.encode())
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        op = q.get("op") or u.path.rstrip("/").split("/")[-1]
        try:
            if op == "export": return self._send(200, V.export_html(q), "text/html")
            self._send(200, json.dumps(route(op, q), default=str))
        except KeyError as e: self._send(404, json.dumps({"error": f"not found: {e}"}))
        except Exception as e: self._send(500, json.dumps({"error": repr(e)}))
