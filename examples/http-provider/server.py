"""Local reference provider implementing the contract; replace classify with your service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from web_platform_moderation import ModerationRequest, ModerationResult


def classify(request):
    return ModerationResult("review", "Reference provider requests owner review", provider="example-rules", policy_id="example-1")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        if self.path != "/moderate": self.send_error(404); return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 32768 or self.headers.get("Transfer-Encoding"): self.send_error(413); return
            self.connection.settimeout(5)
            request = ModerationRequest.from_dict(json.loads(self.rfile.read(size)))
            body = json.dumps(classify(request).to_dict()).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)
        except (ValueError, TypeError, KeyError): self.send_error(400)


if __name__ == "__main__": ThreadingHTTPServer(("127.0.0.1", 8099), Handler).serve_forever()
