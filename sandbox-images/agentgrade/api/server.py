"""
server.py — Sandbox HTTP API Server

Supported languages: python, cpp, java
"""
import os, sys, json, time, logging, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.orchestrator import SandboxOrchestrator, TestCase
from core.executor import ResourceLimits

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sandbox-api")

SUPPORTED = ["python", "cpp", "java"]


class RateLimiter:
    def __init__(self, max_per_minute=15):
        self.max = max_per_minute
        self._counts = {}
        self._lock = threading.Lock()

    def is_allowed(self, ip):
        now = time.time()
        with self._lock:
            timestamps = [t for t in self._counts.get(ip, []) if now - t < 60]
            if len(timestamps) >= self.max:
                self._counts[ip] = timestamps
                return False
            timestamps.append(now)
            self._counts[ip] = timestamps
            return True


rate_limiter = RateLimiter()


class SandboxHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log.info(f"{self.address_string()} - {format % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg, status=400):
        self._send_json({"error": msg, "success": False}, status)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "timestamp": time.time(),
                "supported_languages": SUPPORTED
            })
        elif path == "/api/languages":
            self._send_json({
                "languages": [
                    {"id": "python", "name": "Python 3",       "extension": ".py"},
                    {"id": "cpp",    "name": "C++17 (G++)",    "extension": ".cpp"},
                    {"id": "java",   "name": "Java 21 (JDK)",  "extension": ".java"},
                ]
            })
        else:
            self._send_error("Endpoint not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if not rate_limiter.is_allowed(self.client_address[0]):
            self._send_error("Rate limit exceeded. Please wait 1 minute.", 429)
            return
        if path == "/api/execute":
            self._handle_execute()
        else:
            self._send_error("Endpoint not found", 404)

    def _handle_execute(self):
        try:
            body = self._read_body()
        except Exception as e:
            self._send_error(f"JSON parse error: {e}")
            return

        code     = body.get("code", "").strip()
        language = body.get("language", "").strip().lower()

        if not code:
            self._send_error("'code' field cannot be empty")
            return
        if not language:
            self._send_error(f"'language' field is required ({', '.join(SUPPORTED)})")
            return
        if language not in SUPPORTED:
            self._send_error(f"Unsupported language: {language}. Supported: {SUPPORTED}")
            return
        if len(code) > 100_000:
            self._send_error("Code too large (max 100 KB)")
            return

        lim = body.get("limits", {})
        limits = ResourceLimits(
            cpu_time_sec  = min(int(lim.get("cpu_time_sec",  10)), 30),
            wall_time_sec = min(int(lim.get("wall_time_sec", 15)), 60),
            memory_mb     = min(int(lim.get("memory_mb",    256)), 512),
            disk_mb       = min(int(lim.get("disk_mb",       50)), 100),
            max_processes = min(int(lim.get("max_processes", 32)),  64),
        )

        test_cases = []
        for tc in body.get("test_cases", []):
            try:
                test_cases.append(TestCase(
                    name               = tc.get("name", f"test_{len(test_cases) + 1}"),
                    stdin              = tc.get("stdin"),
                    expected_stdout    = tc.get("expected_stdout"),
                    expected_exit_code = int(tc.get("expected_exit_code", 0)),
                    description        = tc.get("description", ""),
                ))
            except Exception:
                pass

        start = time.perf_counter()
        log.info(f"Execute: lang={language} size={len(code)}b tests={len(test_cases)}")

        try:
            orchestrator = SandboxOrchestrator(limits)
            report = orchestrator.run_submission(
                code=code,
                language=language,
                test_cases=test_cases or None,
                submission_id=body.get("submission_id"),
            )
            elapsed = (time.perf_counter() - start) * 1000
            log.info(f"Done: id={report.submission_id} elapsed={elapsed:.0f}ms")
            self._send_json({
                "success": True,
                "submission_id": report.submission_id,
                "report": report.to_dict(),
                "api_elapsed_ms": round(elapsed, 2)
            })
        except Exception as e:
            log.error(traceback.format_exc())
            self._send_error(f"Internal sandbox error: {e}", 500)


def start_server(host="0.0.0.0", port=8080):
    server = HTTPServer((host, port), SandboxHandler)
    log.info(f"Sandbox API running -> http://{host}:{port}")
    log.info(f"  Supported languages: {SUPPORTED}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped.")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sandbox API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    start_server(args.host, args.port)
