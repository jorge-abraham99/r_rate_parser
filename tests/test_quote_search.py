from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from rate_ingest.config import Settings
from rate_ingest.models import RateCard, RateChargeLine, RateOffer
from rate_ingest.repositories import ApprovedRateLibrary, RateRepository
from rate_ingest import services


class QuoteFixture:
    """Small approved libraries exercise pricing and search without private workbooks."""

    def __init__(self, root: Path):
        self.settings = Settings.load(cwd=root)
        self.cards = []
        self.offers = []
        self.charges = []
        self.sources = {}

    def add(self, identity, *, carrier="COSCO", key="cosco-sea", mode="CY / CY",
            collection=None, pol="Felixstowe", pod="Mundra", amount=100,
            currency="USD", equipment="40HC", start=None, end=None,
            commodity="WASTE PAPER", label=None, charges=()):
        haulage = key in {"cosco-haulage", "haulage-q2"}
        card = RateCard(id=f"card-{identity}", rate_import_id=f"import-{identity}",
                        provider_name=carrier, carrier_name=carrier,
                        document_type="inland_export" if haulage else "ocean_export",
                        currency_default=currency, commodity=commodity)
        offer = RateOffer(id=identity, rate_card_id=card.id, origin=collection or pol,
                          place_of_receipt=collection or pol, pol=pol, pod=pol if haulage else pod,
                          final_destination=pol if haulage else pod,
                          service_mode=mode, equipment_type=equipment,
                          base_amount=amount, base_currency=currency,
                          valid_from=start, valid_to=end)
        self.cards.append(card)
        self.offers.append(offer)
        self.sources[card.rate_import_id] = {
            "operator_carrier_key": key, "operator_carrier_label": label,
            "contract_tag": "HAUL" if haulage else None, "file_name": f"{identity}.xlsx",
        }
        for index, (name, price, basis) in enumerate(charges):
            self.charges.append(RateChargeLine(id=f"charge-{identity}-{index}",
                rate_offer_id=identity, charge_name=name, amount=price,
                currency=currency, basis=basis, charge_type="surcharge"))
        return offer

    def repository(self):
        repository = Mock(spec=RateRepository)
        repository.backend_name = "csv"
        repository.list_import_records.return_value = ()
        repository.load_approved_rate_library.return_value = ApprovedRateLibrary(
            cards=tuple(self.cards), offers=tuple(self.offers), charges=tuple(self.charges),
            notes=(), source_by_import=self.sources)
        return repository

    def search(self, **filters):
        return services.search_rate_summaries(self.settings, repository=self.repository(), **filters)


@pytest.fixture
def quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("RATE_INGEST_ROOT", raising=False)
    monkeypatch.setenv("RATE_STORAGE_BACKEND", "csv")
    monkeypatch.setenv("SOURCE_STORAGE_BACKEND", "filesystem")
    return QuoteFixture(tmp_path)


@pytest.fixture
def mixed(quotes):
    quotes.add("ocean-fxt", charges=[("Emergency Fuel Surcharge", 50, "Container")])
    quotes.add("ocean-sou", pol="Southampton", amount=80,
               charges=[("Emergency Fuel Surcharge", 50, "Container")])
    quotes.add("ocean-singapore", pod="Singapore", amount=200)
    for identity, pickup, port, amount in [
        ("haul-bristol-fxt", "Bristol", "Felixstowe", 300),
        ("haul-leeds-fxt", "Leeds", "Felixstowe", 100),
        ("haul-bristol-sou", "Bristol", "Southampton", 600),
    ]:
        quotes.add(identity, key="cosco-haulage", mode="Door -> CY",
                   collection=pickup, pol=port, amount=amount)
    quotes.add("msc-door", carrier="MSC", key="msc-inline", mode="SD / CY",
               collection="Bristol", amount=500,
               charges=[("Documentation fee — Origin", 20, "Bill of Lading")])
    quotes.add("maersk-quay", carrier="Maersk", key="maersk-sea", amount=175)
    quotes.add("legacy-haul", carrier="UK Inland Haulage", key="haulage-q2",
               mode="Door -> CY", collection="Bristol", amount=1)
    return quotes


@pytest.mark.parametrize("filters,count,kinds", [
    ({"carrier_name": "COSCO"}, 5, {"combined"}),
    ({"carrier_name": "COSCO", "pol": "Felixstowe"}, 4, {"combined"}),
    ({"carrier_name": "COSCO", "pod": "Mundra"}, 3, {"combined"}),
    ({"carrier_name": "COSCO", "pol": "Felixstowe", "pod": "Mundra"}, 1, {"quay"}),
    ({"carrier_name": "COSCO", "collection": "Bristol"}, 3, {"combined"}),
    ({"collection": "Bristol", "pol": "Felixstowe", "pod": "Mundra"}, 2, {"combined", "door"}),
    ({"pol": "Felixstowe", "pod": "Mundra"}, 2, {"quay"}),
    ({}, 6, {"combined", "door"}),
])
def test_filter_rules_for_all_carriers(mixed, filters, count, kinds):
    result = mixed.search(**filters)
    assert result["pagination"]["total"] == count
    assert len(result["rates"]) == count
    assert {rate["quote_kind"] for rate in result["rates"]} == kinds
    assert len({rate["quote_id"] for rate in result["rates"]}) == count
    for rate in result["rates"]:
        if rate["quote_kind"] == "combined":
            assert rate["collection_location_name"]
            assert rate["all_in_usd"] == rate["ocean_all_in_usd"] + rate["inland_usd"]
            assert rate["haulage"]["provider_name"] == "COSCO Haulage"


def test_only_published_port_prices_without_inventing_haulage(mixed):
    result = mixed.search(pol="Felixstowe", pod="Mundra")
    assert {r["offer_id"]: r["all_in_usd"] for r in result["rates"]} == {
        "ocean-fxt": 150, "maersk-quay": 175,
    }
    assert mixed.search(carrier_name="MSC", pol="Felixstowe", pod="Mundra")["rates"] == []
    assert mixed.search(carrier_name="Maersk", collection="Bristol")["rates"] == []
    assert mixed.search(collection="Unknown collection")["rates"] == []


def test_multiple_filter_values_use_or_within_each_dimension(mixed):
    result = mixed.search(
        carrier_name=["COSCO", "Maersk"],
        pol=["Felixstowe", "Southampton"],
        pod=["Mundra", "Singapore"],
    )

    assert result["result_type"] == "quay"
    assert result["pagination"]["total"] == 4
    assert {rate["carrier_name"] for rate in result["rates"]} == {"COSCO", "Maersk"}
    assert {(rate["pol"], rate["pod"]) for rate in result["rates"]} == {
        ("Felixstowe", "Mundra"),
        ("Southampton", "Mundra"),
        ("Felixstowe", "Singapore"),
    }


def test_multiple_collections_preserve_complete_route_assembly(mixed):
    result = mixed.search(
        collection=["Bristol", "Leeds"],
        carrier_name=["COSCO", "MSC"],
        pol=["Felixstowe", "Southampton"],
        pod=["Mundra"],
    )

    assert result["pagination"]["total"] == 4
    assert {rate["collection_location_name"] for rate in result["rates"]} == {
        "Bristol, GB",
        "Leeds, GB",
    }
    assert {rate["carrier_name"] for rate in result["rates"]} == {"COSCO", "MSC"}


def test_multiple_filter_values_are_supported_by_csv_export(mixed):
    exported = services.export_rate_desk_csv(
        mixed.settings,
        carrier_name=["COSCO", "Maersk"],
        pol=["Felixstowe", "Southampton"],
        pod=["Mundra", "Singapore"],
        repository=mixed.repository(),
    )
    rows = list(csv.DictReader(StringIO(exported)))

    assert len(rows) == 4


def test_pagination_uses_complete_prices_and_distinct_combinations(quotes):
    # The cheaper ocean leg produces the more expensive complete route.
    quotes.add("cheap-ocean", amount=50)
    quotes.add("dearer-ocean", pol="Southampton", amount=100)
    for index in range(60):
        for port, amount in [("Felixstowe", 1000), ("Southampton", 200)]:
            quotes.add(f"haul-{index}-{port}", key="cosco-haulage", mode="Door -> CY",
                       collection=f"Collection {index}", pol=port, amount=amount)
    pages = [quotes.search(limit=50, offset=offset) for offset in (0, 50, 100)]
    assert [len(page["rates"]) for page in pages] == [50, 50, 20]
    assert all(page["pagination"]["total"] == 120 for page in pages)
    assert [page["pagination"]["has_more"] for page in pages] == [True, True, False]
    rows = [row for page in pages for row in page["rates"]]
    assert len({row["quote_id"] for row in rows}) == 120
    assert [row["all_in_usd"] for row in rows] == [300] * 60 + [1050] * 60
    assert pages[1] == quotes.search(limit=50, offset=50)

    exported = services.export_rate_desk_csv(
        quotes.settings,
        carrier_name="COSCO",
        containers=2,
        margin_usd=50,
        repository=quotes.repository(),
    )
    export_rows = list(csv.DictReader(StringIO(exported)))
    assert len(export_rows) == 120
    assert export_rows[0]["total_cost"] == "700.00 USD"
    assert export_rows[-1]["total_cost"] == "2200.00 USD"


def test_csv_export_contains_combined_route_and_margin(mixed):
    exported = services.export_rate_desk_csv(
        mixed.settings,
        carrier_name="COSCO",
        collection="Bristol",
        containers=2,
        margin_usd=50,
        repository=mixed.repository(),
    )
    rows = list(csv.DictReader(StringIO(exported)))

    assert list(rows[0]) == ["collection", "port_of_loading", "port_of_delivery", "total_cost"]
    assert {(row["collection"], row["port_of_loading"], row["port_of_delivery"])
            for row in rows} == {
                ("Bristol, GB", "Felixstowe", "Mundra, IN"),
                ("Bristol, GB", "Southampton", "Mundra, IN"),
                ("Bristol, GB", "Felixstowe", "Singapore"),
            }
    assert {row["total_cost"] for row in rows} == {"1000.00 USD", "1100.00 USD", "1560.00 USD"}


def test_csv_export_keeps_native_currency_for_single_currency_rates(quotes):
    quotes.add(
        "cma-door-gbp",
        carrier="CMA CGM",
        key="cma-door",
        mode="SD / CY",
        collection="Bristol",
        currency="GBP",
        amount=100,
    )
    exported = services.export_rate_desk_csv(
        quotes.settings,
        carrier_name="CMA CGM",
        collection="Bristol",
        containers=2,
        margin_usd=50,
        repository=quotes.repository(),
    )
    rows = list(csv.DictReader(StringIO(exported)))

    assert rows[0]["total_cost"] == "277.52 GBP"


@pytest.mark.parametrize("change", [
    {"equipment": "20GP"}, {"commodity": "SCRAP METAL"}, {"currency": "ZZZ"},
    {"amount": None}, {"pol": "Southampton"},
    {"start": "2026-10-01", "end": "2026-10-31"},
])
def test_incompatible_or_unpriced_haulage_is_not_a_complete_quote(quotes, change):
    quotes.add("ocean", start="2026-09-01", end="2026-09-30")
    quotes.add("haul", key="cosco-haulage", mode="Door -> CY", collection="Bristol", **change)
    assert quotes.search()["rates"] == []
    assert len(quotes.search(pol="Felixstowe", pod="Mundra")["rates"]) == 1


def test_combined_validity_and_expiry_are_applied_before_pagination(quotes):
    quotes.add("ocean", start="2020-01-01", end="2099-12-31")
    quotes.add("expired", key="cosco-haulage", mode="Door -> CY", collection="Bristol",
               start="2020-06-01", end="2020-06-30", amount=1)
    quotes.add("current", key="cosco-haulage", mode="Door -> CY", collection="Leeds",
               start="2026-09-01", end="2099-09-30", amount=200)
    result = quotes.search(include_expired=False, limit=1)
    assert result["pagination"]["total"] == 1
    assert result["hidden_expired"] == 1
    assert result["rates"][0]["haulage"]["offer_id"] == "current"
    assert result["rates"][0]["valid_from"] == "2026-09-01"
    assert result["rates"][0]["valid_to"] == "2099-09-30"
    assert quotes.search()["pagination"]["total"] == 2  # legacy API default
    assert quotes.search(valid_on="2026-08-31")["rates"] == []


@pytest.mark.parametrize("carrier,key", [("MSC", "msc-inline"), ("CMA CGM", "cma-door"),
                                         ("Hapag-Lloyd", "hapag-door"), ("Maersk", "maersk-sea")])
def test_published_door_rate_has_no_extra_haulage(quotes, carrier, key):
    quotes.add("door", carrier=carrier, key=key, mode="SD / CY", collection="Bristol", amount=500)
    quotes.add("haul", key="cosco-haulage", mode="Door -> CY", collection="Bristol", amount=300)
    row = quotes.search(collection="Bristol")["rates"][0]
    assert row["all_in_usd"] == 500
    assert row["quote_kind"] == "door"
    assert row["haulage"] is None
    assert quotes.search(pol="Felixstowe", pod="Mundra")["rates"] == []


@pytest.mark.parametrize("mode,label,expected", [
    ("CY / CY", None, "quay"), ("SD-CY", None, "door"),
    (None, "MSC · Door-to-quay", "door"), (None, "Quay-to-quay", "quay"),
    (None, None, "unknown"), ("CY / SD", None, "unknown"),
    ("CY / CY", "Door-to-quay", "unknown"),
])
def test_service_classification_uses_evidence(mode, label, expected):
    assert services.quote_service_kind({"service_mode": mode, "carrier_label": label}) == expected


def test_door_quote_with_unknown_port_never_matches_specific_port(quotes):
    quotes.add("door", carrier="Maersk", key="maersk-sea", mode="SD / CY", collection="Bristol", pol=None)
    assert len(quotes.search(collection="Bristol")["rates"]) == 1
    assert quotes.search(collection="Bristol", pol="Felixstowe")["rates"] == []


def test_metadata_ignores_legacy_haulage_and_ocean_receipt_ports(mixed):
    metadata = services.get_rate_desk_metadata(mixed.settings, repository=mixed.repository())
    assert set(metadata["haulage_tariffs_by_source"]) == {"cosco-haulage"}
    assert "Felixstowe" not in metadata["filters"]["collection_places"]


def test_frontend_consumes_real_search_results_and_preserves_prices(mixed):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for executable frontend regression checks")
    repository = mixed.repository()
    details = {offer.id: services.get_rate_offer_detail(mixed.settings, offer.id, repository=repository)
               for offer in mixed.offers}
    payload = {"browse": mixed.search(), "quay": mixed.search(pol="Felixstowe", pod="Mundra"),
               "collection": mixed.search(collection="Bristol", pol="Felixstowe", pod="Mundra"),
               "details": details}
    subprocess.run([node, "tests/quote_search_frontend.cjs"], input=json.dumps(payload),
                   text=True, check=True, capture_output=True)
