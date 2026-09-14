"""Pin the 16 ``ChannelSpec`` rows of backend.md §3.1, field by field.

The chart-count assertions re-implement the frontend's grouping rule (FE §1.2)
so that editing a ``unit`` string or a ``vibration_like`` flag fails a backend
test before it can move a frontend testid.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from xpm.contracts import ChannelSpec
from xpm.contracts.channels import (
    AI4I_CHANNELS,
    CHANNELS_BY_PLANT,
    IMS_CHANNELS,
    channels_for,
)

# (name, display_name, unit, vibration_like, nominal_min, nominal_max)
AI4I_TABLE: tuple[tuple[str, str, str, bool, float, float], ...] = (
    ("air_temp", "Air Temperature", "K", False, 294.0, 306.0),
    ("process_temp", "Process Temperature", "K", False, 304.0, 315.0),
    ("temp_diff", "Temperature Difference", "K", False, 6.0, 14.0),
    ("rot_speed", "Rotational Speed", "rpm", False, 1100.0, 2900.0),
    ("torque", "Torque", "N·m", False, 0.0, 80.0),
    ("power", "Mechanical Power", "W", False, 2000.0, 14000.0),
    ("tool_wear", "Tool Wear", "min", False, 0.0, 260.0),
)

IMS_TABLE: tuple[tuple[str, str, str, bool, float, float], ...] = (
    ("vibration_0k5khz", "Vibration @ 0.5 kHz", "g²/Hz", True, 0.0, 0.05),
    ("vibration_1khz", "Vibration @ 1 kHz", "g²/Hz", True, 0.0, 0.05),
    ("vibration_2khz", "Vibration @ 2 kHz", "g²/Hz", True, 0.0, 0.02),
    ("vibration_3khz", "Vibration @ 3 kHz", "g²/Hz", True, 0.0, 0.02),
    ("vibration_5khz", "Vibration @ 5 kHz", "g²/Hz", True, 0.0, 0.01),
    ("vibration_8khz", "Vibration @ 8 kHz", "g²/Hz", True, 0.0, 0.01),
    ("vibration_rms", "Vibration RMS", "g", True, 0.0, 2.0),
    ("vibration_kurtosis", "Vibration Kurtosis", "", False, 1.5, 12.0),
    ("vibration_crest", "Vibration Crest Factor", "", False, 2.0, 12.0),
)


def _unit_slug(unit: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", unit.lower()).strip("-")


def _chart_ids(channels: tuple[ChannelSpec, ...]) -> list[str]:
    """Mirror of frontend rule FE §1.2: ``vibration_like`` AND identical ``unit``
    share one chart; a group of size 1 renders as an ordinary per-channel chart.
    """
    groups: dict[str, list[ChannelSpec]] = {}
    for channel in channels:
        if channel.vibration_like:
            groups.setdefault(channel.unit, []).append(channel)
    ids: list[str] = []
    seen: set[str] = set()
    for channel in channels:
        if channel.vibration_like and len(groups[channel.unit]) > 1:
            gid = f"telemetry-chart-group-{_unit_slug(channel.unit)}"
            if gid not in seen:
                seen.add(gid)
                ids.append(gid)
        else:
            ids.append(f"telemetry-chart-{channel.name}")
    return ids


def test_channel_counts() -> None:
    assert len(AI4I_CHANNELS) == 7
    assert len(IMS_CHANNELS) == 9
    assert len(AI4I_CHANNELS) + len(IMS_CHANNELS) == 16


@pytest.mark.parametrize(("plant_id", "table"), [("ai4i", AI4I_TABLE), ("ims", IMS_TABLE)])
def test_rows_match_the_table_field_by_field(
    plant_id: str, table: tuple[tuple[str, str, str, bool, float, float], ...]
) -> None:
    channels = channels_for(plant_id)  # type: ignore[arg-type]
    assert len(channels) == len(table)
    for channel, row in zip(channels, table, strict=True):
        name, display_name, unit, vibration_like, nominal_min, nominal_max = row
        assert channel.name == name
        assert channel.display_name == display_name
        assert channel.unit == unit
        assert channel.vibration_like is vibration_like
        assert channel.nominal_min == nominal_min
        assert channel.nominal_max == nominal_max


def test_canonical_order_is_table_order() -> None:
    assert [c.name for c in AI4I_CHANNELS] == [row[0] for row in AI4I_TABLE]
    assert [c.name for c in IMS_CHANNELS] == [row[0] for row in IMS_TABLE]


def test_exact_unit_characters() -> None:
    torque = next(c for c in AI4I_CHANNELS if c.name == "torque")
    assert torque.unit == "N·m"
    assert "*" not in torque.unit and "." not in torque.unit
    band = next(c for c in IMS_CHANNELS if c.name == "vibration_3khz")
    assert band.unit == "g²/Hz"
    assert band.unit == "g²/Hz"
    assert " " not in band.unit
    assert not band.unit.endswith("·Hz")


def test_dimensionless_channels_use_the_empty_string() -> None:
    for name in ("vibration_kurtosis", "vibration_crest"):
        channel = next(c for c in IMS_CHANNELS if c.name == name)
        assert channel.unit == ""


def test_no_vibration_like_channel_has_an_empty_unit() -> None:
    """What keeps the empty unit out of the frontend's ``unitSlug``."""
    for channels in CHANNELS_BY_PLANT.values():
        for channel in channels:
            if channel.vibration_like:
                assert channel.unit != ""


def test_nominal_bands_are_ordered() -> None:
    for channels in CHANNELS_BY_PLANT.values():
        for channel in channels:
            assert channel.nominal_min < channel.nominal_max


def test_chart_grouping_counts() -> None:
    assert len(_chart_ids(AI4I_CHANNELS)) == 7
    ims_ids = _chart_ids(IMS_CHANNELS)
    assert len(ims_ids) == 4
    assert ims_ids == [
        "telemetry-chart-group-g-hz",
        "telemetry-chart-vibration_rms",
        "telemetry-chart-vibration_kurtosis",
        "telemetry-chart-vibration_crest",
    ]


def test_ai4i_charts_are_all_per_channel() -> None:
    """The three ``K`` channels are not grouped: the rule needs ``vibration_like``."""
    assert _chart_ids(AI4I_CHANNELS) == [f"telemetry-chart-{c.name}" for c in AI4I_CHANNELS]


def test_shared_band_domain() -> None:
    bands = [c for c in IMS_CHANNELS if c.unit == "g²/Hz"]
    assert len(bands) == 6
    assert min(c.nominal_min for c in bands) == 0.0
    assert max(c.nominal_max for c in bands) == 0.05


def test_channels_are_frozen_tuples() -> None:
    assert isinstance(AI4I_CHANNELS, tuple)
    assert isinstance(IMS_CHANNELS, tuple)
    with pytest.raises(TypeError):
        CHANNELS_BY_PLANT["ai4i"] = ()  # type: ignore[index]
    with pytest.raises(ValidationError):
        AI4I_CHANNELS[0].name = "nope"  # type: ignore[misc]


def test_channel_names_are_unique_per_plant() -> None:
    for channels in CHANNELS_BY_PLANT.values():
        names = [c.name for c in channels]
        assert len(names) == len(set(names))
