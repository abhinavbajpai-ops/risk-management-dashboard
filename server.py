"""Local dev server: python server.py  ->  http://localhost:3000 (serves index.html + /api/index)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from index import handler
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/"): return handler.do_GET(self)
        return super().do_GET()
    _send = handler._send
ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 3000))), H).serve_forever()
