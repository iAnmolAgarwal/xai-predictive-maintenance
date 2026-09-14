"""The 16 :class:`ChannelSpec` rows of backend.md §3.1, and nothing else.

This module is the **only** place a channel name, display name, unit,
``vibration_like`` flag or nominal band is written down. ``xpm.api`` and
``xpm.data`` import from here; neither re-declares any of it.

Table row order **is** the canonical channel order: every positional
``values[]`` array on the WebSocket is indexed by it, so reordering a row is a
protocol change, not a cosmetic one.

Unit strings are exact characters. ``N·m`` uses U+00B7 MIDDLE DOT; ``g²/Hz``
uses U+00B2 SUPERSCRIPT TWO with an ASCII solidus, no spaces.
``vibration_kurtosis`` and ``vibration_crest`` are dimensionless and carry the
empty string, never ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from xpm.contracts.common import ChannelSpec, PlantId

__all__ = [
    "AI4I_CHANNELS",
    "CHANNELS_BY_PLANT",
    "IMS_CHANNELS",
    "channels_for",
]

#: AI4I 2020 milling plant, 7 channels, canonical order (backend.md §3.1).
AI4I_CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec(
        name="air_temp",
        display_name="Air Temperature",
        unit="K",
        vibration_like=False,
        nominal_min=294.0,
        nominal_max=306.0,
    ),
    ChannelSpec(
        name="process_temp",
        display_name="Process Temperature",
        unit="K",
        vibration_like=False,
        nominal_min=304.0,
        nominal_max=315.0,
    ),
    ChannelSpec(
        name="temp_diff",
        display_name="Temperature Difference",
        unit="K",
        vibration_like=False,
        nominal_min=6.0,
        nominal_max=14.0,
    ),
    ChannelSpec(
        name="rot_speed",
        display_name="Rotational Speed",
        unit="rpm",
        vibration_like=False,
        nominal_min=1100.0,
        nominal_max=2900.0,
    ),
    ChannelSpec(
        name="torque",
        display_name="Torque",
        unit="N·m",
        vibration_like=False,
        nominal_min=0.0,
        nominal_max=80.0,
    ),
    ChannelSpec(
        name="power",
        display_name="Mechanical Power",
        unit="W",
        vibration_like=False,
        nominal_min=2000.0,
        nominal_max=14000.0,
    ),
    ChannelSpec(
        name="tool_wear",
        display_name="Tool Wear",
        unit="min",
        vibration_like=False,
        nominal_min=0.0,
        nominal_max=260.0,
    ),
)

#: NASA IMS bearing plant, 9 channels, canonical order (backend.md §3.1).
IMS_CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec(
        name="vibration_0k5khz",
        display_name="Vibration @ 0.5 kHz",
        unit="g²/Hz",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=0.05,
    ),
    ChannelSpec(
        name="vibration_1khz",
        display_name="Vibration @ 1 kHz",
        unit="g²/Hz",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=0.05,
    ),
    ChannelSpec(
        name="vibration_2khz",
        display_name="Vibration @ 2 kHz",
        unit="g²/Hz",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=0.02,
    ),
    ChannelSpec(
        name="vibration_3khz",
        display_name="Vibration @ 3 kHz",
        unit="g²/Hz",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=0.02,
    ),
    ChannelSpec(
        name="vibration_5khz",
        display_name="Vibration @ 5 kHz",
        unit="g²/Hz",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=0.01,
    ),
    ChannelSpec(
        name="vibration_8khz",
        display_name="Vibration @ 8 kHz",
        unit="g²/Hz",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=0.01,
    ),
    ChannelSpec(
        name="vibration_rms",
        display_name="Vibration RMS",
        unit="g",
        vibration_like=True,
        nominal_min=0.0,
        nominal_max=2.0,
    ),
    ChannelSpec(
        name="vibration_kurtosis",
        display_name="Vibration Kurtosis",
        unit="",
        vibration_like=False,
        nominal_min=1.5,
        nominal_max=12.0,
    ),
    ChannelSpec(
        name="vibration_crest",
        display_name="Vibration Crest Factor",
        unit="",
        vibration_like=False,
        nominal_min=2.0,
        nominal_max=12.0,
    ),
)

CHANNELS_BY_PLANT: Mapping[PlantId, tuple[ChannelSpec, ...]] = MappingProxyType(
    {"ai4i": AI4I_CHANNELS, "ims": IMS_CHANNELS}
)


def channels_for(plant_id: PlantId) -> tuple[ChannelSpec, ...]:
    """Return the canonical, ordered channel tuple for ``plant_id``."""
    return CHANNELS_BY_PLANT[plant_id]
