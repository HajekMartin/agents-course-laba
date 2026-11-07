"""A development-only HTTP health endpoint using the Python standard library."""

import json
import logging
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event
from types import FrameType

from marketplace_agent import APP_NAME, __version__
from marketplace_agent.config import Settings

LOGGER = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """Report process health without probing any planned integrations."""

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404, "Not found")
            return

        payload = json.dumps(
            {"status": "ok", "application": APP_NAME, "version": __version__}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug(format, *args)


def serve(settings: Settings) -> None:
    """Run in the main thread and close the server cleanly on SIGINT or SIGTERM."""
    stopped = Event()

    def request_shutdown(signum: int, frame: FrameType | None) -> None:
        stopped.set()

    with ThreadingHTTPServer((settings.app_host, settings.app_port), HealthHandler) as server:
        server.timeout = 0.25
        previous_handlers = {
            sig: signal.signal(sig, request_shutdown) for sig in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            LOGGER.info(
                "Health server listening on http://%s:%s/health",
                settings.app_host,
                settings.app_port,
            )
            # A short request timeout lets signal handlers stop the main loop without
            # calling shutdown() from the same thread as serve_forever(), which deadlocks.
            while not stopped.is_set():
                server.handle_request()
        finally:
            for sig, previous_handler in previous_handlers.items():
                signal.signal(sig, previous_handler)
    LOGGER.info("Health server stopped")
