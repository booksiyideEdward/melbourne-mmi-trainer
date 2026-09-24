import json
from collections import Counter
from pathlib import Path

from app import _balanced_station_order, _normalise_station


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _word_count(text: str) -> int:
    return len(str(text).split())


def test_production_station_bank_has_complete_original_rapid4_content():
    payload = json.loads((PROJECT_ROOT / "data" / "stations.json").read_text(encoding="utf-8"))
    records = payload.get("stations", []) if isinstance(payload, dict) else payload
    stations = [_normalise_station(record) for record in records]

    assert len(stations) >= 30
    assert len({station["id"] for station in stations}) == len(stations)
    assert len({station["category"] for station in stations}) >= 8
    assert all(station["scenario"].strip() for station in stations)
    assert all(len(station["questions"]) == 4 for station in stations)
    assert all(len(station["model_answers"]) == 4 for station in stations)
    assert all(station["source_type"] == "original_ai_reviewed" for station in stations)
    assert all(
        90 <= _word_count(answer) <= 120
        for station in stations
        for answer in station["model_answers"]
    )


def test_hidden_topic_deck_is_even_and_interleaved():
    payload = json.loads((PROJECT_ROOT / "data" / "stations.json").read_text(encoding="utf-8"))
    records = payload.get("stations", []) if isinstance(payload, dict) else payload
    stations = [_normalise_station(record) for record in records]
    ordered = _balanced_station_order(stations)
    categories = [station["category"] for station in ordered]
    counts = Counter(categories)

    assert max(counts.values()) - min(counts.values()) <= 1
    category_count = len(counts)
    for start in range(0, min(counts.values()) * category_count, category_count):
        assert len(set(categories[start : start + category_count])) == category_count
    assert all(left != right for left, right in zip(categories, categories[1:]))
