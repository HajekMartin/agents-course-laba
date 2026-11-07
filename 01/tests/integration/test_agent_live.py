"""Opt-in actual Unsloth/gateway/MCP cycle, not proof of unrestricted marketplace access."""

import asyncio
import os

import pytest

from marketplace_agent.agent import connect_agent
from marketplace_agent.config import Settings


@pytest.mark.live
@pytest.mark.skipif(os.getenv("AGENT_LIVE_E2E") != "true", reason="Set AGENT_LIVE_E2E=true")
def test_native_agent_with_actual_unsloth_and_both_mcp_servers():
    async def run():
        trace = []
        async with connect_agent(Settings(), trace.append) as agent:
            reply = await agent.ask(
                "Najdi iPhone 15 do 12000 Kč. Prohledej oba bazary a seřaď od nejlevnějších."
            )
            assert reply.tool_calls >= 2
            assert set(reply.results["searched_sources"]) == {"Bazoš", "Sbazar"}
            assert reply.results["search"]["max_price"] == 12000
            assert reply.results["search"]["sort_by"] == "price_asc"
            assert reply.text.strip()
            assert any("Returning tool results" in line for line in trace)
            assert trace[-1] == "[LLM] Final response generated"
            for item in reply.results["listings"]:
                assert item["url"].startswith("https://")
                assert item["price"] is not None and item["price"] <= 12000
            print(
                f"Native cycle verified: {reply.tool_calls} calls, "
                f"{reply.results['count']} listings, incomplete={reply.results['incomplete']}"
            )
            followup = await agent.ask("A teď jen Bazoš v okolí PSČ 46001 do 30 km.")
            assert followup.results["searched_sources"] == ["Bazoš"]
            assert followup.results["search"]["max_price"] == 12000
            assert followup.results["search"]["location"] == "46001"
            assert followup.results["search"]["radius_km"] == 30
            assert "iphone" in followup.results["search"]["query"].lower()
            print(
                "Native follow-up verified: product/price retained, "
                "user postcode and source applied"
            )

    asyncio.run(run())
