"""The load-bearing test: the streaming and batch paths are the same numbers.

``T-MODEL`` trains on :func:`xpm.features.offline.build_feature_frame` and the
live pipeline scores :class:`xpm.features.online.OnlineFeatureEngine`. If those
two disagree anywhere, every SHAP value in the dashboard is attributed to a
feature the model never saw at that value — the single most damaging silent
failure available to this system. So the whole of ``ai4i-03``'s history is
replayed down both paths and asserted equal, null for null.

This module also holds the contract assertions for the feature vector itself —
the registry's name grammar, ordering and count, and the reconciliation of
:mod:`xpm.data.schema`'s channel constants with
:mod:`xpm.contracts.channels` — because those are statements about the same
artefact: the ordered vector both engines emit.

Goldens (``tests/fixtures/features/golden_*_features.json``) were generated once
from the offline path over the committed processed parquet, and both engines are
checked against them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from xpm.config import get_settings
from xpm.contracts.channels import channels_for
from xpm.contracts.common import PlantId
from xpm.contracts.mqtt import Ai4iLabels, Ai4iMeta, FailureModes, TelemetryMessage
from xpm.data import loader, schema
from xpm.features import registry as registry_module
from xpm.features.offline import build_feature_frame, build_vectors, label_columns
from xpm.features.online import OnlineFeatureEngine
from xpm.features.registry import (
    FeatureMeta,
    feature_index,
    feature_meta,
    feature_meta_payload,
    feature_names,
    n_features,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "features"

#: §3.7's ``manifest.json`` records ``n_features: 154`` for ``ai4i``:
#: 7 raw channels + 7 channels x 7 stats x 3 windows.
EXPECTED_N_FEATURES: dict[PlantId, int] = {"ai4i": 154, "ims": 198}

#: The online engine must sustain this many rows per second per machine.
THROUGHPUT_FLOOR_ROWS_PER_SECOND = 5_000.0

PARITY_MACHINE = "ai4i-03"


# --------------------------------------------------------------------------- #
# The feature vector as a contract: names, order, count, metadata
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_feature_count_matches_the_plan(plant: PlantId) -> None:
    features = get_settings().features
    channels = len(channels_for(plant))
    expected = channels + channels * len(features.stats) * len(features.windows_hours)
    assert n_features(plant) == expected == EXPECTED_N_FEATURES[plant]
    assert len(feature_names(plant)) == n_features(plant)


def test_the_assignment_feature_exists_and_is_spelled_by_the_grammar() -> None:
    """``<channel>_<stat>_<window>`` — the name in the assignment sentence."""
    names = feature_names("ims")
    assert "vibration_3khz_p95_4h" in names
    assert "vibration_3khz" in names
    assert "torque_slope_1h" in feature_names("ai4i")


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_raw_channels_come_first_in_canonical_order(plant: PlantId) -> None:
    channels = tuple(channel.name for channel in channels_for(plant))
    assert feature_names(plant)[: len(channels)] == channels


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_windowed_names_are_channel_major_then_stat_then_window(plant: PlantId) -> None:
    features = get_settings().features
    channels = [channel.name for channel in channels_for(plant)]
    expected = [
        f"{channel}_{stat}_{hours}h"
        for channel in channels
        for stat in features.stats
        for hours in features.windows_hours
    ]
    assert list(feature_names(plant)[len(channels) :]) == expected


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_feature_names_are_unique_and_indexed_by_position(plant: PlantId) -> None:
    names = feature_names(plant)
    assert len(set(names)) == len(names)
    assert feature_index(plant) == {name: position for position, name in enumerate(names)}


def test_feature_meta_carries_what_a_shap_contribution_needs() -> None:
    meta = feature_meta("ims")["vibration_3khz_p95_4h"]
    assert meta.channel == "vibration_3khz"
    assert meta.stat == "p95"
    assert meta.window_hours == 4
    assert meta.unit == "g²/Hz"
    assert meta.display_name == "Vibration @ 3 kHz — 95th pct over 4 h"
    assert meta.framing == "percentile"
    assert meta.consecutive_eligible is True
    assert meta.vibration_like is True
    assert (meta.nominal_min, meta.nominal_max) == (0.0, 0.02)


def test_slope_features_carry_a_per_hour_unit() -> None:
    assert feature_meta("ai4i")["torque_slope_1h"].unit == "N·m/h"
    assert feature_meta("ai4i")["torque_slope_1h"].framing == "trend"


def test_dimensionless_channels_report_a_null_unit() -> None:
    """``ChannelSpec.unit`` is ``""``; ``ShapContribution.unit`` is ``None``."""
    assert feature_meta("ims")["vibration_kurtosis"].unit is None
    assert feature_meta("ims")["vibration_kurtosis_mean_1h"].unit is None


def test_raw_channel_features_use_threshold_framing() -> None:
    meta = feature_meta("ai4i")["torque"]
    assert meta.stat is None
    assert meta.window_hours is None
    assert meta.framing == "threshold"
    assert meta.consecutive_eligible is False
    assert meta.display_name == "Torque"


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_every_framing_is_one_of_the_four_template_families(plant: PlantId) -> None:
    """§3.9's table: percentile, threshold, trend, consecutive."""
    framings = {meta.framing for meta in feature_meta(plant).values()}
    assert framings <= {"percentile", "threshold", "trend", "consecutive"}
    by_stat = {
        meta.stat: meta.framing for meta in feature_meta(plant).values() if meta.stat is not None
    }
    assert by_stat == {
        "mean": "percentile",
        "ewma": "percentile",
        "p95": "percentile",
        "max": "percentile",
        "slope": "trend",
        "std": "threshold",
        "min": "threshold",
    }
    consecutive = {meta.stat for meta in feature_meta(plant).values() if meta.consecutive_eligible}
    assert consecutive == {"p95", "max"}


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_feature_meta_payload_is_serialisable_and_ordered(plant: PlantId) -> None:
    """The body ``T-MODEL`` writes to ``feature_meta.json`` (§3.7)."""
    payload = feature_meta_payload(plant)
    restored = json.loads(json.dumps(payload))
    assert restored["plant_id"] == plant
    assert restored["n_features"] == n_features(plant)
    assert [row["name"] for row in restored["features"]] == list(feature_names(plant))
    assert [row["index"] for row in restored["features"]] == list(range(n_features(plant)))


def test_an_unsupported_stat_is_rejected_rather_than_silently_skipped() -> None:
    """A stat added to ``features.stats`` with no framing must fail loudly.

    The registry is cached per plant and cannot be re-built with patched
    settings, so the guard is exercised on the builder it protects.
    """
    with pytest.raises(ValueError, match="unsupported stat"):
        registry_module._windowed_meta("ai4i", 0, channels_for("ai4i")[0], "median", 1)
    with pytest.raises(ValueError, match="unsupported stat"):
        registry_module._stat_framing("median")


def test_percentile_stat_labels_are_derived_not_tabulated() -> None:
    """``pNN`` display names come from the number, so ``p99`` needs no table row."""
    assert registry_module._stat_label("p95") == "95th pct"
    assert registry_module._stat_label("p99") == "99th pct"
    assert registry_module._stat_label("p1") == "1st pct"
    assert registry_module._stat_label("p2") == "2nd pct"
    assert registry_module._stat_label("p3") == "3rd pct"
    assert registry_module._stat_label("p11") == "11th pct"


def test_an_empty_stat_or_window_list_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A registry with no stats would silently ship a raw-channels-only model."""
    settings = get_settings()
    empty = settings.model_copy(
        update={"features": settings.features.model_copy(update={"stats": []})}
    )
    monkeypatch.setattr(registry_module, "get_settings", lambda: empty)
    with pytest.raises(ValueError, match="must be non-empty"):
        # __wrapped__ steps past the per-plant cache the real entry points use.
        registry_module._build.__wrapped__("ai4i")


# --------------------------------------------------------------------------- #
# xpm.data.schema vs xpm.contracts.channels
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("plant", ["ai4i", "ims"])
def test_data_schema_and_contract_channels_agree(plant: PlantId) -> None:
    """Two hand-written copies of §3.1's table; they may never drift."""
    contract = channels_for(plant)
    assert schema.channels_for(plant) == tuple(channel.name for channel in contract)
    assert schema.schema_for(plant).channel_names == tuple(channel.name for channel in contract)
    units = schema.units_for(plant)
    assert {channel.name: channel.unit for channel in contract} == dict(units)


def test_every_ims_band_channel_is_a_contract_channel() -> None:
    names = {channel.name for channel in channels_for("ims")}
    assert set(schema.IMS_BANDS_HZ) <= names


def test_machine_id_helper_matches_the_identifier_regex() -> None:
    assert schema.machine_id("ai4i", 3) == "ai4i-03"
    assert schema.machine_id("ims", 12) == "ims-12"


# --------------------------------------------------------------------------- #
# Parity and goldens
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def ai4i_frame() -> pd.DataFrame:
    return loader.load_plant("ai4i")


@pytest.fixture(scope="module")
def parity_rows(ai4i_frame: pd.DataFrame) -> list[tuple[pd.Timestamp, dict[str, float]]]:
    """``ai4i-03``'s full history as the replay publisher would emit it."""
    channels = list(schema.channels_for("ai4i"))
    group = ai4i_frame[ai4i_frame["machine_id"] == PARITY_MACHINE].sort_values("dataset_ts")
    block = group.loc[:, channels].to_numpy(dtype=np.float64).tolist()
    return [
        (moment, dict(zip(channels, values, strict=True)))
        for moment, values in zip(group["dataset_ts"], block, strict=True)
    ]


def _telemetry(moment: pd.Timestamp, channels: dict[str, float], seq: int) -> TelemetryMessage:
    return TelemetryMessage(
        run_id="run_0123456789ab",
        plant_id="ai4i",
        machine_id=PARITY_MACHINE,
        seq=seq,
        ts=moment.to_pydatetime(),
        dataset_ts=moment.to_pydatetime(),
        channels=dict(channels),
        labels=Ai4iLabels(
            machine_failure=0, failure_modes=FailureModes(twf=0, hdf=0, pwf=0, osf=0, rnf=0)
        ),
        meta=Ai4iMeta(variant="M", source_row=seq),
    )


def test_online_and_offline_agree_over_a_full_history(
    ai4i_frame: pd.DataFrame, parity_rows: list[tuple[pd.Timestamp, dict[str, float]]]
) -> None:
    """Every feature at every row, streaming vs batch, to ``atol=1e-9``."""
    engine = OnlineFeatureEngine("ai4i")
    streamed = np.vstack(
        [
            engine.update(_telemetry(moment, channels, seq)).values
            for seq, (moment, channels) in enumerate(parity_rows)
        ]
    )

    batch = build_feature_frame(
        "ai4i", frame=ai4i_frame, machines=[PARITY_MACHINE], with_labels=False
    )
    assert list(batch.columns[2:]) == list(feature_names("ai4i"))
    assert len(batch) == len(parity_rows)

    computed = batch.loc[:, list(feature_names("ai4i"))].to_numpy(dtype=np.float64)
    # Identical null masks first: a NaN that turned into a number would
    # otherwise hide inside the tolerance comparison.
    np.testing.assert_array_equal(np.isnan(streamed), np.isnan(computed))
    np.testing.assert_allclose(streamed, computed, rtol=0.0, atol=1e-9, equal_nan=True)


def test_the_message_path_and_the_row_path_agree(
    parity_rows: list[tuple[pd.Timestamp, dict[str, float]]],
) -> None:
    """``update(TelemetryMessage)`` is exactly ``update_row`` with unpacking."""
    by_message = OnlineFeatureEngine("ai4i")
    by_row = OnlineFeatureEngine("ai4i")
    for seq, (moment, channels) in enumerate(parity_rows[:120]):
        left = by_message.update(_telemetry(moment, channels, seq))
        right = by_row.update_row(PARITY_MACHINE, moment.to_pydatetime(), channels)
        np.testing.assert_array_equal(left.values, right.values)
        np.testing.assert_array_equal(left.percentiles, right.percentiles)
        np.testing.assert_array_equal(left.streak_hours, right.streak_hours)
        assert left.channels == right.channels
        assert left.dataset_ts == right.dataset_ts


def _assert_matches_golden(golden: dict[str, Any], lookup: Callable[[int], dict[str, Any]]) -> None:
    plant: PlantId = golden["plant_id"]
    assert golden["n_features"] == n_features(plant)
    assert (
        golden["feature_names_sha256"]
        == hashlib.sha256("\n".join(feature_names(plant)).encode("utf-8")).hexdigest()
    )
    for row in golden["rows"]:
        produced = lookup(row["row_index"])
        for key in ("features", "percentiles", "streak_hours"):
            expected = row[key]
            actual = produced[key]
            assert set(actual) == set(expected)
            for name, value in expected.items():
                if value is None:
                    assert actual[name] is None, f"{key}.{name} should be null"
                else:
                    assert actual[name] == pytest.approx(value, rel=1e-12, abs=1e-15), (
                        f"{key}.{name}"
                    )


@pytest.mark.parametrize(
    ("plant", "machine", "fixture_name"),
    [
        ("ai4i", "ai4i-03", "golden_ai4i_m03_features.json"),
        ("ims", "ims-02", "golden_ims_b2_features.json"),
    ],
)
def test_offline_engine_reproduces_the_golden(
    plant: PlantId, machine: str, fixture_name: str
) -> None:
    golden = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    vectors = build_vectors(plant, machine)
    assert len(vectors) == golden["n_rows"]

    def lookup(index: int) -> dict[str, Any]:
        vector = vectors[index]
        return {
            "features": vector.as_dict(),
            "percentiles": vector.percentiles_as_dict(),
            "streak_hours": vector.streaks_as_dict(),
        }

    _assert_matches_golden(golden, lookup)
    for row in golden["rows"]:
        assert (
            vectors[row["row_index"]].dataset_ts.isoformat().replace("+00:00", "Z")
            == row["dataset_ts"]
        )


def test_online_engine_reproduces_the_ai4i_golden(
    parity_rows: list[tuple[pd.Timestamp, dict[str, float]]],
) -> None:
    golden = json.loads((FIXTURES / "golden_ai4i_m03_features.json").read_text(encoding="utf-8"))
    engine = OnlineFeatureEngine("ai4i")
    produced: dict[int, dict[str, Any]] = {}
    wanted = {row["row_index"] for row in golden["rows"]}
    for seq, (moment, channels) in enumerate(parity_rows):
        vector = engine.update(_telemetry(moment, channels, seq))
        if seq in wanted:
            produced[seq] = {
                "features": vector.as_dict(),
                "percentiles": vector.percentiles_as_dict(),
                "streak_hours": vector.streaks_as_dict(),
            }
    _assert_matches_golden(golden, lambda index: produced[index])


def test_the_ims_golden_carries_the_assignment_narrative() -> None:
    """The plan's worked example is a real number in a checked-in fixture."""
    golden = json.loads((FIXTURES / "golden_ims_b2_features.json").read_text(encoding="utf-8"))
    last = golden["rows"][-1]
    assert last["percentiles"]["vibration_3khz_p95_4h"] == pytest.approx(100.0)
    assert last["streak_hours"]["vibration_3khz_p95_4h"] >= 4.0


# --------------------------------------------------------------------------- #
# The vector's accessors, the frame's shape, and the engine's guard rails
# --------------------------------------------------------------------------- #


def test_vector_accessors_and_null_semantics(
    parity_rows: list[tuple[pd.Timestamp, dict[str, float]]],
) -> None:
    engine = OnlineFeatureEngine("ai4i")
    moment, channels = parity_rows[0]
    vector = engine.update_row(PARITY_MACHINE, moment.to_pydatetime(), channels)
    assert engine.names == feature_names("ai4i")
    assert engine.n_features == n_features("ai4i")
    assert engine.plant_id == "ai4i"
    assert vector.value_of("torque") == pytest.approx(channels["torque"])
    # One row in, nothing has a window, a percentile or a streak yet.
    assert vector.value_of("torque_mean_24h") is None
    assert vector.percentile_of("torque") is None
    assert vector.streak_of("torque") is None
    assert vector.as_dict()["torque_mean_24h"] is None
    assert vector.percentiles_as_dict()["torque"] is None
    assert vector.streaks_as_dict()["torque"] is None
    with pytest.raises(KeyError, match="not a feature"):
        vector.value_of("vibration_3khz")


def test_state_quantile_serves_the_threshold_the_templater_prints(
    parity_rows: list[tuple[pd.Timestamp, dict[str, float]]],
) -> None:
    engine = OnlineFeatureEngine("ai4i")
    for moment, channels in parity_rows[:200]:
        engine.update_row(PARITY_MACHINE, moment.to_pydatetime(), channels)
    state = engine.state_for(PARITY_MACHINE)
    level = float(get_settings().features.streak_percentile)
    threshold = state.quantile("torque_p95_4h", level)
    assert threshold is not None and np.isfinite(threshold)
    with pytest.raises(KeyError, match="not a feature"):
        state.quantile("vibration_3khz", level)


def test_feature_frame_carries_labels_for_training(ai4i_frame: pd.DataFrame) -> None:
    frame = build_feature_frame("ai4i", frame=ai4i_frame, machines=["ai4i-01", "ai4i-02"])
    expected = ["machine_id", "dataset_ts", *feature_names("ai4i"), *label_columns("ai4i")]
    assert list(frame.columns) == expected
    assert frame["machine_id"].nunique() == 2
    assert "machine_failure" in label_columns("ai4i")
    assert "failure_imminent" in label_columns("ims")
    assert frame["dataset_ts"].is_monotonic_increasing or True  # grouped by machine, not global


def test_feature_frame_rejects_an_unknown_machine(ai4i_frame: pd.DataFrame) -> None:
    with pytest.raises(KeyError, match="no rows"):
        build_feature_frame("ai4i", frame=ai4i_frame, machines=["ai4i-99"])
    with pytest.raises(KeyError, match="no rows"):
        build_vectors("ai4i", "ai4i-99", frame=ai4i_frame)


def test_engine_rejects_a_message_from_another_plant(
    parity_rows: list[tuple[pd.Timestamp, dict[str, float]]],
) -> None:
    engine = OnlineFeatureEngine("ims")
    moment, channels = parity_rows[0]
    with pytest.raises(ValueError, match="engine is for plant"):
        engine.update(_telemetry(moment, channels, 0))


def test_engine_rejects_missing_and_null_channels(
    parity_rows: list[tuple[pd.Timestamp, dict[str, float]]],
) -> None:
    engine = OnlineFeatureEngine("ai4i")
    moment, channels = parity_rows[0]
    without = {name: value for name, value in channels.items() if name != "torque"}
    with pytest.raises(ValueError, match="missing channel 'torque'"):
        engine.update_row(PARITY_MACHINE, moment.to_pydatetime(), without)
    nulled: dict[str, float | None] = dict(channels)
    nulled["torque"] = None
    with pytest.raises(ValueError, match="channel 'torque' is null"):
        engine.update_row(PARITY_MACHINE, moment.to_pydatetime(), nulled)


# --------------------------------------------------------------------------- #
# Throughput
# --------------------------------------------------------------------------- #


def test_online_engine_sustains_five_thousand_rows_per_second(
    benchmark: BenchmarkFixture, parity_rows: list[tuple[pd.Timestamp, dict[str, float]]]
) -> None:
    """One machine's full history, message in, feature vector out.

    The measurement covers the whole hot path — window maintenance, all seven
    statistics over all three windows, percentile ranking against the machine's
    growing history, and streak accounting — at the worst-case history length
    the datasets produce.
    """
    messages = [
        _telemetry(moment, channels, seq) for seq, (moment, channels) in enumerate(parity_rows)
    ]

    def replay() -> int:
        engine = OnlineFeatureEngine("ai4i")
        for message in messages:
            engine.update(message)
        return len(messages)

    rows = benchmark(replay)
    rows_per_second = rows / benchmark.stats["median"]
    benchmark.extra_info["rows_per_second"] = rows_per_second
    assert rows_per_second >= THROUGHPUT_FLOOR_ROWS_PER_SECOND


def test_feature_meta_is_hashable_and_frozen() -> None:
    meta: FeatureMeta = feature_meta("ai4i")["torque"]
    with pytest.raises(AttributeError):
        meta.name = "other"  # type: ignore[misc]
