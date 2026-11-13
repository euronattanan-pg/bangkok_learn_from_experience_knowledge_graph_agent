import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .config import neo4j_environment
from .model import ManualAdapter
from .neo4j_repo import ConfigurationError, DatabaseOperationError, Neo4jRepository
from .samples import samples
from .schema import FIELDS, QUESTIONS, graph_preview
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def handler_for(store, repository, adapter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, status, data, content_type="application/json; charset=utf-8"):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host", "").lower() in ("localhost:8000", "127.0.0.1:8000", "localhost", "127.0.0.1")

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {"error": "Local access only."})
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                filename, mime = assets[path]
                return self.respond(200, (ROOT / "static" / filename).read_bytes(), mime)
            if path == "/api/schema":
                return self.respond(200, {"fields": FIELDS, "questions": [
                    {"number": number, "label": label, "fields": keys}
                    for number, (label, keys) in enumerate(QUESTIONS, 1)
                ]})
            if path == "/api/samples":
                return self.respond(200, {"samples": samples()})
            if path == "/api/connection":
                status = repository.status()
                status["mock_uploads_allowed"] = store.allow_mock_uploads
                return self.respond(200, status)
            if path == "/api/pending":
                return self.respond(200, {"cases": store.pending()})
            if path == "/api/history":
                return self.respond(200, {"cases": store.history()})
            if path == "/api/pending-upload":
                return self.respond(200, {"cases": store.pending_upload()})
            if path == "/api/audit":
                return self.respond(200, {"events": store.audit()})
            if path.startswith("/api/drafts/") and path.endswith("/graph-preview"):
                case_id = path.removeprefix("/api/drafts/").removesuffix("/graph-preview")
                try:
                    item = store.get(case_id)
                    result = graph_preview(case_id, item["answers"], item["evidence"])
                    result["revision"] = item["revision"]
                    return self.respond(200, result)
                except ValueError as exc:
                    return self.respond(400, {"error": str(exc)})
            if path.startswith("/api/drafts/"):
                try:
                    return self.respond(200, store.get(path.removeprefix("/api/drafts/")))
                except ValueError as exc:
                    return self.respond(404, {"error": str(exc)})
            return self.respond(404, {"error": "Not found."})

        def do_POST(self):
            if not self.valid_host():
                return self.respond(403, {"error": "Local access only."})
            origin = self.headers.get("Origin")
            if origin and origin not in ("http://localhost:8000", "http://127.0.0.1:8000"):
                return self.respond(403, {"error": "Invalid origin."})
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                return self.respond(415, {"error": "JSON required."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1024 * 1024:
                    raise ValueError("Request must be between 1 byte and 1 MiB.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
                path = urlsplit(self.path).path.strip("/").split("/")
                if path == ["api", "drafts"]:
                    transcript = payload.get("transcript")
                    extraction = adapter.extract(transcript)
                    result = {"draft": store.create(transcript, extraction), "notice": extraction["notice"]}
                elif path == ["api", "sample-drafts"]:
                    extraction = {"answers": payload.get("answers"), "evidence": payload.get("evidence")}
                    result = store.create("", extraction, is_sample=True)
                elif len(path) == 4 and path[:2] == ["api", "drafts"]:
                    case_id, action = path[2:]
                    if action not in ("update", "submit", "approve", "save"):
                        return self.respond(404, {"error": "Not found."})
                    try:
                        if action == "update":
                            result = store.update(case_id, payload.get("answers"), payload.get("evidence"), payload.get("revision"))
                        elif action == "submit":
                            result = store.submit(case_id, payload.get("revision"))
                        elif action == "approve":
                            result = store.approve(case_id, payload.get("revision"))
                        else:
                            result = store.save(case_id, payload.get("revision"), repository)
                    except ValueError:
                        store.record_rejection(case_id, action)
                        raise
                elif path == ["api", "qa"]:
                    question = payload.get("question")
                    cases = repository.search(question)
                    result = {"answer": adapter.answer(question, cases), "cases": cases}
                elif path == ["api", "connection", "check"]:
                    result = repository.check_connection()
                else:
                    return self.respond(404, {"error": "Not found."})
                return self.respond(200, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.respond(400, {"error": str(exc)})
            except (ConfigurationError, DatabaseOperationError) as exc:
                return self.respond(503, {"error": str(exc)})
            except Exception:
                # Driver errors can contain connection details; never expose or log them.
                return self.respond(503, {"error": "Operation failed. Check local configuration and database availability."})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Run the local LFE application.")
    parser.add_argument("--env-dev", action="store_true", help="Load Neo4j settings from .env_dev in the current directory.")
    parser.add_argument("--allow-mock-upload", action="store_true",
                        help="Allow approved mock cases to be uploaded to the configured dedicated test database only.")
    args = parser.parse_args()
    try:
        env = neo4j_environment(use_env_dev=args.env_dev)
    except (ValueError, RuntimeError) as exc:
        parser.exit(2, f"{exc}\n")
    data_dir = Path(os.environ.get("LFE_DATA_DIR", "data"))
    store = Store(data_dir / "drafts.sqlite3", allow_mock_uploads=args.allow_mock_upload)
    server = ThreadingHTTPServer((os.environ.get("LFE_LISTEN_HOST", "127.0.0.1"), 8000),
                                 handler_for(store, Neo4jRepository(env), ManualAdapter()))
    server.serve_forever()


if __name__ == "__main__":
    main()
