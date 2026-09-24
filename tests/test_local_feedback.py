from services.local_feedback import _contains_any, evaluate_locally


def test_local_feedback_rewards_people_first_and_tradeoff_language():
    station = {
        "questions": [{"id": f"q{i}", "text": f"Question {i}"} for i in range(1, 5)],
        "model_answers": ["A concise model answer."] * 4,
        "rubric_focus": ["empathy", "collaboration"],
    }
    responses = [
        {
            "question_id": f"q{i}",
            "transcript": (
                "I would first listen privately and acknowledge how they feel. "
                "I would then balance their needs with the team's responsibility; "
                "however, I would escalate only if the risk continued."
            ),
            "duration_seconds": 50,
        }
        for i in range(1, 5)
    ]

    evaluation = evaluate_locally(station, responses)
    assert evaluation["dimensions"]["empathy"] >= 6
    assert evaluation["dimensions"]["critical_thinking"] >= 6
    assert evaluation["questions"][0]["word_count"] > 20
    assert all(3 <= len(question["answer_structure"]) <= 4 for question in evaluation["questions"])
    assert all(
        any("\u4e00" <= character <= "\u9fff" for character in step)
        for question in evaluation["questions"]
        for step in question["answer_structure"]
    )


def test_empty_answers_score_zero_without_false_repetition():
    station = {
        "questions": [{"id": f"q{i}", "text": f"Question {i}"} for i in range(1, 5)],
        "model_answers": ["A concise model answer."] * 4,
    }
    responses = [
        {"question_id": f"q{i}", "transcript": "", "duration_seconds": 0}
        for i in range(1, 5)
    ]

    evaluation = evaluate_locally(station, responses)

    assert evaluation["overall_score"] == 0
    assert evaluation["repetition"]["detected"] is False
    assert all(
        all(score == 0 for score in question["scores"].values())
        for question in evaluation["questions"]
    )
    assert all(3 <= len(question["answer_structure"]) <= 4 for question in evaluation["questions"])


def test_short_markers_do_not_match_inside_unrelated_words():
    assert _contains_any("This is difficult knowledge.", {"if", "no"}) == 0
    assert _contains_any("If needed, I would say no.", {"if", "no"}) == 2
