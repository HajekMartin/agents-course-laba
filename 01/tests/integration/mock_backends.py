"""Test-only fixture HTTP backends, running in the existing Python Docker image."""

import asyncio
import json
import os
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import uvicorn

from marketplace_agent.mcp.bazos_server import mcp as bazos_mcp
from marketplace_agent.mcp.sbazar_server import mcp as sbazar_mcp
from marketplace_agent.providers import bazos, sbazar

FIXTURES = Path("/tests/fixtures")
MODEL = "stage04-local-test-model"


def mock_marketplace(provider, fixture: str) -> None:
    original = provider.search_listings

    async def search(request):
        def respond(http_request: httpx.Request) -> httpx.Response:
            if http_request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            return httpx.Response(
                200,
                content=(FIXTURES / fixture).read_bytes(),
                headers={
                    "Content-Type": "application/json" if fixture.endswith("json") else "text/html"
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await original(request, client)

    provider.search_listings = search


class OpenAIHandler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # Expected when the gateway times out the deliberately slow response.
        with suppress(BrokenPipeError):
            self.wfile.write(body)

    def authenticated(self) -> bool:
        if self.path.startswith("/anonymous/"):
            self.path = self.path.removeprefix("/anonymous")
            if self.headers.get("Authorization") is not None:
                self.respond(400, {"error": {"message": "Unexpected authentication header"}})
                return False
            return True
        if self.headers.get("Authorization") != "Bearer stage04-test-key":
            self.respond(401, {"error": {"message": "Authentication required"}})
            return False
        return True

    def do_GET(self) -> None:
        if not self.authenticated():
            return
        if self.path != "/v1/models":
            self.respond(404, {})
            return
        self.respond(200, {"object": "list", "data": [{"id": MODEL, "loaded": True}]})

    def do_POST(self) -> None:
        if not self.authenticated():
            return
        if self.path != "/v1/chat/completions":
            self.respond(404, {})
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if payload["model"] != MODEL:
            self.respond(404, {"error": {"message": "Unknown model"}})
            return
        if payload["messages"][-1]["content"] == "slow":
            time.sleep(1)
        message = {"role": "assistant", "content": json.dumps(payload)}
        finish_reason = "stop"
        if payload.get("tools"):
            observed = any(
                item.get("role") != "system" and "Observation:" in str(item.get("content", ""))
                for item in payload["messages"]
            )
            tools = [
                tool
                for tool in payload["tools"]
                if tool["function"]["name"].endswith("search_listings")
            ]
            calls = (
                [("final_answer", {"answer": "Fixture search finished."})]
                if observed
                else [
                    (
                        tool["function"]["name"],
                        {
                            "query": "test product",
                            "min_price": 1000,
                            "sort_by": "price_asc",
                            "limit": 3,
                        },
                    )
                    for tool in tools
                ]
            )
            if observed:
                assert "listings" in str(payload["messages"])
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"fixture-call-{index}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                    for index, (name, arguments) in enumerate(calls)
                ],
            }
            finish_reason = "tool_calls"
        self.respond(
            200,
            {
                "id": "chatcmpl-stage04",
                "object": "chat.completion",
                "created": 1,
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


async def main() -> None:
    os.environ["BAZOS_ACCESS_PERMITTED"] = "true"
    os.environ["SBAZAR_ACCESS_PERMITTED"] = "true"
    mock_marketplace(bazos, "bazos.html")
    mock_marketplace(sbazar, "sbazar.json")
    server = ThreadingHTTPServer(("0.0.0.0", 8888), OpenAIHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    await asyncio.gather(
        *(
            uvicorn.Server(
                uvicorn.Config(
                    mcp.http_app(path="/mcp", stateless_http=True, json_response=True),
                    host="0.0.0.0",
                    port=port,
                    log_level="error",
                )
            ).serve()
            for mcp, port in ((bazos_mcp, 8001), (sbazar_mcp, 8002))
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
