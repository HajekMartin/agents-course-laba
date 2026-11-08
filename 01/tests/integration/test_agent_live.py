"""Opt-in native smolagents cycle against the actual local Unsloth and gateway."""

import os

import pytest

from marketplace_agent.agent import MarketplaceAgent
from marketplace_agent.config import Settings


@pytest.mark.live
@pytest.mark.skipif(os.getenv("AGENT_LIVE_E2E") != "true", reason="Set AGENT_LIVE_E2E=true")
def test_native_agent_with_actual_unsloth_and_both_mcp_servers():
    agent = MarketplaceAgent(Settings())
    try:
        answer = agent.run(
            "Najdi iPhone 15 do 12000 Kč. Prohledej oba bazary a seřaď od nejlevnějších."
        )
        assert agent.tool_call_count >= 2
        assert set(agent.last_results["searched_sources"]) == {"Bazoš", "Sbazar"}
        assert agent.last_results["search"]["max_price"] == 12000
        assert agent.last_results["search"]["sort_by"] == "price_asc"
        assert answer.strip()
        print(
            f"Native cycle verified: {agent.tool_call_count} calls, "
            f"{agent.last_results['count']} listings"
        )
        agent.run("A teď jen Bazoš v okolí PSČ 46001 do 30 km.", reset=False)
        assert agent.last_results["searched_sources"] == ["Bazoš"]
        assert agent.last_results["search"]["max_price"] == 12000
        assert agent.last_results["search"]["location"] == "46001"
        assert agent.last_results["search"]["radius_km"] == 30
    finally:
        agent.model.client.close()


@pytest.mark.live
@pytest.mark.skipif(os.getenv("POSTCODE_LIVE_E2E") != "true", reason="Set POSTCODE_LIVE_E2E=true")
def test_native_postcode_lookup_then_actual_marketplace_mcp():
    agent = MarketplaceAgent(Settings())
    try:
        answer = agent.run(
            "Najdi iPhone 15 do 12000 Kč do 30 km od Liberce 1, jen Bazoš. "
            "PSČ neznám, dohledej ho na internetu."
        )
        assert agent.postcode_lookup.resolved
        assert agent.last_results["search"]["location"] in agent.postcode_lookup.resolved
        assert agent.last_results["search"]["radius_km"] == 30
        assert agent.last_results["search"]["max_price"] == 12000
        assert agent.last_results["searched_sources"] == ["Bazoš"]
        assert agent.last_results["postcode_lookup"]["source_url"] in answer
        print(f"Native postcode lookup verified: {agent.last_results['postcode_lookup']}")
    finally:
        agent.model.client.close()
