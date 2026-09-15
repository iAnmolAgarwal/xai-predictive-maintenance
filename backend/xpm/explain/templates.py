"""The eight explanation templates and the quantity formatting they use (§3.9).

One template per ``framing`` x ``direction``, verbatim from backend.md §3.9.
They are ``str.format`` strings and nothing else: :func:`render` fills them from
a :class:`~xpm.explain.framing.ClauseFacts`, and :func:`placeholders` exposes the
placeholder set so ``tests/explain/test_templates.py`` can iterate the table and
prove that every combination renders with nothing left unfilled.

``{rate}`` is the one placeholder with a fallback (§3.9, review suggestion 6):
a slope renders as **percent of the window mean per hour** when the window mean
is meaningfully non-zero, and as **absolute channel units per hour** when it is
not. ``features.slope_zero_eps`` decides which, so a zero window mean can never
produce a division by zero, an ``inf`` or a ``nan`` in a user-visible sentence.

Nothing here is a business threshold. The only numbers in this module are
display precisions.
"""

from __future__ import annotations

from string import Formatter
from types import MappingProxyType
from typing import Final

from xpm.contracts.common import Direction, Framing

__all__ = [
    "TEMPLATES",
    "format_hours",
    "format_number",
    "format_ordinal",
    "format_quantity",
    "format_rate",
    "format_window",
    "placeholders",
    "render",
]

#: §3.9's template table. The keys are the full ``framing`` x ``direction``
#: product, so a new framing cannot be added without a sentence for both
#: directions.
TEMPLATES: Final[MappingProxyType[tuple[Framing, Direction], str]] = MappingProxyType(
    {
        ("percentile", "up"): (
            "{display} over the last {window} sat at the {pct} percentile of "
            "this machine's own history ({value})"
        ),
        ("percentile", "down"): (
            "{display} over the last {window} fell to the {pct} percentile of "
            "this machine's own history ({value})"
        ),
        ("consecutive", "up"): (
            "{display} stayed above its {streak_pct}th percentile for {hours} "
            "consecutive hours (peaking at {value})"
        ),
        ("consecutive", "down"): (
            "{display} stayed below its {streak_pct}th percentile for {hours} "
            "consecutive hours (bottoming at {value})"
        ),
        ("trend", "up"): "{display} has been climbing at {rate} over the last {window}",
        ("trend", "down"): "{display} has been falling at {rate} over the last {window}",
        ("threshold", "up"): "{display} reached {value}, above the {threshold} normal ceiling",
        ("threshold", "down"): "{display} dropped to {value}, below the {threshold} normal floor",
    }
)

#: Display precision for a quantity of magnitude >= 1: two decimals, trailing
#: zeros stripped, so 74.10 reads "74.1" and 74.00 reads "74".
_DECIMALS_LARGE: Final[int] = 2
#: Significant digits for a quantity below 1, which is where the vibration band
#: energies live (0.031 g²/Hz).
_SIGNIFICANT_SMALL: Final[int] = 3
#: Above this magnitude a quantity is rendered with thousands separators and no
#: fractional part; torque and rotational speed live here.
_GROUPING_THRESHOLD: Final[float] = 1000.0

#: Unit conversion for :func:`format_window`, not a tunable.
MINUTES_PER_HOUR: Final[float] = 60.0


def placeholders(template: str) -> frozenset[str]:
    """The ``{name}`` placeholders of ``template``."""
    return frozenset(
        field for _, field, _, _ in Formatter().parse(template) if field is not None and field
    )


def render(framing: Framing, direction: Direction, fields: dict[str, str]) -> str:
    """Fill one template, refusing to emit a clause with a missing placeholder.

    ``str.format`` would raise ``KeyError`` for a missing key anyway; the
    explicit check turns that into a message that names the template.
    """
    template = TEMPLATES[framing, direction]
    missing = placeholders(template) - fields.keys()
    if missing:
        raise KeyError(f"{framing}.{direction} template is missing {sorted(missing)}")
    return template.format(**fields)


def format_quantity(value: float, unit: str | None) -> str:
    """A value with its unit, e.g. ``"0.031 g²/Hz"`` or ``"1,538"``."""
    return f"{format_number(value)} {unit}" if unit else format_number(value)


def format_number(value: float) -> str:
    """Round a magnitude for display without ever printing scientific notation."""
    magnitude = abs(value)
    if magnitude >= _GROUPING_THRESHOLD:
        return f"{value:,.0f}"
    if magnitude >= 1.0:
        return f"{value:.{_DECIMALS_LARGE}f}".rstrip("0").rstrip(".")
    if magnitude == 0.0:
        return "0"
    # Three significant digits. Below ~1e-4 this goes exponential, which is
    # both shorter and less error-prone to read than "0.00000146" for the IMS
    # band energies, and is the notation vibration spectra are quoted in.
    return f"{value:.{_SIGNIFICANT_SMALL}g}"


def format_ordinal(value: float) -> str:
    """``96.8`` -> ``"97th"`` — the ``{pct}`` placeholder's rendering."""
    whole = round(value)
    teens = 10 <= whole % 100 <= 20
    suffix = "th" if teens else {1: "st", 2: "nd", 3: "rd"}.get(whole % 10, "th")
    return f"{whole}{suffix}"


def format_hours(hours: float) -> str:
    """``4.0`` -> ``"4"``, ``4.5`` -> ``"4.5"`` — the ``{hours}`` placeholder."""
    return str(int(hours)) if float(hours).is_integer() else f"{hours:.1f}"


def format_window(window_hours: float) -> str:
    """``4`` -> ``"4 hours"`` — the humanised ``{window}`` of §3.9.

    Sub-hour spans are rendered in minutes, which is what a raw channel needs:
    its "window" is one dataset row, ``plants.<id>.row_interval_seconds`` long.
    """
    if window_hours < 1.0:
        minutes = round(window_hours * MINUTES_PER_HOUR)
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    whole = round(window_hours)
    return "1 hour" if whole == 1 else f"{whole} hours"


def format_rate(
    slope_per_hour: float,
    *,
    window_mean: float | None,
    unit: str | None,
    slope_zero_eps: float,
) -> str:
    """``{rate}``: percent of the window mean per hour, or absolute units per hour.

    The relative form is only meaningful when the window mean is a real,
    non-vanishing level, so ``features.slope_zero_eps`` gates it. When the mean
    is zero, missing or too close to zero the absolute form is used instead —
    the case §3.9 calls out and ``test_templates.py`` pins, because dividing by
    a zero mean is exactly how an ``inf`` reaches a user-visible sentence.

    ``unit`` is the feature's own unit, which for a slope feature already ends
    in ``/h`` (see :class:`~xpm.features.registry.FeatureMeta`), so the absolute
    form appends "per hour" only when it does not.
    """
    if window_mean is not None and abs(window_mean) > slope_zero_eps:
        percent = slope_per_hour / abs(window_mean) * 100.0
        return f"{_signed(format_number(percent))}% per hour"
    absolute = _signed(format_number(slope_per_hour))
    if unit is None:
        return f"{absolute} per hour"
    if unit.endswith("/h"):
        return f"{absolute} {unit[:-2]} per hour"
    return f"{absolute} {unit} per hour"


def _signed(rendered: str) -> str:
    """Prefix a rendered number with ``+`` when it is not already signed."""
    return rendered if rendered.startswith("-") else f"+{rendered}"
