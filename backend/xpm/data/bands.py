"""Welch band energies and time-domain shape statistics for IMS vibration.

Parameters are §3.2.3's: Welch PSD with a Hann window, ``nperseg=4096``, 50 %
overlap, ``fs = 20 kHz``. Each band channel carries the **band-mean PSD** --
the integral of the PSD over the band divided by that band's width in Hz --
which is what makes six bands of different widths comparable on one shared
y-axis and what makes the unit ``g²/Hz``.
"""

from __future__ import annotations

from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.signal import welch

from xpm.data.schema import (
    IMS_BANDS_HZ,
    IMS_NPERSEG,
    IMS_OVERLAP,
    IMS_SAMPLE_RATE_HZ,
    IMS_WINDOW,
)

Float64Array = NDArray[np.float64]


def power_spectral_density(
    samples: Float64Array,
    *,
    fs: float = IMS_SAMPLE_RATE_HZ,
    nperseg: int = IMS_NPERSEG,
    overlap: float = IMS_OVERLAP,
    window: str = IMS_WINDOW,
) -> tuple[Float64Array, Float64Array]:
    """Welch PSD of a 1-D acceleration signal in g; returns ``(freqs, psd)``."""
    if samples.ndim != 1:
        raise ValueError(f"expected a 1-D signal, got shape {samples.shape}")
    segment = min(nperseg, samples.size)
    freqs, psd = welch(
        samples.astype(np.float64, copy=False),
        fs=fs,
        window=window,
        nperseg=segment,
        noverlap=int(segment * overlap),
        detrend=False,
    )
    return cast(Float64Array, np.asarray(freqs, dtype=np.float64)), cast(
        Float64Array, np.asarray(psd, dtype=np.float64)
    )


def _band_mask(freqs: Float64Array, low: float, high: float, nyquist: float) -> Float64Array:
    """Half-open ``[low, high)`` bins, closing the final band at Nyquist."""
    mask = (freqs >= low) & (freqs < high)
    if high >= nyquist:
        mask = mask | (freqs == high)
    return cast(Float64Array, mask)


def band_integrals(freqs: Float64Array, psd: Float64Array) -> dict[str, float]:
    """``∫ PSD dHz`` over each §3.2.3 band, in ``g²``."""
    nyquist = float(freqs[-1])
    out: dict[str, float] = {}
    for name, (low, high) in IMS_BANDS_HZ.items():
        mask = _band_mask(freqs, low, high, nyquist)
        selected = psd[mask]
        if selected.size < 2:
            out[name] = 0.0
            continue
        out[name] = float(np.trapezoid(selected, freqs[mask]))
    return out


def band_means(freqs: Float64Array, psd: Float64Array) -> dict[str, float]:
    """Band-mean PSD per band, in ``g²/Hz`` (the committed channel values)."""
    integrals = band_integrals(freqs, psd)
    return {name: integrals[name] / (high - low) for name, (low, high) in IMS_BANDS_HZ.items()}


def rms(samples: Float64Array) -> float:
    """Root-mean-square acceleration in g."""
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def kurtosis(samples: Float64Array) -> float:
    """Pearson (non-Fisher) kurtosis; 3.0 for a Gaussian signal."""
    centred = samples - float(np.mean(samples))
    variance = float(np.mean(np.square(centred)))
    if variance == 0.0:
        return 0.0
    return float(np.mean(centred**4) / variance**2)


def crest_factor(samples: Float64Array) -> float:
    """Peak-to-RMS ratio, dimensionless."""
    value = rms(samples)
    if value == 0.0:
        return 0.0
    return float(np.max(np.abs(samples)) / value)


def snapshot_channels(samples: Float64Array) -> dict[str, float]:
    """The nine IMS channels (§3.1) for one bearing's 1.024 s snapshot."""
    freqs, psd = power_spectral_density(samples)
    channels = band_means(freqs, psd)
    channels["vibration_rms"] = rms(samples)
    channels["vibration_kurtosis"] = kurtosis(samples)
    channels["vibration_crest"] = crest_factor(samples)
    return channels


def snapshot_matrix_channels(matrix: Float64Array) -> list[dict[str, float]]:
    """Per-column channel dictionaries for a ``(samples, bearings)`` snapshot."""
    if matrix.ndim != 2:
        raise ValueError(f"expected a 2-D snapshot, got shape {matrix.shape}")
    return [snapshot_channels(np.ascontiguousarray(matrix[:, i])) for i in range(matrix.shape[1])]
