import io
import json
import sqlite3
from pathlib import Path

from app import _audio_extension, _normalise_station


def _responses(texts=None):
    texts = texts or [
        "I would first listen to each teammate privately and acknowledge how they feel before proposing a fair plan.",
        "I would balance individual circumstances with the team's shared responsibility and explain that trade-off clearly.",
        "If they still refused, I would clarify expectations, offer support, and escalate only if the project remained at risk.",
        "I would aim for respectful cooperation, a transparent workload, and timely completion without forcing a friendship outcome.",
    ]
    return [
        {
            "question_id": f"teamwork-test-q{index + 1}",
            "transcript": text,
            "duration_seconds": 48 + index,
            "audio_mime_type": "audio/webm;codecs=opus",
        }
        for index, text in enumerate(texts)
    ]


def test_config_exposes_verified_rapid_profile(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    config = response.get_json()

    rapid = config["modes"]["rapid4"]
    assert rapid == {
        "label": "Melbourne 2026 detailed · Rapid 4",
        "scenario_seconds": 60,
        "question_count": 4,
        "prep_seconds": 15,
        "answer_seconds": 60,
        "question_visible_during_answer": False,
    }
    assert config["providers"]["deepseek"] is False
    assert config["providers"]["deepgram"] is False


def test_security_headers_keep_browser_uploads_local(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]


def test_both_review_surfaces_include_original_scenario_slots(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="review-scenario-text"' in html
    assert 'id="result-scenario-text"' in html
    assert html.count("Original scenario") == 2


def test_local_subscription_sandbox_grants_mmi_without_touching_production(client):
    response = client.get("/api/sandbox/billing/status")
    assert response.status_code == 200
    assert response.get_json() == {
        "sandbox": True,
        "subscribed": True,
        "products": ["mmi"],
        "endsAt": None,
    }


def test_station_listing_exposes_only_neutral_practice_content(client):
    response = client.get("/api/stations")
    assert response.status_code == 200
    station = response.get_json()["stations"][0]
    assert station["id"].startswith("mmi_")
    assert station["number"] == 1
    assert len(station["questions"]) == 4
    assert set(station) == {"id", "number", "scenario", "questions"}
    assert all(set(question) == {"id", "text"} for question in station["questions"])


def test_browser_facing_station_ids_can_save_an_attempt(client):
    station = client.get("/api/stations").get_json()["stations"][0]
    responses = [
        {
            "question_id": question["id"],
            "transcript": f"Answer {index + 1}",
            "duration_seconds": 45,
        }
        for index, question in enumerate(station["questions"])
    ]
    created = client.post(
        "/api/attempts",
        json={"station_id": station["id"], "mode": "rapid4", "responses": responses},
    )
    assert created.status_code == 201


def test_attempt_can_be_saved_listed_and_deleted(client):
    created = client.post(
        "/api/attempts",
        json={
            "station_id": "teamwork-test",
            "mode": "rapid4",
            "coaching_mode": "guided",
            "strict_mode": False,
            "started_at": "2026-09-06T09:00:00Z",
            "responses": _responses(),
        },
    )
    assert created.status_code == 201
    attempt_id = created.get_json()["attempt_id"]

    history = client.get("/api/history").get_json()["attempts"]
    assert len(history) == 1
    assert history[0]["id"] == attempt_id
    assert history[0]["station_number"] == 1
    assert history[0]["station_id"].startswith("mmi_")
    assert history[0]["scenario"].startswith("Two members of your student project team")
    assert "station_title" not in history[0]
    assert "category" not in history[0]
    assert history[0]["coaching_mode"] == "guided"
    assert len(history[0]["responses"]) == 4

    deleted = client.delete(f"/api/attempts/{attempt_id}")
    assert deleted.status_code == 200
    assert client.get("/api/history").get_json()["attempts"] == []


def test_saved_evaluation_is_available_in_history(client):
    created = client.post(
        "/api/attempts",
        json={
            "station_id": "teamwork-test",
            "mode": "rapid4",
            "responses": _responses(),
        },
    ).get_json()
    evaluated = client.post(
        "/api/evaluate",
        json={
            "attempt_id": created["attempt_id"],
            "station_id": "teamwork-test",
            "responses": _responses(),
        },
    )
    assert evaluated.status_code == 200

    saved = client.get("/api/history").get_json()["attempts"][0]
    assert saved["evaluation"]["provider"] == "local"
    assert len(saved["evaluation"]["questions"]) == 4
    assert all(
        3 <= len(question["answer_structure"]) <= 4
        for question in saved["evaluation"]["questions"]
    )
    assert saved["responses"][0]["question_text"] == "How would you approach the situation?"


def test_history_keeps_question_snapshot_when_station_bank_changes(client, sample_stations):
    created = client.post(
        "/api/attempts",
        json={
            "station_id": "teamwork-test",
            "mode": "rapid4",
            "responses": _responses(),
        },
    )
    assert created.status_code == 201

    bank = json.loads(sample_stations.read_text(encoding="utf-8"))
    original_text = bank[0]["questions"][0]["text"]
    original_scenario = bank[0]["scenario"]
    bank[0]["questions"][0]["text"] = "A replacement question added after the attempt."
    bank[0]["scenario"] = "A replacement scenario added after the attempt."
    sample_stations.write_text(json.dumps(bank), encoding="utf-8")

    saved = client.get("/api/history").get_json()["attempts"][0]
    assert saved["responses"][0]["question_text"] == original_text
    assert saved["scenario"] == original_scenario

    sample_stations.write_text("[]", encoding="utf-8")
    saved_without_bank = client.get("/api/history").get_json()["attempts"][0]
    assert saved_without_bank["scenario"] == original_scenario
    assert saved_without_bank["station_number"] == 1


def test_existing_database_adds_snapshot_column_and_legacy_rows_use_current_bank(
    tmp_path, sample_stations, monkeypatch
):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE attempts (
            id TEXT PRIMARY KEY,
            station_id TEXT NOT NULL,
            station_title TEXT NOT NULL,
            category TEXT NOT NULL,
            mode TEXT NOT NULL,
            coaching_mode TEXT NOT NULL DEFAULT 'simulation',
            strict_mode INTEGER NOT NULL DEFAULT 0,
            started_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id TEXT NOT NULL,
            question_index INTEGER NOT NULL,
            transcript TEXT NOT NULL DEFAULT '',
            duration_seconds REAL NOT NULL DEFAULT 0,
            audio_mime_type TEXT,
            audio_id TEXT
        );
        INSERT INTO attempts (
            id, station_id, station_title, category, mode, coaching_mode,
            strict_mode, started_at, created_at
        ) VALUES (
            'legacy-attempt', 'teamwork-test', 'Competing Priorities', 'Teamwork',
            'rapid4', 'simulation', 0, NULL, '2026-09-01T00:00:00Z'
        );
        INSERT INTO responses (
            attempt_id, question_id, question_index, transcript, duration_seconds
        ) VALUES (
            'legacy-attempt', 'teamwork-test-q1', 0, 'A legacy response.', 42
        );
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    from app import create_app

    legacy_app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database),
            "STATIONS_FILE": str(sample_stations),
            "RECORDINGS_DIR": str(tmp_path / "recordings"),
        }
    )

    with sqlite3.connect(database) as migrated:
        response_columns = {row[1] for row in migrated.execute("PRAGMA table_info(responses)")}
        attempt_columns = {row[1] for row in migrated.execute("PRAGMA table_info(attempts)")}
        snapshot = migrated.execute(
            "SELECT station_scenario, station_number FROM attempts WHERE id = 'legacy-attempt'"
        ).fetchone()
    assert "question_text" in response_columns
    assert "station_scenario" in attempt_columns
    assert "station_number" in attempt_columns
    assert snapshot[0].startswith("Two members of your student project team")
    assert snapshot[1] == 1

    history = legacy_app.test_client().get("/api/history").get_json()["attempts"]
    assert history[0]["responses"][0]["question_text"] == "How would you approach the situation?"
    assert history[0]["scenario"].startswith("Two members of your student project team")


def test_evaluation_falls_back_locally_and_returns_coaching_schema(client):
    response = client.post(
        "/api/evaluate",
        json={
            "station_id": "teamwork-test",
            "mode": "rapid4",
            "responses": _responses(),
        },
    )
    assert response.status_code == 200
    evaluation = response.get_json()["evaluation"]

    assert evaluation["provider"] == "local"
    assert evaluation["disclaimer"]
    assert 0 <= evaluation["overall_score"] <= 10
    assert len(evaluation["questions"]) == 4
    assert evaluation["next_focus"]
    assert "dimensions" in evaluation
    assert "repetition" in evaluation
    assert all(question["model_answer"] for question in evaluation["questions"])
    assert all(3 <= len(question["answer_structure"]) <= 4 for question in evaluation["questions"])


def test_repeated_answers_are_flagged(client):
    repeated = "I would talk privately, protect the deadline, and ask the instructor for help."
    response = client.post(
        "/api/evaluate",
        json={
            "station_id": "teamwork-test",
            "mode": "rapid4",
            "responses": _responses([repeated] * 4),
        },
    )
    evaluation = response.get_json()["evaluation"]
    assert evaluation["repetition"]["detected"] is True
    assert evaluation["repetition"]["max_similarity"] >= 0.9


def test_transcription_without_provider_returns_manual_fallback(client, app):
    response = client.post(
        "/api/transcribe",
        data={
            "question_id": "teamwork-test-q1",
            "audio": (io.BytesIO(b"not-real-audio"), "answer.webm", "audio/webm"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider"] == "manual"
    assert payload["transcript"] == ""
    assert payload["audio_id"]
    recording = Path(app.config["RECORDINGS_DIR"]) / f"{payload['audio_id']}.webm"
    assert recording.exists()

    deleted = client.delete(f"/api/recordings/{payload['audio_id']}")
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True
    assert not recording.exists()


def test_transcription_with_deepgram_returns_editable_transcript(client, monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": {
                    "channels": [
                        {"alternatives": [{"transcript": "I would listen before proposing a plan."}]}
                    ]
                }
            }

    def fake_post(endpoint, *, params, headers, data, timeout):
        captured.update(
            {
                "endpoint": endpoint,
                "params": params,
                "content_type": headers["Content-Type"],
                "audio": data.read(),
                "timeout": timeout,
            }
        )
        assert headers["Authorization"] == "Token test-deepgram-key"
        return FakeResponse()

    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-deepgram-key")
    monkeypatch.setattr("services.transcription.requests.post", fake_post)

    response = client.post(
        "/api/transcribe",
        data={
            "question_id": "teamwork-test-q1",
            "audio": (io.BytesIO(b"browser-audio"), "answer.webm", "audio/webm;codecs=opus"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider"] == "deepgram"
    assert payload["transcript"] == "I would listen before proposing a plan."
    assert payload["warning"] is None
    assert payload["audio_id"]
    assert captured == {
        "endpoint": "https://api.deepgram.com/v1/listen",
        "params": {
            "model": "nova-3",
            "language": "en-AU",
            "smart_format": "true",
            "punctuate": "true",
        },
        "content_type": "audio/webm",
        "audio": b"browser-audio",
        "timeout": (5, 70),
    }


def test_invalid_attempt_payload_is_rejected(client):
    response = client.post(
        "/api/attempts",
        json={"station_id": "teamwork-test", "mode": "rapid4", "responses": []},
    )
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_non_object_json_payload_is_rejected(client):
    assert client.post("/api/attempts", json=[]).status_code == 400
    assert client.post("/api/evaluate", json=[]).status_code == 400


def test_station_id_is_stable_when_authored_record_omits_one():
    raw = {
        "title": "An Authored Station",
        "scenario": "A candidate must make a balanced decision.",
        "questions": ["What would you do?"],
    }
    first = _normalise_station(raw)
    second = _normalise_station(raw)

    assert first["id"] == second["id"]
    assert first["id"].startswith("an-authored-station-")
    assert first["questions"][0]["id"] == f"{first['id']}-q1"


def test_browser_codec_parameters_are_accepted_for_supported_audio():
    assert _audio_extension("audio/mp4;codecs=mp4a.40.2") == ".mp4"
    assert _audio_extension("audio/webm;codecs=opus") == ".webm"
    assert _audio_extension("text/plain") is None
