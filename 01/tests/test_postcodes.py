"""Postcode evidence extraction from mocked online search results."""

from unittest.mock import Mock

import pytest

from marketplace_agent.postcodes import PostcodeLookup


def result(body="PSČ 460 01", title="Liberec 1 PSČ", url="https://www.psc.cz/46001/"):
    return {"title": title, "body": body, "href": url}


@pytest.fixture
def lookup():
    tool = PostcodeLookup()
    tool.ddgs = Mock()
    tool._min_interval = 0
    return tool


def test_unique_online_postcode_is_normalized_and_keeps_its_source(lookup):
    lookup.ddgs.text.return_value = [result(), result("PSČ: 46001")]
    payload = lookup("Liberec 1")
    assert payload["requires_clarification"] is False
    assert [item["postcode"] for item in payload["candidates"]] == ["46001"]
    assert lookup.resolved["46001"]["source_url"] == "https://www.psc.cz/46001/"
    lookup.ddgs.text.assert_called_once_with(
        '"Liberec 1" PSČ Česká republika', max_results=5, region="cz-cs"
    )


def test_ambiguous_postcodes_cannot_authorize_a_marketplace_search(lookup):
    lookup.ddgs.text.return_value = [result("PSČ 460 01, 460 06")]
    payload = lookup("Liberec 1")
    assert payload["requires_clarification"] is True
    assert len(payload["candidates"]) == 2
    assert not lookup.resolved


@pytest.mark.parametrize(
    "item",
    [
        result("PSČ: 99999"),
        result("Phone 12345", title="Liberec 1"),
        result(title="Liberec 10 PSČ"),
        result(url="javascript:46001"),
        result(url="https:///46001"),
    ],
)
def test_invalid_or_unrelated_evidence_is_not_authorized(lookup, item):
    lookup.ddgs.text.return_value = [item]
    payload = lookup("Liberec 1")
    assert not payload["candidates"]
    assert not lookup.resolved


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("private upstream body")])
def test_lookup_failure_becomes_clear_tool_data_without_upstream_bodies(lookup, failure):
    lookup.ddgs.text.side_effect = failure
    payload = lookup("Liberec 1")
    assert "failed" in payload["error"]
    assert "private upstream body" not in payload["error"]
    assert payload["requires_clarification"] is True
    assert not lookup.resolved


def test_empty_lookup_does_not_invent_a_postcode(lookup):
    lookup.ddgs.text.return_value = []
    assert lookup("Liberec 1")["requires_clarification"] is True
    assert not lookup.resolved


def test_session_evidence_is_bounded(lookup):
    for index in range(33):
        lookup.ddgs.text.return_value = [result(f"PSČ {46000 + index}")]
        lookup("Liberec 1")
    assert len(lookup.resolved) == 32
    assert "46000" not in lookup.resolved
