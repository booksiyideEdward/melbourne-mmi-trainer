import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def sample_stations(tmp_path):
    stations = [
        {
            "id": "teamwork-test",
            "title": "Competing Priorities",
            "category": "Teamwork",
            "difficulty": "Medium",
            "scenario": (
                "Two members of your student project team disagree about how to "
                "divide the remaining work, and the disagreement is affecting the group."
            ),
            "questions": [
                {"id": "teamwork-test-q1", "text": "How would you approach the situation?"},
                {"id": "teamwork-test-q2", "text": "What competing interests would you consider?"},
                {"id": "teamwork-test-q3", "text": "What would you do if one person refused to engage?"},
                {"id": "teamwork-test-q4", "text": "What outcome would you aim for?"},
            ],
            "model_answers": [
                "I would first speak with each person privately, listen without taking sides, and then bring the team together to agree on a fair plan.",
                "I would balance each person's circumstances, the fairness of the workload, and the team's responsibility to submit good work on time.",
                "I would clarify expectations and offer a workable adjustment, then seek guidance if their refusal continued to harm the team.",
                "I would aim for respectful working relationships, a transparent division of tasks, and timely completion without trying to control their friendship.",
            ],
            "rubric_focus": ["empathy", "collaboration", "boundaries", "fairness"],
            "source_type": "original_ai_reviewed",
        }
    ]
    path = tmp_path / "stations.json"
    path.write_text(json.dumps(stations), encoding="utf-8")
    return path


@pytest.fixture()
def app(tmp_path, sample_stations, monkeypatch):
    # Empty values keep tests hermetic even when the developer has configured a
    # real local .env; _load_local_env deliberately does not overwrite them.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("SCAN_COACH_DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "")

    from app import create_app

    application = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.db"),
            "STATIONS_FILE": str(sample_stations),
            "RECORDINGS_DIR": str(tmp_path / "recordings"),
        }
    )
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()
