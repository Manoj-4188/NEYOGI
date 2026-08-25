"""Compositing windows and reduceRegions post-processing.

These cover the pure-Python parts of Phase 1 -- the parts that decide what gets
asked of Earth Engine and how its answers are turned into database rows. The
Earth Engine calls themselves are not mocked into fake imagery; they are simply
out of scope here.
"""

from __future__ import annotations

from datetime import date

import pytest

from ml_pipeline import config
from ml_pipeline import gee_ingestion as gi


# --------------------------------------------------------------------------
# Composite windows
# --------------------------------------------------------------------------


def test_windows_tile_the_range_without_gaps_or_overlap() -> None:
    windows = gi.build_composite_windows(date(2024, 1, 1), date(2024, 3, 1), 16)
    assert windows[0].start == date(2024, 1, 1)
    for earlier, later in zip(windows, windows[1:]):
        assert earlier.end == later.start
    assert windows[-1].end == date(2024, 3, 1)


def test_sixty_day_seed_produces_four_sixteen_day_windows() -> None:
    windows = gi.build_composite_windows(date(2024, 1, 1), date(2024, 3, 1), 16)
    # 60 days -> three full 16-day windows plus a 12-day remainder.
    assert len(windows) == 4
    assert [(w.end - w.start).days for w in windows] == [16, 16, 16, 12]


def test_windows_are_anchored_on_start_so_reruns_are_stable() -> None:
    """Identical boundaries across runs is what makes the cache addressable."""
    first = gi.build_composite_windows(date(2024, 5, 1), date(2024, 6, 2), 16)
    second = gi.build_composite_windows(date(2024, 5, 1), date(2024, 7, 4), 16)
    assert [w.start for w in second][: len(first)] == [w.start for w in first]


def test_empty_or_inverted_range_yields_no_windows() -> None:
    assert gi.build_composite_windows(date(2024, 1, 1), date(2024, 1, 1)) == []
    assert gi.build_composite_windows(date(2024, 3, 1), date(2024, 1, 1)) == []


def test_zero_period_is_rejected() -> None:
    with pytest.raises(ValueError):
        gi.build_composite_windows(date(2024, 1, 1), date(2024, 2, 1), 0)


def test_window_label_is_the_start_date() -> None:
    window = gi.CompositeWindow(date(2024, 4, 5), date(2024, 4, 21))
    assert window.label == "2024-04-05"


def test_seed_range_covers_the_configured_lookback() -> None:
    start, end = gi.seed_window_range(today=date(2024, 6, 30))
    assert end == date(2024, 6, 30)
    assert (end - start).days == config.SETTINGS.seed_lookback_days


def test_seed_lookback_default_is_sixty_days() -> None:
    """The cold-start seed the spec calls for."""
    assert config.SETTINGS.seed_lookback_days == 60
    assert config.SETTINGS.composite_period_days == 16


# --------------------------------------------------------------------------
# Band and index wiring
# --------------------------------------------------------------------------


def test_source_bands_cover_every_index_and_the_classifier() -> None:
    """SOURCE_BANDS is the union of index inputs and classifier features.

    B12 feeds no vegetation index here, but the spectral classifier takes it as
    one of its 17 features, so it has to be fetched even though nothing else
    reads it.
    """
    assert len(gi.COMPUTED_INDICES) == 11
    index_bands = {"B2", "B3", "B4", "B5", "B6", "B8", "B8A", "B11"}
    assert index_bands.issubset(set(gi.SOURCE_BANDS))
    assert "B12" in gi.SOURCE_BANDS
    assert set(gi.SOURCE_BANDS) == index_bands | {"B12"}


def test_scl_mask_classes_are_shadow_cloud_and_cirrus() -> None:
    assert config.SCL_MASK_CLASSES == (3, 8, 9, 10)


def test_native_scale_is_ten_metres() -> None:
    """reduceRegions must run at Sentinel-2 native resolution."""
    assert config.NATIVE_SCALE_M == 10


# --------------------------------------------------------------------------
# reduceRegions -> database rows
# --------------------------------------------------------------------------


def _row(parcel_id: int, **values) -> dict:
    row = {"parcel_id": parcel_id}
    row.update({f"{k}_mean": v for k, v in values.items()})
    return row


def test_reduction_rows_become_one_record_per_index() -> None:
    rows = [_row(1, NDVI=0.62, EVI=0.41, NDMI=0.22)]
    records = gi.records_from_reduction(rows, date(2024, 5, 1), scene_count=4)
    assert {r.index_name for r in records} == {"NDVI", "EVI", "NDMI"}
    assert all(r.parcel_id == 1 for r in records)
    assert all(r.observation_date == date(2024, 5, 1) for r in records)
    assert all(r.scene_count == 4 for r in records)


def test_null_index_values_are_dropped_not_zero_filled() -> None:
    """A cloud-masked parcel leaves a gap; a gap is not a measurement of zero."""
    rows = [_row(7, NDVI=None, EVI=0.33)]
    records = gi.records_from_reduction(rows, date(2024, 5, 1), scene_count=2)
    assert [r.index_name for r in records] == ["EVI"]
    assert all(r.value != 0.0 for r in records)


def test_rows_without_a_parcel_id_are_skipped() -> None:
    records = gi.records_from_reduction(
        [{"NDVI_mean": 0.5}], date(2024, 5, 1), scene_count=1
    )
    assert records == []


def test_bare_band_name_is_accepted_when_no_mean_suffix_is_present() -> None:
    records = gi.records_from_reduction(
        [{"parcel_id": 3, "NDVI": 0.7}], date(2024, 5, 1), scene_count=1
    )
    assert len(records) == 1
    assert records[0].value == pytest.approx(0.7)


def test_non_numeric_values_are_discarded() -> None:
    records = gi.records_from_reduction(
        [{"parcel_id": 3, "NDVI_mean": "n/a"}], date(2024, 5, 1), scene_count=1
    )
    assert records == []


def test_pixel_count_is_carried_through() -> None:
    rows = [{"parcel_id": 5, "NDVI_mean": 0.4, "NDVI_count": 128}]
    records = gi.records_from_reduction(rows, date(2024, 5, 1), scene_count=3)
    assert records[0].pixel_count == 128


def test_record_as_row_matches_the_insert_column_order() -> None:
    record = gi.ParcelIndexRecord(
        parcel_id=9,
        index_name="NDVI",
        observation_date=date(2024, 5, 1),
        value=0.55,
        scene_count=3,
        pixel_count=64,
    )
    assert record.as_row() == (9, "NDVI", date(2024, 5, 1), 0.55, 3, 64)


# --------------------------------------------------------------------------
# Ingestion report
# --------------------------------------------------------------------------


def test_report_coverage_ratio() -> None:
    report = gi.IngestionReport(district="Kolar")
    report.windows_requested = 4
    report.windows_with_imagery = 3
    assert report.coverage_ratio == pytest.approx(0.75)


def test_report_coverage_is_zero_when_nothing_was_requested() -> None:
    assert gi.IngestionReport(district="Kolar").coverage_ratio == 0.0


def test_report_serialises_for_the_telemetry_endpoint() -> None:
    import json

    report = gi.IngestionReport(district="Kolar")
    report.windows_requested = 2
    report.windows_empty.append("2024-05-01")
    report.low_confidence_windows.append("2024-05-17")
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["district"] == "Kolar"
    assert payload["windows_empty"] == ["2024-05-01"]
    assert payload["low_confidence_windows"] == ["2024-05-17"]


def test_parcels_without_geometry_are_rejected_loudly() -> None:
    with pytest.raises(ValueError, match="usable geometry"):
        gi.parcels_to_feature_collection([{"id": 1, "geometry": None}])
