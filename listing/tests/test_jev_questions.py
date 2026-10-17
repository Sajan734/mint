import pytest
from typesafe_sdk import Noul, Score

from jev_questions import CONDITION_QUESTIONS, GATE_QUESTIONS, TASKS, WEAR_LEVELS

ALL = [(task, qid, q) for task, (_, qs) in TASKS.items() for qid, q in qs.items()]


@pytest.mark.parametrize("task, qid, q", ALL, ids=[f"{t}.{i}" for t, i, _ in ALL])
def test_questions_reference_context_and_have_criteria(task, qid, q):
    assert "`context`" in q.instructions
    if isinstance(q, Noul):
        assert q.criteria and q.criteria["true"] and q.criteria["false"]


def test_question_sets():
    assert set(GATE_QUESTIONS) == {"item_usable", "same_category", "same_product"}
    assert set(CONDITION_QUESTIONS) == {
        "item_usable", "scratches_scuffs", "stains_discolouration", "cracks_tears", "missing_broken", "wear",
    }


def test_wear_levels_match_score_criteria():
    wear = CONDITION_QUESTIONS["wear"]
    assert isinstance(wear, Score)
    assert len(wear.criteria) == len(WEAR_LEVELS) == 4
    assert wear.criteria[0].startswith("Like new") and wear.criteria[3].startswith("Heavy wear")
