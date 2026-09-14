"""Welch band energies: golden values on real data, plus analytic sanity checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from xpm.data import bands
from xpm.data.schema import (
    IMS_BANDS_HZ,
    IMS_CHANNELS,
    IMS_SAMPLE_RATE_HZ,
    IMS_SNAPSHOT_ROWS,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "data"


@pytest.fixture(scope="module")
def snapshot() -> bands.Float64Array:
    """One real 20 480 x 4 snapshot copied out of the IMS test-2 tree."""
    matrix: bands.Float64Array = np.load(FIXTURES / "ims_raw_snippet_20480.npy")
    return matrix


@pytest.fixture(scope="module")
def expected() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FIXTURES / "ims_bands_expected.json").read_text(encoding="utf-8")
    )
    return loaded


def test_snapshot_fixture_has_the_documented_shape(snapshot: bands.Float64Array) -> None:
    assert snapshot.shape == (IMS_SNAPSHOT_ROWS, 4)


def test_channels_match_the_golden_values(
    snapshot: bands.Float64Array, expected: dict[str, Any]
) -> None:
    computed = bands.snapshot_matrix_channels(snapshot)
    assert len(computed) == 4
    for index, channels in enumerate(computed, start=1):
        golden = expected["bearings"][str(index)]
        assert tuple(channels) == IMS_CHANNELS
        for name, value in channels.items():
            assert value == pytest.approx(golden[name], rel=1e-9), f"bearing {index} {name}"


def _sine(frequency: float, amplitude: float = 1.0) -> bands.Float64Array:
    time = np.arange(IMS_SNAPSHOT_ROWS, dtype=np.float64) / IMS_SAMPLE_RATE_HZ
    signal: bands.Float64Array = amplitude * np.sin(2.0 * np.pi * frequency * time)
    return signal


def test_a_3khz_sine_lands_in_the_3khz_band() -> None:
    freqs, psd = bands.power_spectral_density(_sine(3000.0))
    integrals = bands.band_integrals(freqs, psd)
    total = sum(integrals.values())
    assert integrals["vibration_3khz"] / total >= 0.95


def test_a_1khz_sine_stays_out_of_the_3khz_band() -> None:
    freqs, psd = bands.power_spectral_density(_sine(1000.0))
    integrals = bands.band_integrals(freqs, psd)
    total = sum(integrals.values())
    assert integrals["vibration_1khz"] / total >= 0.95
    assert integrals["vibration_3khz"] / total <= 0.01


def test_band_mean_is_the_integral_divided_by_the_band_width() -> None:
    freqs, psd = bands.power_spectral_density(_sine(3000.0))
    integrals = bands.band_integrals(freqs, psd)
    means = bands.band_means(freqs, psd)
    for name, (low, high) in IMS_BANDS_HZ.items():
        assert means[name] == pytest.approx(integrals[name] / (high - low))


def test_sine_has_the_analytic_rms_kurtosis_and_crest() -> None:
    signal = _sine(3000.0, amplitude=2.0)
    assert bands.rms(signal) == pytest.approx(2.0 / np.sqrt(2.0), rel=1e-6)
    assert bands.kurtosis(signal) == pytest.approx(1.5, rel=1e-6)
    assert bands.crest_factor(signal) == pytest.approx(np.sqrt(2.0), rel=1e-6)


def test_constant_signal_degenerates_safely() -> None:
    zeros: bands.Float64Array = np.zeros(1024, dtype=np.float64)
    assert bands.kurtosis(zeros) == 0.0
    assert bands.crest_factor(zeros) == 0.0
    assert bands.rms(zeros) == 0.0


def test_narrow_band_with_too_few_bins_is_zero() -> None:
    freqs: bands.Float64Array = np.array([0.0, 5000.0, 8000.0, 10000.0], dtype=np.float64)
    psd: bands.Float64Array = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float64)
    integrals = bands.band_integrals(freqs, psd)
    # 0-500 Hz holds a single bin, so there is nothing to integrate over.
    assert integrals["vibration_0k5khz"] == 0.0
    # 6000-10000 Hz holds two bins, and the Nyquist bin closes the final band.
    assert integrals["vibration_8khz"] == pytest.approx(2000.0)


def test_psd_rejects_a_non_1d_signal(snapshot: bands.Float64Array) -> None:
    with pytest.raises(ValueError, match="1-D signal"):
        bands.power_spectral_density(snapshot)


def test_matrix_channels_rejects_a_1d_snapshot() -> None:
    with pytest.raises(ValueError, match="2-D snapshot"):
        bands.snapshot_matrix_channels(np.zeros(16, dtype=np.float64))
