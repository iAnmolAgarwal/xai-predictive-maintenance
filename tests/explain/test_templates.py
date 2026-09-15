"""§3.9's template table: every framing renders, and it renders the truth.

Two obligations from backend.md §4 live here. Every ``framing`` x ``direction``
must render with no unfilled placeholder — the test iterates the table itself,
so adding a framing without a sentence fails — and the numbers in a clause must
be the numbers on the ``ShapContribution`` it came from, which is the
"sentence matches what is on screen" requirement made mechanical.

The zero-window-mean slope fallback (review suggestion 6) is pinned here too: a
hand-built series with a zero mean and a real slope must render the absolute
form and must never emit ``inf`` or ``nan``.
"""

from __future__ import annotations

import math

import pytest

from xpm.contracts.common import DIRECTIONS, FRAMINGS, Direction, Framing
from xpm.contracts.settings import Settings
from xpm.explain.explainer import Explainer, FeatureSnapshot
from xpm.explain.framing import ClauseFacts, band_for, history_levels, resolve_clause
from xpm.explain.narrative import IN_BAND_CLAUSE, clause, contribution
from xpm.explain.templates import (
    TEMPLATES,
    format_hours,
    format_number,
    format_ordinal,
    format_quantity,
    format_rate,
    format_window,
    placeholders,
    render,
)
from xpm.features.registry import feature_meta

#: One value per placeholder, enough to fill any template in the table.
FIELDS = {
    "display": "Vibration @ 3 kHz",
    "window": "4 hours",
    "pct": "97th",
    "value": "0.031 g²/Hz",
    "streak_pct": "95",
    "hours": "4",
    "rate": "+12% per hour",
    "threshold": "0.02 g²/Hz",
}


def _facts(
    feature: str,
    *,
    value: float,
    percentile: float | None = None,
    streak_hours: float | None = None,
    history_band: tuple[float, float] | None = None,
    window_mean: float | None = None,
    settings: Settings,
    plant_id: str = "ims",
) -> ClauseFacts:
    return resolve_clause(
        feature_meta(plant_id)[feature],  # type: ignore[arg-type]
        value=value,
        percentile=percentile,
        streak_hours=streak_hours,
        history_band=history_band,
        window_mean=window_mean,
        settings=settings,
    )


def test_the_table_covers_every_framing_and_direction() -> None:
    assert set(TEMPLATES) == {
        (framing, direction) for framing in FRAMINGS for direction in DIRECTIONS
    }


@pytest.mark.parametrize("framing", FRAMINGS)
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_every_template_renders_with_no_unfilled_placeholder(
    framing: Framing, direction: Direction
) -> None:
    rendered = render(framing, direction, dict(FIELDS))
    assert "{" not in rendered and "}" not in rendered
    assert rendered.startswith(FIELDS["display"])
    assert placeholders(TEMPLATES[framing, direction]) <= FIELDS.keys()


def test_render_names_the_template_when_a_field_is_missing() -> None:
    with pytest.raises(KeyError, match=r"percentile\.up template is missing"):
        render("percentile", "up", {"display": "Torque"})


def test_percentile_clause_quotes_the_rank_and_the_value(settings: Settings) -> None:
    facts = _facts("vibration_3khz_mean_4h", value=0.031, percentile=96.8, settings=settings)
    item = contribution(facts, 0.25, settings)
    assert item.framing == "percentile"
    assert format_ordinal(96.8) in item.sentence
    assert item.percentile == 96.8
    assert format_quantity(0.031, item.unit) in item.sentence
    assert "4 hours" in item.sentence


def test_consecutive_clause_quotes_the_streak_and_the_streak_percentile(
    settings: Settings,
) -> None:
    facts = _facts(
        "vibration_3khz_p95_4h",
        value=0.031,
        percentile=97.0,
        streak_hours=4.0,
        settings=settings,
    )
    item = contribution(facts, 0.31, settings)
    assert item.framing == "consecutive"
    assert item.consecutive_hours == 4.0
    assert f"for {format_hours(4.0)} consecutive hours" in item.sentence
    assert f"{round(settings.features.streak_percentile)}th percentile" in item.sentence


def test_a_short_streak_does_not_use_the_consecutive_framing(settings: Settings) -> None:
    """``features.streak_min_hours`` decides, not a literal in the templater."""
    below = settings.features.streak_min_hours / 2.0
    facts = _facts(
        "vibration_3khz_p95_4h",
        value=0.031,
        percentile=97.0,
        streak_hours=below,
        settings=settings,
    )
    assert facts.framing == "percentile"


def test_threshold_clause_only_fires_on_a_real_crossing(settings: Settings) -> None:
    meta = feature_meta("ims")["vibration_rms"]
    above = _facts("vibration_rms", value=meta.nominal_max + 1.0, settings=settings)
    assert above.framing == "threshold"
    assert above.direction == "up"
    assert above.threshold == meta.nominal_max
    assert "normal ceiling" in clause(above, settings)

    below = _facts("vibration_rms", value=meta.nominal_min - 1.0, settings=settings)
    assert below.framing == "threshold"
    assert below.direction == "down"
    assert below.threshold == meta.nominal_min
    assert "normal floor" in clause(below, settings)


def test_a_value_inside_its_band_with_no_rank_gets_the_in_band_clause(
    settings: Settings,
) -> None:
    """The one non-§3.9 clause: both threshold templates would be false here."""
    facts = _facts("vibration_rms", value=1.0, settings=settings)
    assert facts.in_band
    rendered = clause(facts, settings)
    assert rendered.startswith(IN_BAND_CLAUSE.split("{display}")[0] + "Vibration RMS")
    assert "inside its normal" in rendered
    assert format_quantity(1.0, "g") in rendered


def test_a_history_band_crossing_is_used_when_there_is_no_rank(settings: Settings) -> None:
    facts = _facts(
        "vibration_rms_std_4h",
        value=0.5,
        history_band=(0.0, 0.1),
        settings=settings,
    )
    assert facts.framing == "threshold"
    assert facts.threshold == 0.1
    assert not facts.in_band


def test_a_rank_beats_the_history_band(settings: Settings) -> None:
    """Quoting the 95th percentile as a ceiling beside a 98th-percentile value
    says the same thing twice; the percentile clause says it once and better."""
    facts = _facts(
        "vibration_rms_std_4h",
        value=0.5,
        percentile=98.0,
        history_band=(0.0, 0.1),
        settings=settings,
    )
    assert facts.framing == "percentile"


def test_band_for_prefers_history_and_rejects_an_inverted_one() -> None:
    meta = feature_meta("ims")["vibration_rms"]
    assert band_for(meta, history_band=(0.1, 0.4)) == (0.1, 0.4)
    assert band_for(meta, history_band=None) == (meta.nominal_min, meta.nominal_max)
    with pytest.raises(ValueError, match="exceeds ceiling"):
        band_for(meta, history_band=(0.4, 0.1))


def test_history_levels_mirror_the_streak_percentile(settings: Settings) -> None:
    low, high = history_levels(settings)
    assert high == settings.features.streak_percentile
    assert low == 100.0 - high


def test_trend_clause_uses_percent_of_the_window_mean(settings: Settings) -> None:
    facts = _facts(
        "vibration_rms_slope_4h",
        value=0.012,
        window_mean=0.1,
        settings=settings,
    )
    item = contribution(facts, 0.1, settings)
    assert item.framing == "trend"
    assert "+12% per hour" in item.sentence
    assert "climbing" in item.sentence


def test_trend_clause_falls_back_to_absolute_units_at_a_zero_window_mean(
    settings: Settings,
) -> None:
    """Review suggestion 6: a zero window mean must not divide by zero."""
    facts = _facts(
        "vibration_3khz_slope_4h",
        value=0.004,
        window_mean=0.0,
        settings=settings,
    )
    rendered = clause(facts, settings)
    assert "%" not in rendered
    assert "+0.004 g²/Hz per hour" in rendered
    assert "inf" not in rendered and "nan" not in rendered


def test_the_rate_fallback_is_driven_by_slope_zero_eps(settings: Settings) -> None:
    eps = settings.features.slope_zero_eps
    absolute = format_rate(1.0, window_mean=eps / 2.0, unit="g/h", slope_zero_eps=eps)
    relative = format_rate(1.0, window_mean=1.0, unit="g/h", slope_zero_eps=eps)
    assert "per hour" in absolute and "%" not in absolute
    assert "%" in relative
    missing = format_rate(1.0, window_mean=None, unit=None, slope_zero_eps=eps)
    assert missing == "+1 per hour"
    plain = format_rate(-1.0, window_mean=None, unit="g", slope_zero_eps=eps)
    assert plain == "-1 g per hour"
    for rendered in (absolute, relative, missing, plain):
        assert math.isfinite(float(rendered.split()[0].rstrip("%")))


def test_a_falling_slope_reads_as_falling(settings: Settings) -> None:
    facts = _facts(
        "vibration_rms_slope_4h",
        value=-0.012,
        window_mean=0.1,
        settings=settings,
    )
    assert facts.direction == "down"
    assert "falling at -12% per hour" in clause(facts, settings)


def test_a_feature_with_no_value_has_no_framing_claim(settings: Settings) -> None:
    facts = resolve_clause(
        feature_meta("ims")["vibration_rms_mean_4h"],
        value=None,
        percentile=None,
        streak_hours=None,
        history_band=None,
        window_mean=None,
        settings=settings,
    )
    assert not facts.renderable
    assert "no reading" in clause(facts, settings)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0"),
        (0.031, "0.031"),
        (1.46e-06, "1.46e-06"),
        (74.0, "74"),
        (74.1, "74.1"),
        (1538.2, "1,538"),
        (-0.5, "-0.5"),
    ],
)
def test_number_formatting(value: float, expected: str) -> None:
    assert format_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (96.8, "97th")],
)
def test_ordinal_formatting(value: float, expected: str) -> None:
    assert format_ordinal(value) == expected


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(1.0, "1 hour"), (4.0, "4 hours"), (24.0, "24 hours"), (5.0 / 60.0, "5 minutes")],
)
def test_window_formatting(hours: float, expected: str) -> None:
    assert format_window(hours) == expected


def test_a_one_minute_window_reads_singular() -> None:
    assert format_window(1.0 / 60.0) == "1 minute"


def test_quantity_formatting_drops_an_empty_unit() -> None:
    assert format_quantity(12.0, None) == "12"
    assert format_quantity(12.0, "g") == "12 g"


def test_hours_formatting() -> None:
    assert format_hours(4.0) == "4"
    assert format_hours(4.5) == "4.5"


def test_a_raw_channel_names_one_dataset_row_as_its_window(settings: Settings) -> None:
    """§3.9's ``{window}`` for a raw channel is ``plants.<id>.row_interval_seconds``."""
    facts = _facts("vibration_rms", value=1.0, percentile=99.0, settings=settings)
    assert facts.framing == "percentile"
    minutes = settings.plants.ims.row_interval_seconds / 60
    assert f"over the last {minutes:.0f} minutes" in clause(facts, settings)


def test_every_contribution_of_a_real_explanation_quotes_its_own_fields(
    ims_lgbm: Explainer, ims_snapshot: FeatureSnapshot, settings: Settings
) -> None:
    """The graded requirement: the sentence matches the numbers on screen."""
    explanation = ims_lgbm.explain(
        ims_snapshot, alert_id="alt_0123456789abcdef", machine_display_name="Bearing 1"
    )
    for item in explanation.contributions:
        assert item.value is not None
        assert format_quantity(item.value, item.unit) in item.sentence
        if item.framing == "percentile":
            assert item.percentile is not None
            assert format_ordinal(item.percentile) in item.sentence
        if item.framing == "consecutive":
            assert item.consecutive_hours is not None
            assert format_hours(item.consecutive_hours) in item.sentence
        if item.framing == "threshold" and item.threshold is not None:
            assert format_quantity(item.threshold, item.unit) in item.sentence


def test_a_hand_built_snapshot_renders_the_assignment_sentence(settings: Settings) -> None:
    """The assignment's own sentence, from real metadata and real numbers."""
    facts = resolve_clause(
        feature_meta("ims")["vibration_3khz_p95_4h"],
        value=0.031,
        percentile=97.0,
        streak_hours=4.0,
        history_band=(0.0, 0.02),
        window_mean=None,
        settings=settings,
    )
    rendered = clause(facts, settings)
    assert rendered == (
        "Vibration @ 3 kHz stayed above its 95th percentile for 4 consecutive "
        "hours (peaking at 0.031 g²/Hz)"
    )
