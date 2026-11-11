"""Local rehearsal receiver. Replace with an operator-owned destination before public use."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 65536:
            self.send_error(413)
            return
        payload = json.loads(self.rfile.read(size))
        with Path("/events/alerts.jsonl").open("a") as stream:
            stream.write(json.dumps(payload) + "\n")
        self.send_response(200)
        self.end_headers()


HTTPServer(("0.0.0.0", 8080), Receiver).serve_forever()
