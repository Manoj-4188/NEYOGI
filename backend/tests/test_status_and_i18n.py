"""Status badges and the bilingual message catalogue.

The badge tests assert the exact strings the product spec names, because those
strings are the user-visible contract about data provenance.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backend import status
from backend.config import settings
from backend.services import i18n


def _days_ago(days: int) -> date:
    return datetime.now(tz=timezone.utc).date() - timedelta(days=days)


# --------------------------------------------------------------------------
# Badge text
# --------------------------------------------------------------------------


def test_cached_satellite_badge_matches_the_specified_wording() -> None:
    observed = _days_ago(5)
    badge = status.satellite_cached(observed)
    assert badge.label == f"🟡 CACHED SATELLITE TILE ({observed.isoformat()})"
    assert badge.status is status.SourceStatus.CACHED
    assert badge.severity is status.Severity.WARN
    assert badge.is_fallback


def test_cached_market_badge_matches_the_specified_wording() -> None:
    badge = status.market_cached(_days_ago(3))
    assert badge.label == "🟡 MARKET DATA CACHED"
    assert badge.is_fallback


def test_unvalidated_district_badge_matches_the_specified_wording() -> None:
    badge = status.district_unvalidated("Ramanagara")
    assert badge.label == "🔴 UNVALIDATED DISTRICT (No Verified Labels)"
    assert badge.status is status.SourceStatus.UNVALIDATED
    assert badge.severity is status.Severity.ERROR


def test_unvalidated_badge_explains_the_ndvi_fallback() -> None:
    detail = status.district_unvalidated("Ramanagara", parcel_count=12).detail
    assert "NDVI basemap" in detail
    assert "12 unverified" in detail


def test_live_badges_are_not_flagged_as_fallbacks() -> None:
    assert not status.satellite_live(date(2024, 6, 1)).is_fallback
    assert not status.market_live(date(2024, 6, 1)).is_fallback
    assert not status.district_validated(40, date(2024, 5, 1)).is_fallback


# --------------------------------------------------------------------------
# Staleness escalation
# --------------------------------------------------------------------------


def test_cached_satellite_escalates_to_red_past_the_age_limit() -> None:
    """A composite older than the policy window is not a usable fallback."""
    stale = _days_ago(settings.satellite_cache_max_age_days + 1)
    badge = status.satellite_cached(stale)
    assert badge.severity is status.Severity.ERROR
    assert badge.status is status.SourceStatus.UNAVAILABLE
    assert "STALE" in badge.label


def test_cached_satellite_inside_the_window_stays_amber() -> None:
    fresh = _days_ago(settings.satellite_cache_max_age_days - 1)
    assert status.satellite_cached(fresh).severity is status.Severity.WARN


def test_cached_market_escalates_past_the_thirty_day_window() -> None:
    stale = _days_ago(settings.market_cache_max_age_days + 5)
    assert status.market_cached(stale).severity is status.Severity.ERROR


def test_age_days_is_reported_on_dated_badges() -> None:
    assert status.satellite_cached(_days_ago(7)).age_days == 7


# --------------------------------------------------------------------------
# StatusSet aggregation
# --------------------------------------------------------------------------


def test_status_set_is_not_degraded_when_everything_is_live() -> None:
    badges = status.StatusSet()
    badges.add(status.satellite_live(date(2024, 6, 1)))
    badges.add(status.market_live(date(2024, 6, 1)))
    assert not badges.degraded
    assert badges.worst_severity is status.Severity.OK


def test_any_fallback_makes_the_set_degraded() -> None:
    badges = status.StatusSet()
    badges.add(status.satellite_live(date(2024, 6, 1)))
    badges.add(status.market_cached(_days_ago(2)))
    assert badges.degraded
    assert badges.worst_severity is status.Severity.WARN


def test_worst_severity_reports_the_error_when_present() -> None:
    badges = status.StatusSet()
    badges.add(status.market_cached(_days_ago(2)))
    badges.add(status.district_unvalidated("Hassan"))
    assert badges.worst_severity is status.Severity.ERROR


def test_status_set_serialises_for_the_api() -> None:
    import json

    badges = status.StatusSet().add(status.satellite_cached(_days_ago(1)))
    payload = json.loads(json.dumps(badges.to_dict()))
    assert payload["degraded"] is True
    assert payload["badges"][0]["icon"] == "🟡"


# --------------------------------------------------------------------------
# i18n catalogue
# --------------------------------------------------------------------------


def test_every_message_exists_in_both_languages() -> None:
    for key, entry in i18n.MESSAGES.items():
        assert set(entry) == {"en", "kn"}, key
        assert entry["en"].strip(), key
        assert entry["kn"].strip(), key


def test_kannada_messages_actually_use_kannada_script() -> None:
    """Guards against an English string being pasted into the kn column."""
    for key, entry in i18n.MESSAGES.items():
        assert any("ಀ" <= ch <= "೿" for ch in entry["kn"]), key


def test_placeholders_match_across_languages() -> None:
    """A missing placeholder in one language would render a broken message."""
    import string

    for key, entry in i18n.MESSAGES.items():
        fields = {
            tuple(
                sorted(
                    f for _, f, _, _ in string.Formatter().parse(entry[lang]) if f
                )
            )
            for lang in ("en", "kn")
        }
        assert len(fields) == 1, f"{key} has mismatched placeholders: {fields}"


def test_translation_renders_with_arguments() -> None:
    rendered = i18n.t("ask_crops", "kn", district="ಕೋಲಾರ")
    assert "ಕೋಲಾರ" in rendered


def test_unknown_language_falls_back_to_english() -> None:
    assert i18n.t("help", "fr") == i18n.MESSAGES["help"]["en"]


def test_missing_key_returns_empty_rather_than_raising() -> None:
    assert i18n.t("no_such_key", "en") == ""


# --------------------------------------------------------------------------
# Input parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("tomato", ["Tomato"]),
        ("ಟೊಮಾಟೊ", ["Tomato"]),
        ("Tomato, Onion", ["Tomato", "Onion"]),
        ("ಈರುಳ್ಳಿ, ಆಲೂಗಡ್ಡೆ", ["Onion", "Potato"]),
        ("palak", ["Leafy Greens"]),
        ("soppu", ["Leafy Greens"]),
    ],
)
def test_parse_crops_accepts_both_scripts(text, expected) -> None:
    crops, _ = i18n.parse_crops(text)
    assert crops == expected


def test_parse_crops_reports_unrecognised_tokens() -> None:
    crops, unknown = i18n.parse_crops("Tomato, Dragonfruit")
    assert crops == ["Tomato"]
    assert unknown == ["Dragonfruit"]


def test_parse_crops_deduplicates() -> None:
    crops, _ = i18n.parse_crops("tomato, Tomato, ಟೊಮಾಟೊ")
    assert crops == ["Tomato"]


SUPPORTED = [
    "Kolar",
    "Chikkaballapur",
    "Bengaluru Rural",
    "Ramanagara",
    "Tumakuru",
    "Hassan",
    "Mandya",
    "Chikkamagaluru",
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kolar", "Kolar"),
        ("kolar", "Kolar"),
        ("ಕೋಲಾರ", "Kolar"),
        ("ತುಮಕೂರು", "Tumakuru"),
        ("Chikkaballa", "Chikkaballapur"),  # unambiguous prefix
    ],
)
def test_parse_district_accepts_both_scripts_and_prefixes(text, expected) -> None:
    assert i18n.parse_district(text, SUPPORTED) == expected


def test_parse_district_refuses_an_ambiguous_prefix() -> None:
    """"Chikka" matches two districts -- guessing between them is not allowed."""
    assert i18n.parse_district("Chikka", SUPPORTED) is None


def test_parse_district_rejects_an_unsupported_district() -> None:
    assert i18n.parse_district("Mysuru", SUPPORTED) is None
    assert i18n.parse_district("nonsense", SUPPORTED) is None


def test_crop_and_district_display_names_localise() -> None:
    assert i18n.crop_name("Onion", "kn") == "ಈರುಳ್ಳಿ"
    assert i18n.crop_name("Onion", "en") == "Onion"
    assert i18n.district_name("Kolar", "kn") == "ಕೋಲಾರ"
    assert i18n.district_name("Kolar", "en") == "Kolar"
