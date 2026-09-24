import json
from copy import deepcopy

import pytest

from services.evaluation import (
    _extract_output_text,
    _normalise_deepseek,
    _request_deepseek,
    _response_schema,
)


def _station():
    return {
        "title": "A test station",
        "category": "Teamwork",
        "scenario": "A team is under pressure.",
        "questions": [{"id": f"q{i}", "text": f"Question {i}?"} for i in range(1, 5)],
        "model_answers": ["fallback answer"] * 4,
        "rubric_focus": ["collaboration"],
    }


def _responses():
    return [
        {
            "question_id": f"q{i}",
            "transcript": "I would listen first. I would then agree on a fair plan.",
            "duration_seconds": 45,
        }
        for i in range(1, 5)
    ]


def _model_answer():
    return " ".join(
        [
            "I would begin by listening to the people involved and clarifying what is making the situation difficult.",
            "I would acknowledge their concerns without taking sides, then explain the shared responsibility that the team still needs to meet.",
            "Together, we could agree on a fair division of work and a short check-in point.",
            "If the problem continued to place the project at risk, I would seek proportionate guidance while preserving privacy.",
            "My aim would be respectful cooperation and a workable outcome, not forcing agreement on every personal issue.",
        ]
    )


def _candidate():
    dimensions = {
        "directness": 7,
        "structure": 8,
        "empathy": 8,
        "ethical_reasoning": 6,
        "professionalism": 7,
        "critical_thinking": 6,
        "communication": 8,
    }
    return {
        "summary": "结构清楚。",
        "dimensions": dimensions,
        "next_focus": "进一步减少跨题重复。",
        "repetition": {"detected": False, "message": "没有明显重复。", "repeated_ideas": []},
        "questions": [
            {
                "question_number": index,
                "scores": dimensions,
                "worked": "先听取当事人的观点。",
                "improve": "补充升级阈值。",
                "evidence_ref_ids": [f"q{index}.s01"],
                "next_action": "下一次加入一个条件句。",
                "answer_structure": [
                    "Position：先直接回答本问，例如 I would intervene cautiously，并说明适用条件。",
                    "People：先分别倾听相关者，确认感受和事实，避免过早站队。",
                    "Action：提出一个可执行的方案，并解释它怎样保护团队合作。",
                    "Boundary：如果风险持续影响他人或任务，再按比例寻求帮助。",
                ],
                "model_answer": _model_answer(),
            }
            for index in range(1, 5)
        ],
    }


def test_deepseek_schema_does_not_ask_model_for_overall_score():
    schema = _response_schema(4)
    assert "overall_score" not in schema["properties"]
    assert "overall_score" not in schema["required"]


def test_deepseek_schema_requires_answer_structure_for_each_question():
    question_schema = _response_schema(4)["properties"]["questions"]["items"]
    assert "answer_structure" in question_schema["required"]
    assert question_schema["properties"]["answer_structure"]["minItems"] == 3
    assert question_schema["properties"]["answer_structure"]["maxItems"] == 4


def test_output_extraction_ignores_reasoning_items():
    payload = {
        "output": [
            {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "hidden analysis"}]},
            {"type": "message", "content": [{"type": "output_text", "text": '{"ok": true}'}]},
        ]
    }

    assert _extract_output_text(payload) == '{"ok": true}'


def test_deepseek_evidence_ids_are_resolved_to_exact_transcript_segments():
    evaluation = _normalise_deepseek(_candidate(), _station(), _responses())
    assert evaluation["provider"] == "deepseek"
    assert evaluation["questions"][0]["evidence"] == "I would listen first."
    assert evaluation["questions"][0]["answer_structure"] == _candidate()["questions"][0]["answer_structure"]
    assert 0 <= evaluation["overall_score"] <= 10


def test_token_chinese_labels_fall_back_but_do_not_change_scores_or_model_answer():
    valid = _candidate()
    invalid = deepcopy(valid)
    invalid["questions"][0]["answer_structure"] = [
        "要点：Listen first",
        "说明：Clarify the issue",
        "中文：Offer support",
        "结论：Escalate if needed",
    ]

    valid_evaluation = _normalise_deepseek(valid, _station(), _responses())
    invalid_evaluation = _normalise_deepseek(invalid, _station(), _responses())

    assert invalid_evaluation["questions"][0]["answer_structure"] != invalid["questions"][0]["answer_structure"]
    assert invalid_evaluation["overall_score"] == valid_evaluation["overall_score"]
    assert invalid_evaluation["dimensions"] == valid_evaluation["dimensions"]
    assert invalid_evaluation["questions"][0]["scores"] == valid_evaluation["questions"][0]["scores"]
    assert invalid_evaluation["questions"][0]["model_answer"] == valid_evaluation["questions"][0]["model_answer"]


def test_one_brief_english_interview_phrase_is_allowed_when_chinese_is_substantive():
    candidate = _candidate()
    mixed_structure = [
        "I would first listen to their concern.",
        "接着解释为什么倾听能帮助确认事实，同时降低当事人的防御感。",
        "然后提出一个兼顾公平和任务完成的具体方案，并说明理由。",
        "最后说明只有风险持续影响他人时，才会按比例升级处理。",
    ]
    candidate["questions"][0]["answer_structure"] = mixed_structure

    evaluation = _normalise_deepseek(candidate, _station(), _responses())

    assert evaluation["questions"][0]["answer_structure"] == mixed_structure


@pytest.mark.parametrize(
    "invalid_structure",
    [
        ["只有两步中文解释", "第二步同样不够完整"],
        ["有效中文说明，解释当前立场。", {"text": "对象不能成为步骤"}, "具体行动需要清楚说明。"],
        ["先说明立场并解释适用条件。"] * 3,
    ],
)
def test_malformed_answer_structures_fall_back(invalid_structure):
    candidate = _candidate()
    candidate["questions"][0]["answer_structure"] = invalid_structure
    evaluation = _normalise_deepseek(candidate, _station(), _responses())

    assert evaluation["questions"][0]["answer_structure"] != invalid_structure


def test_invalid_evidence_reference_is_not_exposed_as_a_fake_quote():
    candidate = _candidate()
    candidate["questions"][0]["evidence_ref_ids"] = ["q4.s99"]
    evaluation = _normalise_deepseek(candidate, _station(), _responses())
    assert evaluation["questions"][0]["evidence"] != "q4.s99"
    assert evaluation["questions"][0]["evidence"] in _responses()[0]["transcript"]


def test_shuffled_deepseek_questions_are_rejected():
    candidate = _candidate()
    candidate["questions"][0]["question_number"] = 2

    with pytest.raises(ValueError, match="question order"):
        _normalise_deepseek(candidate, _station(), _responses())


def test_non_object_evaluation_is_rejected():
    with pytest.raises(ValueError, match="must be an object"):
        _normalise_deepseek([], _station(), _responses())


def test_deepseek_request_uses_responses_schema_and_keeps_key_out_of_body(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "completed",
                "output": [{"content": [{"text": json.dumps(_candidate())}]}],
            }

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "body": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-key")
    monkeypatch.setattr("services.evaluation.requests.post", fake_post)
    result = _request_deepseek(_station(), _responses())

    assert result["summary"] == "结构清楚。"
    assert captured["url"] == "https://api.deepseek.com/responses"
    assert captured["body"]["model"] == "deepseek-v4-pro"
    assert captured["body"]["reasoning"] == {"effort": "none"}
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert "tools" not in captured["body"]
    assert "secret-test-key" not in json.dumps(captured["body"])
    assert "q1.s01" in captured["body"]["input"]
