"""Check MCP readiness through actual tool discovery, without marketplace requests."""

import asyncio
import sys

from fastmcp import Client


async def check(url: str) -> None:
    async with Client(url, timeout=2) as client:
        tools = await client.list_tools()
        if [tool.name for tool in tools] != ["search_listings"]:
            raise RuntimeError("Expected exactly one search_listings tool")


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1]))
