"""AGMARKNET key sanitiser and record parsing.

The sanitiser is the layer that keeps this integration from breaking silently
when data.gov.in changes its field casing -- which it has done more than once.
These tests pin every spelling the feed has been observed to use.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services import agmarknet as ag


# --------------------------------------------------------------------------
# Key sanitiser
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Title case with underscores -- the long-standing shape.
        ("Modal_Price", "modal_price"),
        ("Arrival_Date", "arrival_date"),
        ("Min_Price", "min_price"),
        ("Max_Price", "max_price"),
        # Already snake_case.
        ("modal_price", "modal_price"),
        # Escaped spaces, as the upstream export emits them.
        ("Modal_x0020_Price", "modal_price"),
        ("Arrival_x0020_Date", "arrival_date"),
        ("Commodity_x0020_Name", "commodity_name"),
        # camelCase / PascalCase.
        ("arrivalDate", "arrival_date"),
        ("ModalPrice", "modal_price"),
        ("CommodityName", "commodity_name"),
        # Spaces, hyphens and stray punctuation.
        ("Modal Price", "modal_price"),
        ("Modal-Price", "modal_price"),
        ("  District  ", "district"),
        ("STATE", "state"),
    ],
)
def test_sanitise_key(raw: str, expected: str) -> None:
    assert ag.sanitise_key(raw) == expected


def test_sanitise_record_maps_aliases_onto_canonical_names() -> None:
    record = {
        "State": "Karnataka",
        "District": "Kolar",
        "Market": "Kolar",
        "Commodity": "Tomato",
        "Arrival_x0020_Date": "24/06/2024",
        "Modal_x0020_Price": "1450",
    }
    clean = ag.sanitise_record(record)
    assert clean["state"] == "Karnataka"
    assert clean["district"] == "Kolar"
    assert clean["arrival_date"] == "24/06/2024"
    assert clean["modal_price"] == "1450"


def test_sanitise_record_preserves_unknown_fields_rather_than_dropping_them() -> None:
    """A newly added upstream column must be visible, not silently discarded."""
    clean = ag.sanitise_record({"Some_New_Column": "42"})
    assert clean["some_new_column"] == "42"


def test_upstream_typo_alias_is_handled() -> None:
    assert ag.sanitise_record({"Model_Price": "900"})["modal_price"] == "900"


# --------------------------------------------------------------------------
# Value coercion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1450", 1450.0),
        ("1,450", 1450.0),
        (" 1450.5 ", 1450.5),
        (1450, 1450.0),
    ],
)
def test_to_float_parses_prices(raw, expected) -> None:
    assert ag._to_float(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "-", "NA", "N/A", "null", "not a number"])
def test_to_float_treats_placeholders_as_missing(raw) -> None:
    assert ag._to_float(raw) is None


def test_zero_price_is_missing_not_free() -> None:
    """The feed writes 0 for "not reported"; treating it as a price is wrong."""
    assert ag._to_float("0") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("24/06/2024", date(2024, 6, 24)),
        ("2024-06-24", date(2024, 6, 24)),
        ("24-06-2024", date(2024, 6, 24)),
    ],
)
def test_to_date_accepts_every_observed_format(raw, expected) -> None:
    assert ag._to_date(raw) == expected


def test_to_date_returns_none_on_garbage() -> None:
    assert ag._to_date("last tuesday") is None


# --------------------------------------------------------------------------
# Record parsing
# --------------------------------------------------------------------------


def _record(**overrides) -> dict:
    base = {
        "State": "Karnataka",
        "District": "Kolar",
        "Market": "Kolar",
        "Commodity": "Tomato",
        "Variety": "Hybrid",
        "Arrival_Date": "24/06/2024",
        "Min_Price": "1200",
        "Max_Price": "1800",
        "Modal_Price": "1450",
    }
    base.update(overrides)
    return base


def test_parse_record_builds_a_quote() -> None:
    quote = ag.parse_record(_record())
    assert quote is not None
    assert quote.district == "Kolar"
    assert quote.crop == "Tomato"
    assert quote.modal_price == pytest.approx(1450.0)
    assert quote.arrival_date == date(2024, 6, 24)


def test_arrival_volume_is_none_when_the_feed_omits_it() -> None:
    """The daily price resource usually has no arrivals column at all."""
    quote = ag.parse_record(_record())
    assert quote is not None
    assert quote.arrival_volume is None


def test_arrivals_in_quintals_are_converted_to_tonnes() -> None:
    quote = ag.parse_record(_record(Arrivals_in_Qtl="2500"))
    assert quote is not None
    assert quote.arrival_volume == pytest.approx(250.0)


def test_arrivals_already_in_tonnes_pass_through() -> None:
    quote = ag.parse_record(_record(Arrival_Tonnes="250"))
    assert quote is not None
    assert quote.arrival_volume == pytest.approx(250.0)


def test_commodity_outside_our_crop_set_is_skipped() -> None:
    assert ag.parse_record(_record(Commodity="Ragi")) is None


def test_leafy_green_commodities_map_to_the_aggregate_class() -> None:
    for commodity in ("Amaranthus", "Spinach", "Coriander(Leaves)"):
        quote = ag.parse_record(_record(Commodity=commodity))
        assert quote is not None, commodity
        assert quote.crop == "Leafy Greens"
        # The specific commodity is retained alongside the aggregate class.
        assert quote.commodity == commodity


def test_record_missing_a_date_is_skipped() -> None:
    assert ag.parse_record(_record(Arrival_Date="")) is None


def test_record_missing_a_district_is_skipped() -> None:
    assert ag.parse_record(_record(District="")) is None


def test_missing_prices_become_none_not_zero() -> None:
    quote = ag.parse_record(_record(Min_Price="NA", Max_Price="", Modal_Price="0"))
    assert quote is not None
    assert quote.min_price is None
    assert quote.max_price is None
    assert quote.modal_price is None


# --------------------------------------------------------------------------
# Payload handling
# --------------------------------------------------------------------------


def test_parse_payload_filters_to_usable_records() -> None:
    payload = {
        "records": [
            _record(),
            _record(Commodity="Ragi"),
            _record(Commodity="Onion", Modal_Price="2200"),
        ]
    }
    quotes = ag.parse_payload(payload)
    assert [q.crop for q in quotes] == ["Tomato", "Onion"]


def test_parse_payload_rejects_an_unexpected_shape() -> None:
    with pytest.raises(ag.AgmarknetUnavailable):
        ag.parse_payload({"message": "quota exceeded"})


def test_empty_records_list_is_valid_and_yields_nothing() -> None:
    assert ag.parse_payload({"records": []}) == []


# --------------------------------------------------------------------------
# Crop mapping
# --------------------------------------------------------------------------


def test_every_modelled_crop_except_fallow_has_a_commodity_mapping() -> None:
    from ml_pipeline import config as ml_config

    modelled = set(ml_config.CROP_CLASSES) - {"Fallow/Non-Crop"}
    assert modelled == set(ag.CROP_TO_COMMODITIES)


def test_quote_serialises_with_an_explicit_price_unit() -> None:
    quote = ag.parse_record(_record())
    assert quote is not None
    payload = quote.to_dict()
    assert payload["price_unit"] == "INR/quintal"
    assert payload["arrival_volume_mt"] is None
