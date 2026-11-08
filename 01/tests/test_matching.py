"""Realistic title regressions: relevance precedes sorting without arbitrary price floors."""

import pytest

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.common import filter_and_sort
from marketplace_agent.providers.matching import matches_product


@pytest.mark.parametrize(
    "title",
    [
        "RIMOWA kryt iPhone 17 Pro",
        "Kryty Apple , Android , IPad",
        "Privacy ochranné sklo iPhone 17 pro",
        "Ultratenký aramid kryt iPhone 17 pro",
        "Silikonový kryt 17 Pro",
        "Kryty na iPhone 17 Pro Max",
        "LCD Displej + Dotykové sklo Apple iPhone 12 / 12 Pro",
        "Apple iPhone 17 Pro Max vlnité pouzdro Gold",
        "Prázdná krabička od iPhonu 17",
        "Výměním Iphone 17 za 16 PRO MAX",
        "Koupím iPhone 17",
        "iPhone 15 Pro 128GB",
        "Baterie Apple iPhone 17",
        "IPhone 17 pro displej originálni",
        "MagSafe stojan na iPhone, skládací",
        "iPhone 17e 256 GB",
    ],
)
def test_phone_search_rejects_obvious_accessories_parts_trades_and_wrong_models(title):
    assert not matches_product(title, "iPhone 17")


@pytest.mark.parametrize(
    "title, query",
    [
        ("Apple iPhone 17, 256gb, baterie 100 %, Záruka", "iPhone 17"),
        ("iPhone17 s krytem a nabíječkou", "iPhone 17"),
        ("iPhone 17 + kryt", "iPhone 17"),
        ("iPhone 17 s originálním krytem", "iPhone 17"),
        ("iPhone 17 včetně nového pouzdra", "iPhone 17"),
        ("iPhone 17 poškozený displej", "iPhone 17"),
        ("LCD displej iPhone 17", "LCD iPhone 17"),
        ("Kryty na iPhone 17", "kryt iPhone 17"),
        ("Nvidia GeForce RTX4070 12GB", "RTX 4070"),
        ("Sony PlayStation 5", "PS5"),
        ("Apple MacBook Air 13 M2", "MacBook Air M2"),
    ],
)
def test_actual_products_bundles_and_explicit_accessory_searches_are_preserved(title, query):
    assert matches_product(title, query)


def test_cheap_genuine_phone_survives_and_cases_do_not_consume_final_limit():
    request = SearchRequest(query="iPhone 17", max_price=17000, sort_by="price_asc", limit=1)
    items = [
        Listing(title=title, price=price, url=url, location=None, description=None)
        for title, price, url in [
            ("Kryt iPhone 17", 10, "case"),
            ("Vyměním iPhone 17", 1, "trade"),
            ("iPhone 17 poškozený displej", 500, "cheap-phone"),
            ("Apple iPhone 17", 16490, "phone"),
        ]
    ]
    assert request.min_price is None
    assert [item.url for item in filter_and_sort(items, request)] == ["cheap-phone"]
