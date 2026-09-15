"""Clauses, the composed sentence, its spans, and the alert headline (§3.9).

Three things are produced here and nothing else does prose:

* :func:`clause` renders one feature's §3.9 template into the string stored on
  ``ShapContribution.sentence`` (the waterfall hover tooltip);
* :func:`compose` glues the top ``explanation.max_sentence_features`` clauses
  into the one sentence the dashboard prints, and returns the character spans
  the frontend hyperlinks to the matching waterfall bar (R7);
* :func:`headline` is ``Alert.headline``: clause one, capitalised, full-stopped.

**The caveat is never part of the sentence** (R13): it is carried beside it on
``Explanation.caveat`` / ``WhatIfResponse.caveat`` and rendered as a persistent
footnote. Concatenating it here would make it invisible to the testid the
dashboard asserts on and would let it be truncated with the prose.

**Spans slice the channel display name.** §3.9 fixes ``{display}`` as the
*channel* display name ("Vibration @ 3 kHz"), while
``ShapContribution.display_name`` is the *feature* label the waterfall bar
carries ("Vibration @ 3 kHz — 95th pct over 4 h"). The span therefore covers the
leading segment of ``display_name``, which is what the frontend needs to resolve
a click back to a bar, and
:func:`~xpm.features.registry.FeatureMeta.display_name` guarantees the channel
name is that leading segment.
"""

from __future__ import annotations

from typing import Final

from xpm.contracts.common import Probability
from xpm.contracts.rest import SentenceSpan, ShapContribution
from xpm.contracts.settings import Settings
from xpm.explain.framing import ClauseFacts, direction_from_shap
from xpm.explain.templates import (
    format_hours,
    format_number,
    format_ordinal,
    format_quantity,
    format_rate,
    format_window,
    render,
)

__all__ = ["clause", "compose", "contribution", "headline"]

#: What a clause says when the feature has no reading at all — a window still
#: short of ``features.min_window_coverage``. It is not one of §3.9's eight
#: templates because those all quote a level, and this feature has none; the
#: honest statement is that the bar is drawn without a measured value. Such a
#: clause never enters the composed sentence.
UNAVAILABLE_CLAUSE: Final[str] = (
    "{display} had no reading yet at this moment, so its contribution is shown "
    "without a measured level"
)

#: The one clause outside §3.9's eight. It is rendered when a threshold-framed
#: feature sits **inside** its normal band and has no percentile rank to fall
#: back on — the usual case for a what-if slider parked mid-range. Both §3.9
#: threshold templates would assert a crossing that did not happen, so they are
#: not used; this says what is true instead, in the same shape (display name
#: first, so the sentence spans still work).
IN_BAND_CLAUSE: Final[str] = "{display} sat at {value}, inside its normal {floor}-{ceiling} band"

#: Joins exactly two clauses (§3.9). One clause is terminated with a full stop.
_CLAUSE_JOIN: Final[str] = ", and "


def clause(facts: ClauseFacts, settings: Settings) -> str:
    """Render one feature's §3.9 clause."""
    meta = facts.meta
    if facts.value is None:
        return UNAVAILABLE_CLAUSE.format(display=meta.channel_display_name)

    value = format_quantity(facts.value, meta.unit)
    if facts.band is not None:
        floor, ceiling = facts.band
        return IN_BAND_CLAUSE.format(
            display=meta.channel_display_name,
            value=value,
            floor=format_number(floor),
            ceiling=format_quantity(ceiling, meta.unit),
        )

    fields: dict[str, str] = {
        "display": meta.channel_display_name,
        "value": value,
        "window": format_window(facts.window_hours),
    }
    if facts.percentile is not None:
        fields["pct"] = format_ordinal(facts.percentile)
    if facts.consecutive_hours is not None:
        fields["hours"] = format_hours(facts.consecutive_hours)
    # The consecutive templates spell the "th" themselves, so this one is the
    # bare number: features.streak_percentile is the level the streak counter
    # tests against, never a literal.
    fields["streak_pct"] = str(round(settings.features.streak_percentile))
    if facts.threshold is not None:
        fields["threshold"] = format_quantity(facts.threshold, meta.unit)
    if facts.framing == "trend":
        fields["rate"] = format_rate(
            facts.value,
            window_mean=facts.window_mean,
            unit=meta.unit,
            slope_zero_eps=settings.features.slope_zero_eps,
        )
    return render(facts.framing, facts.direction, fields)


def contribution(facts: ClauseFacts, shap_value: float, settings: Settings) -> ShapContribution:
    """One waterfall bar: the SHAP number, its metadata and its clause.

    ``direction`` is the sign of the contribution — which side of the base value
    the bar sits on — while the clause's own wording follows the evidence
    (:mod:`xpm.explain.framing`). The two agree whenever a feature pushes risk in
    the direction its level suggests, and the bar stays truthful when they do
    not.
    """
    meta = facts.meta
    return ShapContribution(
        feature=meta.name,
        display_name=meta.display_name,
        shap=shap_value,
        value=facts.value,
        unit=meta.unit,
        percentile=facts.percentile,
        window_hours=meta.window_hours,
        stat=meta.stat,
        framing=facts.framing,
        consecutive_hours=facts.consecutive_hours,
        threshold=facts.threshold,
        direction=direction_from_shap(shap_value),
        sentence=clause(facts, settings),
    )


def compose(
    machine_display_name: str,
    probability: Probability,
    contributions: list[ShapContribution],
    settings: Settings,
) -> tuple[str, list[SentenceSpan]]:
    """§3.9's sentence and its spans, from the ranked contributions.

    Only contributions with a measured value can be quoted, so a warm-up feature
    is skipped rather than named without a level. If no contribution has a value
    the sentence states the risk and says plainly that no feature had a reading.
    """
    named = [item for item in contributions if item.value is not None][
        : settings.explanation.max_sentence_features
    ]
    prefix = f"{machine_display_name} was flagged at {probability:.0%} risk"
    if not named:
        return (
            f"{prefix}, but no feature had a measured level at this moment.",
            [],
        )

    head = f"{prefix} because "
    spans: list[SentenceSpan] = []
    parts: list[str] = []
    offset = len(head)
    for position, item in enumerate(named):
        if position:
            offset += len(_CLAUSE_JOIN)
        spans.append(
            SentenceSpan(
                start=offset,
                end=offset + _channel_prefix_length(item),
                feature=item.feature,
            )
        )
        parts.append(item.sentence)
        offset += len(item.sentence)
    return f"{head}{_CLAUSE_JOIN.join(parts)}.", spans


def headline(contributions: list[ShapContribution]) -> str:
    """``Alert.headline``: the first clause, capitalised and full-stopped."""
    if not contributions:
        raise ValueError("an explanation with no contributions has no headline")
    first = contributions[0].sentence
    return f"{first[0].upper()}{first[1:]}."


def _channel_prefix_length(item: ShapContribution) -> int:
    """How much of ``display_name`` the clause opens with.

    Every §3.9 template starts with ``{display}``, the channel display name,
    which :class:`~xpm.features.registry.FeatureMeta` builds ``display_name``
    from by appending the stat and window. The prefix is therefore the part of
    ``display_name`` the clause literally begins with.
    """
    name = item.display_name
    while name and not item.sentence.startswith(name):
        name = name[:-1]
    name = name.rstrip()
    if not name:
        raise ValueError(f"{item.feature}: clause does not start with its display name")
    return len(name)
