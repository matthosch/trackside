"""HTTP front end: POST /alerts (Alertmanager webhook), GET /healthz, GET /metrics.

Alertmanager waits at most 10 seconds for an answer, and an investigation takes
longer, so notifications are queued and handled one at a time by a worker thread.
"""

import json
import logging
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from .alerts import AlertGroup
from .config import Settings
from .service import Outputs, Service
from .store import Store
from .tools import Investigator

log = logging.getLogger("trackside.agent")

QUEUE_DEPTH = Gauge("trackside_agent_queue_depth", "Notifications waiting to be handled.")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so Loki can parse the agent's logs."""

    RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        entry = {"time": self.formatTime(record), "level": record.levelname.lower(), "logger": record.name,
                 "msg": record.getMessage()}
        entry.update({k: v for k, v in record.__dict__.items() if k not in self.RESERVED})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def make_handler(work: "queue.Queue[AlertGroup]"):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: bytes, content_type: str = "text/plain") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            if self.path == "/healthz":
                self._reply(200, b"ok\n")
            elif self.path == "/metrics":
                self._reply(200, generate_latest(), CONTENT_TYPE_LATEST)
            else:
                self._reply(404, b"not found\n")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/alerts":
                self._reply(404, b"not found\n")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                group = AlertGroup.from_webhook(json.loads(self.rfile.read(min(length, 1_000_000))))
            except (ValueError, KeyError) as error:
                log.warning("rejected notification: %s", error)
                self._reply(400, f"bad payload: {error}\n".encode())
                return
            try:
                work.put_nowait(group)
            except queue.Full:
                self._reply(503, b"queue full\n")
                return
            QUEUE_DEPTH.set(work.qsize())
            self._reply(202, b"queued\n")

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - quiet access log
            pass

    return Handler


def worker(service: Service, work: "queue.Queue[AlertGroup]") -> None:
    while True:
        group = work.get()
        QUEUE_DEPTH.set(work.qsize())
        try:
            service.handle(group)
        except Exception:  # noqa: BLE001 - one bad notification must not stop the worker
            log.exception("failed to handle notification for %s", group.alertname)
        finally:
            work.task_done()


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    settings = Settings.from_env()
    outputs = Outputs.from_settings(settings)
    service = Service(settings, Store(settings.database_url), Investigator(settings), outputs)
    try:
        service.refresh_spend()
    except Exception:  # noqa: BLE001 - the database may still be starting
        log.warning("could not read this month's spend yet")

    work: queue.Queue[AlertGroup] = queue.Queue(maxsize=100)
    threading.Thread(target=worker, args=(service, work), daemon=True).start()

    port = int(os.environ.get("PORT", "8090"))
    log.info("listening", extra={
        "port": port, "model": settings.model, "claude": bool(settings.anthropic_api_key),
        "github": outputs.github is not None, "discord": outputs.discord is not None,
        "monthly_budget_usd": settings.monthly_budget_usd})
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(work)).serve_forever()


if __name__ == "__main__":
    main()
