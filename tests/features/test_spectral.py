"""Band energies: the synthetic-sine assertions, Parseval, and the golden bands.

The IMS band channels are precomputed per snapshot by ``T-DATA`` (§3.2.3), so
what the feature side owns is the band *table* — which channels are bands and
over which frequencies — plus the two checks that keep the "vibration at 3 kHz"
narrative honest: a pure 3 kHz tone must land in ``vibration_3khz`` and nowhere
else, and the band integrals must account for the signal's power.

``tests/fixtures/features/golden_spectral_bands.json`` is generated from
:mod:`xpm.features.spectral` over the deterministic signals rebuilt by
:func:`_signals` below. Regenerating it is one deliberate command::

    XPM_REGENERATE_GOLDENS=1 uv run pytest tests/features -k golden

This module also reconciles :mod:`xpm.data.schema`'s Welch and IMS acquisition
constants with ``config/settings.yaml``: each side is otherwise pinned to its
own literal, so a matched edit on both would pass every other test in the repo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from xpm.config import get_settings
from xpm.data import bands
from xpm.data.schema import (
    IMS_BANDS_HZ,
    IMS_LABEL_HORIZON_HOURS,
    IMS_NPERSEG,
    IMS_OVERLAP,
    IMS_SAMPLE_RATE_HZ,
    IMS_SNAPSHOT_ROWS,
)
from xpm.features import spectral

GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures" / "features" / "golden_spectral_bands.json"
)

REGENERATE_ENV = "XPM_REGENERATE_GOLDENS"
"""Set this to rewrite the golden instead of asserting against it."""

TONE_ENERGY_SHARE = 0.95
"""A pure tone must put at least this share of its energy in its own band."""

OFF_BAND_ENERGY_SHARE = 0.01
"""...and at most this share in a band it does not belong to."""


def _signals() -> dict[str, np.ndarray]:
    """The deterministic 1.024 s / 20 kHz snapshots the golden was built from."""
    samples = np.arange(IMS_SNAPSHOT_ROWS, dtype=np.float64) / IMS_SAMPLE_RATE_HZ
    generator = np.random.default_rng(20260914)
    return {
        "sine_3khz": np.sin(2 * np.pi * 3000.0 * samples),
        "sine_1khz": np.sin(2 * np.pi * 1000.0 * samples),
        "sine_3khz_in_noise": (
            0.5 * np.sin(2 * np.pi * 3000.0 * samples)
            + generator.normal(scale=0.1, size=IMS_SNAPSHOT_ROWS)
        ),
    }


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return loaded


def _golden_payload() -> dict[str, Any]:
    """The exact fixture body, so the write path and the assert path agree."""
    signals: dict[str, Any] = {}
    for name, signal in _signals().items():
        shares = spectral.band_energy_share(signal)
        signals[name] = {
            "band_mean_psd": spectral.band_mean_psd(signal),
            "band_energy_share": shares,
            "dominant_band": spectral.dominant_band(shares),
            "parseval_ratio": spectral.parseval_ratio(signal),
            "channels": spectral.snapshot_features(signal),
        }
    return {
        "description": (
            "Deterministic synthetic 1.024 s / 20 kHz snapshots run through "
            "xpm.features.spectral. Regenerate with "
            "`XPM_REGENERATE_GOLDENS=1 uv run pytest tests/features -k golden`, "
            "which rewrites this file from "
            "tests/features/test_spectral.py::_golden_payload."
        ),
        "sample_rate_hz": IMS_SAMPLE_RATE_HZ,
        "samples": IMS_SNAPSHOT_ROWS,
        "signals": signals,
    }


def test_ims_acquisition_constants_match_the_settings() -> None:
    """``xpm.data.schema`` and ``plants.ims`` are one table written twice (§3.2)."""
    ims = get_settings().plants.ims
    assert ims.sample_rate_hz == IMS_SAMPLE_RATE_HZ
    assert ims.samples_per_file == IMS_SNAPSHOT_ROWS
    assert ims.welch_nperseg == IMS_NPERSEG
    assert ims.welch_overlap == IMS_OVERLAP
    assert ims.label_horizon_hours == IMS_LABEL_HORIZON_HOURS


def test_the_psd_runs_at_the_configured_resolution() -> None:
    """Behaviour, not signature: the spectrum the bands are cut from.

    A Welch PSD at ``fs`` with ``nperseg`` bins has a bin width of
    ``fs / nperseg`` and tops out at Nyquist, so this pins both settings leaves
    through the transform :mod:`xpm.features.spectral` actually delegates to.
    """
    ims = get_settings().plants.ims
    freqs, psd = bands.power_spectral_density(_signals()["sine_3khz"])
    assert freqs.size == psd.size == ims.welch_nperseg // 2 + 1
    assert float(freqs[1] - freqs[0]) == pytest.approx(ims.sample_rate_hz / ims.welch_nperseg)
    assert float(freqs[-1]) == pytest.approx(ims.sample_rate_hz / 2.0)


def test_only_ims_has_band_channels() -> None:
    """AI4I is a milling dataset: it has no vibration channel at all."""
    assert spectral.band_channels("ai4i") == ()
    assert spectral.band_channels("ims") == tuple(IMS_BANDS_HZ)
    assert len(spectral.band_channels("ims")) == 6


def test_the_three_kilohertz_band_is_centred_on_three_kilohertz() -> None:
    """The band the assignment sentence names (§3.2.3)."""
    assert spectral.band_edges_hz("vibration_3khz") == (2500.0, 3500.0)


def test_band_edges_reject_a_non_band_channel() -> None:
    with pytest.raises(KeyError, match="vibration_rms"):
        spectral.band_edges_hz("vibration_rms")


def test_a_three_kilohertz_tone_lands_in_its_own_band() -> None:
    shares = spectral.band_energy_share(_signals()["sine_3khz"])
    assert shares["vibration_3khz"] >= TONE_ENERGY_SHARE
    assert spectral.dominant_band(shares) == "vibration_3khz"


def test_a_one_kilohertz_tone_stays_out_of_the_three_kilohertz_band() -> None:
    shares = spectral.band_energy_share(_signals()["sine_1khz"])
    assert shares["vibration_3khz"] <= OFF_BAND_ENERGY_SHARE
    assert spectral.dominant_band(shares) == "vibration_1khz"


def test_a_tone_buried_in_noise_still_dominates_its_band() -> None:
    shares = spectral.band_energy_share(_signals()["sine_3khz_in_noise"])
    assert spectral.dominant_band(shares) == "vibration_3khz"


def test_band_energy_shares_sum_to_one() -> None:
    for signal in _signals().values():
        assert sum(spectral.band_energy_share(signal).values()) == pytest.approx(1.0)


def test_a_silent_signal_has_no_band_energy() -> None:
    silence = np.zeros(IMS_SNAPSHOT_ROWS, dtype=np.float64)
    assert set(spectral.band_energy_share(silence).values()) == {0.0}
    assert np.isnan(spectral.parseval_ratio(silence))


def test_parseval_consistency() -> None:
    """``∫ PSD df`` must equal the signal's mean square to within 1 %."""
    for name, signal in _signals().items():
        assert spectral.parseval_ratio(signal) == pytest.approx(1.0, abs=0.01), name


def test_dominant_band_needs_bands() -> None:
    with pytest.raises(ValueError, match="no bands"):
        spectral.dominant_band({})


def test_snapshot_features_produce_every_ims_channel() -> None:
    produced = spectral.snapshot_features(_signals()["sine_3khz"])
    assert set(produced) == set(spectral.band_channels("ims")) | {
        "vibration_rms",
        "vibration_kurtosis",
        "vibration_crest",
    }
    # A unit sine has RMS 1/sqrt(2) and a crest factor of sqrt(2).
    assert produced["vibration_rms"] == pytest.approx(2.0**-0.5, rel=1e-6)
    assert produced["vibration_crest"] == pytest.approx(2.0**0.5, rel=1e-6)


def test_golden_band_energies(golden: dict[str, Any]) -> None:
    if os.environ.get(REGENERATE_ENV):
        GOLDEN.write_text(
            json.dumps(_golden_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        pytest.skip(f"regenerated {GOLDEN.name} from xpm.features.spectral")
    assert golden["sample_rate_hz"] == IMS_SAMPLE_RATE_HZ
    assert golden["samples"] == IMS_SNAPSHOT_ROWS
    signals = _signals()
    assert set(golden["signals"]) == set(signals)
    for name, expected in golden["signals"].items():
        signal = signals[name]
        for channel, value in expected["band_mean_psd"].items():
            assert spectral.band_mean_psd(signal)[channel] == pytest.approx(
                value, rel=1e-9, abs=1e-15
            ), f"{name}.{channel}"
        for channel, value in expected["band_energy_share"].items():
            assert spectral.band_energy_share(signal)[channel] == pytest.approx(
                value, rel=1e-9, abs=1e-15
            ), f"{name}.{channel}"
        for channel, value in expected["channels"].items():
            assert spectral.snapshot_features(signal)[channel] == pytest.approx(
                value, rel=1e-9, abs=1e-15
            ), f"{name}.{channel}"
        assert (
            spectral.dominant_band(spectral.band_energy_share(signal)) == expected["dominant_band"]
        )
        assert spectral.parseval_ratio(signal) == pytest.approx(
            expected["parseval_ratio"], rel=1e-9
        )
