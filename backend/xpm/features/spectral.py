"""The spectral side of the feature vector.

Division of labour, per §3.2.2/§3.2.3: the FFT work happens **once, offline**.
``T-DATA``'s ``scripts/fetch_data.py --plant ims`` runs a Welch PSD over each
1.024 s / 20 kHz snapshot and writes the six band-mean PSD channels plus RMS,
kurtosis and crest into ``data/processed/ims/test2.parquet``. By the time a row
reaches this package it is already nine scalar channels, so the rolling engine
treats ``vibration_3khz`` exactly like ``torque`` and ``vibration_3khz_p95_4h``
falls straight out of the grammar in :mod:`xpm.features.registry`. ``ai4i`` has
no vibration channel at all and this module reports an empty band set for it.

What is left for the feature side, and lives here:

* the band table as the *feature* engine sees it — which of a plant's channels
  are band energies, and over which frequencies, so the explanation templater
  can say "at 3 kHz" and mean it;
* :func:`band_energy_share`, the normalised band split used to show that a pure
  tone lands in the band that names it;
* :func:`parseval_ratio`, the consistency check that the band integrals really
  account for the signal's power.

The transform itself is never re-implemented here: every spectral quantity is
delegated to :mod:`xpm.data.bands`, so there is exactly one Welch configuration
in the system.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from xpm.contracts.channels import channels_for
from xpm.contracts.common import PlantId
from xpm.data.bands import band_integrals, band_means, power_spectral_density, snapshot_channels
from xpm.data.schema import IMS_BANDS_HZ
from xpm.features.stats import Float64Array

__all__ = [
    "band_channels",
    "band_edges_hz",
    "band_energy_share",
    "band_mean_psd",
    "dominant_band",
    "parseval_ratio",
    "snapshot_features",
]


def band_channels(plant_id: PlantId) -> tuple[str, ...]:
    """The plant's channels that are band energies, in canonical order.

    Empty for ``ai4i``: the milling dataset has no vibration channel.
    """
    return tuple(channel.name for channel in channels_for(plant_id) if channel.name in IMS_BANDS_HZ)


def band_edges_hz(channel: str) -> tuple[float, float]:
    """The half-open ``[low, high)`` Hz band a band channel covers (§3.2.3)."""
    edges = IMS_BANDS_HZ.get(channel)
    if edges is None:
        raise KeyError(f"{channel!r} is not a band-energy channel")
    return edges


def band_mean_psd(samples: Float64Array) -> dict[str, float]:
    """Band-mean PSD per band, in ``g²/Hz`` — the committed channel values."""
    freqs, psd = power_spectral_density(samples)
    return band_means(freqs, psd)


def snapshot_features(samples: Float64Array) -> dict[str, float]:
    """All nine IMS channels for one bearing snapshot, as the engine ingests them."""
    return snapshot_channels(samples)


def band_energy_share(samples: Float64Array) -> dict[str, float]:
    """Each band's share of the total banded energy, in ``[0, 1]``.

    Computed from the band **integrals** (``g²``), not the band means, because
    the bands have different widths and only the integrals are additive.
    """
    freqs, psd = power_spectral_density(samples)
    integrals = band_integrals(freqs, psd)
    total = sum(integrals.values())
    if total <= 0.0:
        return {name: 0.0 for name in integrals}
    return {name: value / total for name, value in integrals.items()}


def dominant_band(shares: Mapping[str, float]) -> str:
    """The band channel holding the largest share of the energy."""
    if not shares:
        raise ValueError("no bands to choose from")
    return max(shares, key=lambda name: shares[name])


def parseval_ratio(samples: Float64Array) -> float:
    """``∫ PSD df`` over the whole spectrum divided by the signal's mean square.

    Parseval's theorem makes this 1 for an ideal estimator; a Welch PSD with a
    Hann window and 50 % overlap lands close to it, and a gross deviation means
    the PSD normalisation is wrong. Returns ``NaN`` for an all-zero signal,
    whose mean square is zero and whose ratio is undefined.
    """
    freqs, psd = power_spectral_density(samples)
    mean_square = float(np.mean(np.square(samples, dtype=np.float64)))
    if mean_square <= 0.0:
        return float("nan")
    return float(np.trapezoid(psd, freqs)) / mean_square
