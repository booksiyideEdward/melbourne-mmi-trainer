import io
import json
import sqlite3


VALID_PNG = b"\x89PNG\r\n\x1a\nquestion-image"


def _table_counts(database):
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("attempts", "responses", "evaluations")
        }


def _result():
    return {
        "provider": "deepseek",
        "model": "deepseek-v4-flash-vision-exp",
        "vision_model": "deepseek-v4-flash-vision-exp",
        "recognized": {
            "scenario": "Two friends in a project group have had a conflict.",
            "question": "How would you approach the situation?",
        },
        "scan_status": "ready",
        "scenario_source": "visible",
        "document_kind": "prompt",
        "needs_confirmation": False,
        "answer_structure": [
            "先直接表态会谨慎介入，但只处理已经影响团队合作的部分。",
            "先分别私下倾听双方，确认感受和事实，并避免过早站队。",
            "再讨论团队受到的影响，协助形成一个公平且具体的行动方案。",
            "最后说明边界，只有风险持续时才按比例寻求导师帮助。",
        ],
        "model_answer": "A complete spoken reference would appear here.",
        "disclaimer": "AI-generated practice reference, not an official Melbourne MMI answer.",
    }


def test_scan_page_loads_only_its_own_assets(client):
    scan_html = client.get("/scan").get_data(as_text=True)
    practice_html = client.get("/").get_data(as_text=True)

    assert '/static/scan/scan.css' in scan_html
    assert '/static/scan/scan.js' in scan_html
    assert '/static/styles.css' not in scan_html
    assert '/static/app.js' not in scan_html
    assert '/static/scan/' not in practice_html
    assert 'id="scan-station-memory"' in scan_html
    assert 'id="scan-conversation"' in scan_html
    assert 'data-scan-mode="scenario"' in scan_html
    assert 'data-scan-mode="question"' in scan_html
    assert "There is no fixed order or question count" in scan_html
    assert "Questions 1–4 in sequence" not in scan_html


def test_scan_endpoint_rejects_missing_empty_and_disguised_uploads(client):
    assert client.post("/api/scan-coach").status_code == 400
    assert (
        client.post(
            "/api/scan-coach",
            data={"image": (io.BytesIO(b""), "empty.png")},
            content_type="multipart/form-data",
        ).status_code
        == 400
    )
    disguised = client.post(
        "/api/scan-coach",
        data={"image": (io.BytesIO(b"plain text"), "fake.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert disguised.status_code == 415


def test_scan_endpoint_has_an_independent_ten_megabyte_limit(client):
    response = client.post(
        "/api/scan-coach",
        data={
            "image": (
                io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)),
                "large.png",
                "image/png",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert "10 MB" in response.get_json()["error"]


def test_scan_endpoint_reports_missing_vision_configuration(client):
    response = client.post(
        "/api/scan-coach",
        data={"image": (io.BytesIO(VALID_PNG), "question.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.get_json()["error"] == "DeepSeek Vision is not configured on this device."


def test_scan_endpoint_rejects_invalid_page_memory(client):
    response = client.post(
        "/api/scan-coach",
        data={
            "image": (io.BytesIO(VALID_PNG), "question.png", "image/png"),
            "previous_questions": "not-json",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "The saved question context is invalid."


def test_scan_endpoint_does_not_assume_a_four_question_station(client, monkeypatch):
    captured = {}

    def fake_scan(*_args, **kwargs):
        captured.update(kwargs)
        return _result()

    monkeypatch.setattr("scan_routes.generate_scan_coaching", fake_scan)
    earlier_questions = [f"Question {number}?" for number in range(1, 7)]
    response = client.post(
        "/api/scan-coach",
        data={
            "image": (io.BytesIO(VALID_PNG), "question.png", "image/png"),
            "input_mode": "question",
            "previous_questions": json.dumps(earlier_questions),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["previous_questions"] == earlier_questions


def test_scan_result_is_not_saved_to_practice_history_or_database(client, app, monkeypatch):
    before_history = client.get("/api/history").get_json()
    before_counts = _table_counts(app.config["DATABASE"])
    captured = {}

    def fake_scan(*_args, **kwargs):
        captured.update(kwargs)
        return _result()

    monkeypatch.setattr("scan_routes.generate_scan_coaching", fake_scan)

    response = client.post(
        "/api/scan-coach",
        data={
            "image": (io.BytesIO(VALID_PNG), "question.png", "image/png"),
            "input_mode": "question",
            "station_context": "A saved station scenario.",
            "previous_questions": '["Question one?"]',
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json() == {"result": _result()}
    assert response.headers["Cache-Control"] == "no-store"
    assert captured == {
        "input_mode": "question",
        "station_context": "A saved station scenario.",
        "previous_questions": ["Question one?"],
    }
    assert client.get("/api/history").get_json() == before_history
    assert _table_counts(app.config["DATABASE"]) == before_counts


def test_scan_endpoint_rejects_unknown_input_mode(client):
    response = client.post(
        "/api/scan-coach",
        data={
            "image": (io.BytesIO(VALID_PNG), "question.png", "image/png"),
            "input_mode": "guess-for-me",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Choose Scenario or Question for this image."
