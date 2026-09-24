import json

import pytest

from services.scan_coach import (
    ScanCoachServiceError,
    _normalise_candidate,
    _normalise_structure,
    detect_image_mime,
    generate_scan_coaching,
)


def _model_answer():
    return (
        "I would first speak with each team member privately so I can understand "
        "their concerns without making assumptions or taking sides. I would then "
        "bring the discussion back to the effect on the group, including workload, "
        "communication, and our shared deadline. If both people were willing, I "
        "would help them agree on a practical division of tasks and a short follow-up "
        "check. I would not try to resolve their personal friendship. However, if "
        "the conflict continued to affect the project or another person’s wellbeing, "
        "I would seek proportionate guidance from the appropriate supervisor. My aim "
        "would be respectful cooperation and a fair, workable outcome."
    )


def _candidate():
    return {
        "visible_prompt_text": (
            "Two friends in your project group have had a personal conflict. "
            "How would you approach this situation?"
        ),
        "recognized_scenario": "Two friends in your project group have had a personal conflict.",
        "recognized_question": "How would you approach this situation?",
        "scan_status": "ready",
        "scenario_source": "visible",
        "document_kind": "prompt",
        "context_required": True,
        "answer_structure": [
            "先直接表态：I would intervene cautiously，但只处理已经影响团队合作的部分。",
            "先分别私下倾听两个人，确认感受与事实，避免一开始就站队或下结论。",
            "再把讨论拉回团队影响，协助他们形成公平、具体而且能够执行的分工方案。",
            "最后说明边界：不强行修复私人关系；只有风险持续时才按比例寻求导师帮助。",
        ],
        "model_answer": _model_answer(),
    }


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"\xff\xd8\xffjpeg", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\npng", "image/png"),
        (b"GIF89aimage", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPimage", "image/webp"),
        (b"not-an-image", None),
    ],
)
def test_image_type_is_detected_from_bytes_not_upload_header(content, expected):
    assert detect_image_mime(content) == expected


def test_scan_candidate_returns_only_recognition_and_coaching_fields():
    result = _normalise_candidate(_candidate(), "vision-test")

    assert result["provider"] == "deepseek"
    assert result["model"] == "vision-test"
    assert result["recognized"]["question"] == "How would you approach this situation?"
    assert result["scan_status"] == "ready"
    assert len(result["answer_structure"]) == 4
    assert 90 <= len(result["model_answer"].split()) <= 120
    assert "score" not in result
    assert "feedback" not in result


def test_unclear_scan_never_guesses_an_answer():
    candidate = _candidate()
    candidate.update(
        {
            "recognized_question": "cropped",
            "scan_status": "cropped_or_blurry",
            "scenario_source": "none",
            "answer_structure": ["This malformed structure is deliberately ignored."],
            "model_answer": "This malformed model answer is deliberately ignored.",
        }
    )

    result = _normalise_candidate(candidate, "vision-test")

    assert result["needs_confirmation"] is True
    assert result["answer_structure"] == []
    assert result["model_answer"] == ""


def test_visible_question_that_refers_to_missing_context_requires_confirmation():
    candidate = _candidate()
    candidate["recognized_scenario"] = ""
    candidate["scenario_source"] = "none"

    result = _normalise_candidate(candidate, "vision-test")

    assert result["needs_confirmation"] is True
    assert result["answer_structure"] == []
    assert result["model_answer"] == ""
    assert result["scan_status"] == "question_only_context_missing"


def test_explicit_scenario_mode_saves_background_without_answering_visible_question():
    candidate = _candidate()

    result = _normalise_candidate(candidate, "vision-test", input_mode="scenario")

    assert result["needs_confirmation"] is True
    assert result["scan_status"] == "scenario_only"
    assert result["recognized"]["question"] == ""
    assert result["recognized"]["scenario"].startswith("Two friends")
    assert result["answer_structure"] == []


def test_short_scenario_only_image_is_treated_as_incomplete():
    candidate = _candidate()
    candidate["recognized_scenario"] = "Too short"
    candidate["recognized_question"] = ""
    candidate["scan_status"] = "scenario_only"

    result = _normalise_candidate(candidate, "vision-test", input_mode="scenario")

    assert result["needs_confirmation"] is True
    assert result["scan_status"] == "cropped_or_blurry"


@pytest.mark.parametrize(
    "structure",
    [
        ["只有两步，而且不够完整。", "第二步也不足以组成完整结构。"],
        ["要点：Listen first", "说明：Clarify", "中文：Act", "结论：Escalate"],
        ["Listen first", "Clarify the issue", "Offer support", "Escalate if needed"],
        [
            "这是中文解释内容 Listen carefully to every stakeholder before making any assumptions about what happened next",
            "这是第二中文说明 Clarify all competing interests and explore every possible option before deciding what to do",
            "这是第三中文说明 Explain a detailed escalation process and all relevant professional boundaries to the interviewer",
        ],
        ["先充分倾听并确认事实和感受。", {"text": "对象不是步骤"}, "最后说明处理边界。"],
        ["先充分倾听并确认事实和感受。"] * 3,
    ],
)
def test_scan_structure_rejects_token_chinese_and_malformed_plans(structure):
    with pytest.raises(ValueError):
        _normalise_structure(structure)


def test_scan_candidate_rejects_dense_or_non_english_reference():
    candidate = _candidate()
    candidate["model_answer"] = "This is much too short to be a useful spoken reference."
    with pytest.raises(ValueError, match="90-120"):
        _normalise_candidate(candidate, "vision-test")

    candidate = _candidate()
    candidate["model_answer"] = _model_answer() + " 我会保持公平。"
    with pytest.raises(ValueError, match="in English"):
        _normalise_candidate(candidate, "vision-test")


def test_scan_request_uses_isolated_vision_config_and_keeps_key_out_of_body(monkeypatch):
    captured = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            body = captured[-1]["body"]
            candidate = _candidate()
            if body["text"]["format"]["name"] == "mmi_scan_answer":
                candidate = {
                    "answer_structure": _candidate()["answer_structure"],
                    "model_answer": _model_answer(),
                }
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(candidate)}
                        ],
                    }
                ],
            }

    def fake_post(url, *, headers, json, timeout):
        captured.append({"url": url, "headers": headers, "body": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "scoring-key-that-should-not-be-used")
    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "scan-only-secret")
    monkeypatch.setenv("SCAN_COACH_BASE_URL", "https://vision.example/responses")
    monkeypatch.setenv("SCAN_COACH_MODEL", "vision-test-model")
    monkeypatch.setenv("SCAN_COACH_TEXT_MODEL", "text-test-model")
    monkeypatch.setenv("SCAN_COACH_REASONING_EFFORT", "none")
    monkeypatch.setattr("services.scan_coach.requests.post", fake_post)

    result = generate_scan_coaching(b"\xff\xd8\xffquestion-image", "image/jpeg")

    assert result["model"] == "text-test-model"
    assert result["vision_model"] == "vision-test-model"
    assert len(captured) == 2
    reading, coaching = captured
    assert reading["url"] == "https://vision.example/responses"
    assert reading["headers"]["Authorization"] == "Bearer scan-only-secret"
    assert "scan-only-secret" not in json.dumps(reading["body"])
    assert reading["body"]["store"] is False
    assert reading["body"]["model"] == "vision-test-model"
    assert reading["body"]["input"][0]["content"][1]["type"] == "input_image"
    assert reading["body"]["input"][0]["content"][1]["detail"] == "original"
    assert reading["body"]["input"][0]["content"][1]["image_url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert "never answer" in reading["body"]["instructions"]
    assert coaching["body"]["model"] == "text-test-model"
    assert len(coaching["body"]["input"][0]["content"]) == 1
    assert "Do not score" in coaching["body"]["instructions"]


def test_question_only_image_uses_page_local_station_context(monkeypatch):
    calls = []
    saved_context = "A student tells you that repeated interruptions make them want to leave a committee."

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            if len(calls) == 1:
                output = {
                    "visible_prompt_text": "What would you say to the student?",
                    "recognized_scenario": "",
                    "recognized_question": "What would you say to the student?",
                    "scan_status": "ready",
                    "scenario_source": "provided",
                    "document_kind": "prompt",
                    "context_required": True,
                }
            else:
                output = {
                    "answer_structure": _candidate()["answer_structure"],
                    "model_answer": _model_answer(),
                }
            return {"status": "completed", "output_text": json.dumps(output)}

    def fake_post(_url, *, headers, json, timeout):
        calls.append({"body": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "scan-only-secret")
    monkeypatch.setattr("services.scan_coach.requests.post", fake_post)

    result = generate_scan_coaching(
        b"\xff\xd8\xffquestion-image",
        "image/jpeg",
        station_context=saved_context,
        previous_questions=["What are the main issues in this scenario?"],
    )

    assert result["scan_status"] == "ready"
    assert result["scenario_source"] == "provided"
    assert result["recognized"]["scenario"] == saved_context
    assert saved_context in calls[0]["body"]["input"][0]["content"][0]["text"]
    assert "What are the main issues" in calls[1]["body"]["input"][0]["content"][0]["text"]


def test_standalone_question_needs_no_saved_scenario(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            if len(calls) == 1:
                output = {
                    "visible_prompt_text": "What are the most important qualities of a good doctor?",
                    "recognized_scenario": "",
                    "recognized_question": "What are the most important qualities of a good doctor?",
                    "scan_status": "ready",
                    "scenario_source": "none",
                    "document_kind": "prompt",
                    "context_required": False,
                }
            else:
                output = {
                    "answer_structure": _candidate()["answer_structure"],
                    "model_answer": _model_answer(),
                }
            return {"status": "completed", "output_text": json.dumps(output)}

    def fake_post(_url, *, headers, json, timeout):
        calls.append({"body": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "scan-only-secret")
    monkeypatch.setattr("services.scan_coach.requests.post", fake_post)

    result = generate_scan_coaching(
        b"\xff\xd8\xffstandalone-question",
        "image/jpeg",
        input_mode="question",
    )

    assert result["scan_status"] == "ready"
    assert result["scenario_source"] == "none"
    assert result["recognized"]["scenario"] == ""
    assert len(calls) == 2


def test_scenario_only_scan_stops_after_reading_stage(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "visible_prompt_text": _candidate()["recognized_scenario"],
                        "recognized_scenario": _candidate()["recognized_scenario"],
                        "recognized_question": "",
                        "scan_status": "scenario_only",
                        "scenario_source": "visible",
                        "document_kind": "prompt",
                        "context_required": False,
                    }
                ),
            }

    def fake_post(*_args, **_kwargs):
        calls.append(_kwargs["json"])
        return FakeResponse()

    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "scan-only-secret")
    monkeypatch.setattr("services.scan_coach.requests.post", fake_post)

    result = generate_scan_coaching(
        b"\x89PNG\r\n\x1a\nscenario",
        "image/png",
        input_mode="scenario",
        station_context="An old station that must not leak into the replacement.",
        previous_questions=["An earlier station question?"],
    )

    assert len(calls) == 1
    reading_context = calls[0]["input"][0]["content"][0]["text"]
    assert '"input_mode_selected_by_user": "scenario"' in reading_context
    assert "old station" not in reading_context
    assert "earlier station" not in reading_context
    assert result["scan_status"] == "scenario_only"
    assert result["recognized"]["question"] == ""
    assert result["answer_structure"] == []


def test_scan_request_rejects_bad_provider_contract_after_one_retry(monkeypatch):
    calls = 0

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"status": "completed", "output_text": "not-json"}

    def fake_post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "scan-only-secret")
    monkeypatch.setattr("services.scan_coach.requests.post", fake_post)

    with pytest.raises(ScanCoachServiceError):
        generate_scan_coaching(b"\x89PNG\r\n\x1a\nquestion", "image/png")
    assert calls == 2


def test_scan_request_rejects_failed_status_even_with_partial_output(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {
                "status": "failed",
                "error": {"message": "provider failure"},
                "output_text": json.dumps(_candidate()),
            }

    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "scan-only-secret")
    monkeypatch.setattr("services.scan_coach.requests.post", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(ScanCoachServiceError):
        generate_scan_coaching(b"\xff\xd8\xffquestion", "image/jpeg")
