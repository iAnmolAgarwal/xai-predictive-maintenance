"""The composed sentence, its spans, the headline and the caveat (§3.9, R13).

``sentence_spans`` is the frontend's hyperlink contract (R7): every span must
slice out of ``sentence`` and the slice must identify the contribution it names,
so a click on the prose can resolve to a waterfall bar without parsing the
string.

The span covers the **channel** display name, which §3.9 fixes as ``{display}``
and which :class:`~xpm.features.registry.FeatureMeta` guarantees is the leading
segment of ``ShapContribution.display_name`` — asserted here both ways.
"""

from __future__ import annotations

import pytest

from xpm.contracts.rest import Explanation, ShapContribution
from xpm.contracts.settings import Settings
from xpm.explain.explainer import Explainer, FeatureSnapshot
from xpm.explain.narrative import compose, headline


def _explain(explainer: Explainer, snapshot: FeatureSnapshot, display: str) -> Explanation:
    return explainer.explain(
        snapshot, alert_id="alt_0123456789abcdef", machine_display_name=display
    )


@pytest.fixture(params=["ai4i", "ims"])
def explanation(request: pytest.FixtureRequest) -> Explanation:
    plant_id = request.param
    explainer: Explainer = request.getfixturevalue(f"{plant_id}_lgbm")
    snapshot: FeatureSnapshot = request.getfixturevalue(f"{plant_id}_snapshot")
    return _explain(explainer, snapshot, "Machine 1")


def test_every_span_slices_out_its_features_display_name(explanation: Explanation) -> None:
    by_feature = {item.feature: item for item in explanation.contributions}
    assert explanation.sentence_spans
    for span in explanation.sentence_spans:
        sliced = explanation.sentence[span.start : span.end]
        assert sliced, "a span must select something"
        item = by_feature[span.feature]
        assert item.display_name.startswith(sliced)
        assert sliced in item.sentence
        assert item.sentence.startswith(sliced)


def test_spans_are_ordered_disjoint_and_inside_the_sentence(explanation: Explanation) -> None:
    end = 0
    for span in explanation.sentence_spans:
        assert 0 <= span.start < span.end <= len(explanation.sentence)
        assert span.start >= end
        end = span.end


def test_the_sentence_names_at_most_the_configured_number_of_features(
    explanation: Explanation, settings: Settings
) -> None:
    assert len(explanation.sentence_spans) <= settings.explanation.max_sentence_features
    assert explanation.sentence.endswith(".")
    assert "because" in explanation.sentence


def test_the_sentence_quotes_the_probability_the_explanation_carries(
    explanation: Explanation,
) -> None:
    assert f"{explanation.probability:.0%} risk" in explanation.sentence


def test_the_caveat_is_carried_beside_the_sentence_never_inside_it(
    explanation: Explanation, settings: Settings
) -> None:
    """R13: required, and never concatenated into the prose."""
    assert explanation.caveat.strip()
    assert explanation.caveat == settings.explanation.caveat
    assert explanation.caveat not in explanation.sentence
    assert explanation.caveat.split(".")[0] not in explanation.sentence


def test_headline_is_the_first_clause_capitalised(explanation: Explanation) -> None:
    line = headline(list(explanation.contributions))
    first = explanation.contributions[0].sentence
    assert line == f"{first[0].upper()}{first[1:]}."
    assert line.endswith(".")
    assert line[0].isupper()


def test_headline_refuses_an_empty_contribution_list() -> None:
    with pytest.raises(ValueError, match="no contributions"):
        headline([])


def test_one_clause_is_joined_with_a_full_stop(
    explanation: Explanation, settings: Settings
) -> None:
    sentence, spans = compose("Machine 1", 0.74, list(explanation.contributions[:1]), settings)
    assert ", and " not in sentence
    assert sentence.endswith(".")
    assert len(spans) == 1
    assert sentence[spans[0].start : spans[0].end] in explanation.contributions[0].display_name


def test_two_clauses_are_joined_with_and(explanation: Explanation, settings: Settings) -> None:
    sentence, spans = compose("Machine 1", 0.74, list(explanation.contributions[:2]), settings)
    assert sentence.count(", and ") == 1
    assert len(spans) == 2
    assert sentence[spans[1].start : spans[1].end] in explanation.contributions[1].display_name


def test_a_sentence_with_nothing_measurable_says_so(
    explanation: Explanation, settings: Settings
) -> None:
    blank = [item.model_copy(update={"value": None}) for item in explanation.contributions[:1]]
    sentence, spans = compose("Machine 1", 0.74, blank, settings)
    assert spans == []
    assert "no feature had a measured level" in sentence


def test_a_clause_that_does_not_start_with_its_display_name_is_refused(
    explanation: Explanation, settings: Settings
) -> None:
    """The span contract is enforced, not assumed."""
    broken = explanation.contributions[0].model_copy(update={"sentence": "Something else"})
    with pytest.raises(ValueError, match="does not start with its display name"):
        compose("Machine 1", 0.74, [broken], settings)


def test_contribution_direction_is_the_sign_of_the_bar(explanation: Explanation) -> None:
    for item in explanation.contributions:
        assert item.direction == ("up" if item.shap >= 0 else "down")


def test_contributions_are_contract_models(explanation: Explanation) -> None:
    assert all(isinstance(item, ShapContribution) for item in explanation.contributions)
