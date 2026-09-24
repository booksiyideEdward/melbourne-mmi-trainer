from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, current_app, g, jsonify, render_template, request

from scan_routes import scan_bp
from services.evaluation import evaluate_responses
from services.transcription import transcribe_audio


BASE_DIR = Path(__file__).resolve().parent
ALLOWED_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def _stable_station_id(raw: dict[str, Any]) -> str:
    """Return a readable, deterministic ID when authored data omits one."""

    explicit = str(raw.get("id") or raw.get("station_id") or "").strip()
    if explicit:
        return explicit
    title = str(raw.get("title") or raw.get("name") or "untitled-station").strip()
    scenario = str(raw.get("scenario") or raw.get("prompt") or "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "station"
    digest = hashlib.sha256(f"{title}\n{scenario}".encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def _public_station_id(station_id: str) -> str:
    """Return an opaque, stable browser-facing ID.

    Authored station IDs can contain descriptive title words. Keeping those IDs on
    the server prevents the browser payload from accidentally hinting at a theme.
    """

    digest = hashlib.sha256(f"melbourne-mmi-public-v1\n{station_id}".encode("utf-8")).hexdigest()[:16]
    return f"mmi_{digest}"


def _balanced_station_order(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave hidden categories in a deterministic round-robin deck."""

    buckets: dict[str, list[dict[str, Any]]] = {}
    for station in stations:
        key = str(station.get("category") or "General").strip().casefold()
        buckets.setdefault(key, []).append(station)

    def stable_key(value: str) -> str:
        return hashlib.sha256(f"melbourne-mmi-balanced-v1\n{value}".encode("utf-8")).hexdigest()

    category_order = sorted(buckets, key=stable_key)
    for category in category_order:
        buckets[category].sort(key=lambda station: stable_key(str(station["id"])))

    ordered: list[dict[str, Any]] = []
    round_index = 0
    while True:
        added = False
        for category in category_order:
            bucket = buckets[category]
            if round_index < len(bucket):
                ordered.append(bucket[round_index])
                added = True
        if not added:
            return ordered
        round_index += 1


def _audio_extension(mime_type: str) -> str | None:
    """Accept browser codec parameters while validating the base media type."""

    normalised = str(mime_type or "").strip().lower()
    return ALLOWED_AUDIO_TYPES.get(normalised) or ALLOWED_AUDIO_TYPES.get(normalised.split(";", 1)[0])


def _delete_recording_files(recordings_dir: str | Path, audio_id: str) -> int:
    if re.fullmatch(r"[a-f0-9]{32}", str(audio_id or "")) is None:
        return 0
    root = Path(recordings_dir).resolve()
    deleted = 0
    for extension in set(ALLOWED_AUDIO_TYPES.values()):
        candidate = (root / f"{audio_id}{extension}").resolve()
        if candidate.parent == root and candidate.exists():
            candidate.unlink()
            deleted += 1
    return deleted


SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL,
    station_title TEXT NOT NULL,
    category TEXT NOT NULL,
    station_scenario TEXT,
    station_number INTEGER,
    mode TEXT NOT NULL,
    coaching_mode TEXT NOT NULL DEFAULT 'simulation',
    strict_mode INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    question_index INTEGER NOT NULL,
    question_text TEXT,
    transcript TEXT NOT NULL DEFAULT '',
    duration_seconds REAL NOT NULL DEFAULT 0,
    audio_mime_type TEXT,
    audio_id TEXT
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    overall_score REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_station_id ON attempts(station_id);
CREATE INDEX IF NOT EXISTS idx_responses_attempt_id ON responses(attempt_id);
"""


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise_station(raw: dict[str, Any]) -> dict[str, Any]:
    station_id = _stable_station_id(raw)
    questions = []
    for index, question in enumerate(raw.get("questions", [])):
        if isinstance(question, dict):
            question_id = str(question.get("id") or f"{station_id}-q{index + 1}")
            text = str(question.get("text") or question.get("prompt") or "")
        else:
            question_id = f"{station_id}-q{index + 1}"
            text = str(question)
        questions.append({"id": question_id, "text": text})

    model_answers = raw.get("model_answers", [])
    if isinstance(model_answers, dict):
        model_answers = [str(model_answers.get(question["id"], "")) for question in questions]

    return {
        "id": station_id,
        "title": str(raw.get("title") or "Untitled station"),
        "category": str(raw.get("category") or raw.get("theme") or "General"),
        "difficulty": str(raw.get("difficulty") or "Medium"),
        "scenario": str(raw.get("scenario") or raw.get("prompt") or ""),
        "questions": questions,
        "model_answers": [str(answer) for answer in model_answers],
        "rubric_focus": list(raw.get("rubric_focus", [])),
        "source_type": str(raw.get("source_type") or "original_ai_reviewed"),
    }


def _stations() -> list[dict[str, Any]]:
    path = Path(current_app.config["STATIONS_FILE"])
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("stations", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("stations.json must contain a list or a {stations: []} object")
    normalised = [_normalise_station(record) for record in records if isinstance(record, dict)]
    return _balanced_station_order(normalised)


def _station_by_id(station_id: str) -> dict[str, Any] | None:
    return next(
        (
            station
            for station in _stations()
            if station["id"] == station_id or _public_station_id(station["id"]) == station_id
        ),
        None,
    )


def _public_station(station: dict[str, Any], number: int) -> dict[str, Any]:
    public_id = _public_station_id(station["id"])
    return {
        "id": public_id,
        "number": number,
        "scenario": station["scenario"],
        "questions": [
            {"id": f"{public_id}-q{index + 1}", "text": question["text"]}
            for index, question in enumerate(station["questions"])
        ],
    }


def _db() -> sqlite3.Connection:
    if "db" not in g:
        database = Path(current_app.config["DATABASE"])
        database.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(database)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def _init_db(app: Flask) -> None:
    with app.app_context():
        connection = _db()
        connection.executescript(SCHEMA)
        attempt_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(attempts)").fetchall()
        }
        if "coaching_mode" not in attempt_columns:
            connection.execute(
                "ALTER TABLE attempts ADD COLUMN coaching_mode TEXT NOT NULL DEFAULT 'simulation'"
            )
        if "station_scenario" not in attempt_columns:
            connection.execute("ALTER TABLE attempts ADD COLUMN station_scenario TEXT")
        if "station_number" not in attempt_columns:
            connection.execute("ALTER TABLE attempts ADD COLUMN station_number INTEGER")
        response_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(responses)").fetchall()
        }
        if "question_text" not in response_columns:
            # Existing attempts predate prompt snapshots. Keeping this nullable lets
            # history distinguish legacy rows from newly saved (possibly blank) prompts.
            connection.execute("ALTER TABLE responses ADD COLUMN question_text TEXT")
        for station_number, station in enumerate(_stations(), start=1):
            connection.execute(
                """
                UPDATE attempts
                SET station_scenario = COALESCE(station_scenario, ?),
                    station_number = COALESCE(station_number, ?)
                WHERE station_id = ?
                """,
                (station["scenario"], station_number, station["id"]),
            )
        connection.execute("PRAGMA optimize")
        connection.commit()


def _validate_responses(station: dict[str, Any], raw_responses: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(raw_responses, list) or len(raw_responses) != len(station["questions"]):
        return None, f"Exactly {len(station['questions'])} responses are required."

    expected_ids = [question["id"] for question in station["questions"]]
    public_station_id = _public_station_id(station["id"])
    expected_public_ids = [f"{public_station_id}-q{index + 1}" for index in range(len(expected_ids))]
    responses = []
    for index, raw in enumerate(raw_responses):
        if not isinstance(raw, dict):
            return None, f"Response {index + 1} must be an object."
        question_id = str(raw.get("question_id") or "")
        if question_id not in {expected_ids[index], expected_public_ids[index]}:
            return None, "Response question IDs must match the station in order."
        transcript = str(raw.get("transcript") or "")
        if len(transcript) > 10000:
            return None, f"Response {index + 1} is too long."
        try:
            duration = float(raw.get("duration_seconds", 0) or 0)
        except (TypeError, ValueError):
            return None, f"Response {index + 1} has an invalid duration."
        if duration < 0 or duration > 180:
            return None, f"Response {index + 1} has an invalid duration."
        responses.append(
            {
                "question_id": expected_ids[index],
                "transcript": transcript.strip(),
                "duration_seconds": duration,
                "audio_mime_type": str(raw.get("audio_mime_type") or "")[:100],
                "audio_id": str(raw.get("audio_id") or "")[:100] or None,
            }
        )
    return responses, None


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    _load_local_env(BASE_DIR / ".env")
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"), instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=str(BASE_DIR / "instance" / "mmi.db"),
        STATIONS_FILE=str(BASE_DIR / "data" / "stations.json"),
        RECORDINGS_DIR=str(BASE_DIR / "instance" / "recordings"),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["RECORDINGS_DIR"]).mkdir(parents=True, exist_ok=True)
    _init_db(app)
    app.register_blueprint(scan_bp)

    @app.teardown_appcontext
    def close_db(_error: BaseException | None = None) -> None:
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "media-src 'self' blob:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        return response

    @app.errorhandler(413)
    def too_large(_error):
        if request.path == "/api/scan-coach":
            return jsonify({"error": "The image is too large. Use a file smaller than 10 MB."}), 413
        return jsonify({"error": "Audio file is too large (maximum 12 MB)."}), 413

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/config")
    def config():
        return jsonify(
            {
                "modes": {
                    "rapid4": {
                        "label": "Melbourne 2026 detailed · Rapid 4",
                        "scenario_seconds": 60,
                        "question_count": 4,
                        "prep_seconds": 15,
                        "answer_seconds": 60,
                        "question_visible_during_answer": False,
                    },
                    "official2027": {
                        "label": "Melbourne 2027 · Official-known profile",
                        "station_seconds": 300,
                        "question_count": "several",
                        "timing_note": "The current official guide does not publish per-question timing.",
                    },
                },
                "providers": {
                    "deepseek": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
                    "deepgram": bool(os.getenv("DEEPGRAM_API_KEY", "").strip()),
                },
                "disclaimer": "Practice coaching only; not an official University of Melbourne score.",
            }
        )

    @app.get("/api/sandbox/billing/status")
    def sandbox_billing_status():
        return jsonify(
            {
                "sandbox": True,
                "subscribed": True,
                "products": ["mmi"],
                "endsAt": None,
            }
        )

    @app.get("/api/stations")
    def list_stations():
        records = _stations()
        return jsonify(
            {
                "stations": [
                    _public_station(record, number)
                    for number, record in enumerate(records, start=1)
                ]
            }
        )

    @app.get("/api/stations/<station_id>")
    def get_station(station_id: str):
        station = _station_by_id(station_id)
        if station is None:
            return jsonify({"error": "Station not found."}), 404
        number = next(
            index
            for index, record in enumerate(_stations(), start=1)
            if record["id"] == station["id"]
        )
        return jsonify({"station": _public_station(station, number)})

    @app.post("/api/transcribe")
    def transcribe():
        upload = request.files.get("audio")
        if upload is None:
            return jsonify({"error": "An audio file is required."}), 400
        mime_type = (upload.mimetype or request.form.get("mime_type") or "").lower()
        extension = _audio_extension(mime_type)
        if extension is None:
            return jsonify({"error": f"Unsupported audio type: {mime_type or 'unknown'}"}), 415

        audio_id = uuid.uuid4().hex
        path = Path(app.config["RECORDINGS_DIR"]) / f"{audio_id}{extension}"
        upload.save(path)
        result = transcribe_audio(path, mime_type)
        return jsonify({"audio_id": audio_id, **result})

    @app.post("/api/attempts")
    def save_attempt():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body must be an object."}), 400
        station = _station_by_id(str(payload.get("station_id") or ""))
        if station is None:
            return jsonify({"error": "Station not found."}), 404
        responses, error = _validate_responses(station, payload.get("responses"))
        if error:
            return jsonify({"error": error}), 400

        mode = str(payload.get("mode") or "rapid4")
        if mode not in {"rapid4", "official2027"}:
            return jsonify({"error": "Unsupported practice mode."}), 400
        coaching_mode = str(payload.get("coaching_mode") or "simulation")
        if coaching_mode not in {"simulation", "guided"}:
            return jsonify({"error": "Unsupported coaching mode."}), 400
        attempt_id = f"att_{uuid.uuid4().hex}"
        station_number = next(
            number
            for number, record in enumerate(_stations(), start=1)
            if record["id"] == station["id"]
        )
        connection = _db()
        connection.execute(
            """
            INSERT INTO attempts (
                id, station_id, station_title, category, station_scenario,
                station_number, mode, coaching_mode, strict_mode, started_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                station["id"],
                station["title"],
                station["category"],
                station["scenario"],
                station_number,
                mode,
                coaching_mode,
                int(bool(payload.get("strict_mode"))),
                str(payload.get("started_at") or "")[:100] or None,
                _utc_now(),
            ),
        )
        for index, response in enumerate(responses or []):
            connection.execute(
                """
                INSERT INTO responses (
                    attempt_id, question_id, question_index, question_text, transcript,
                    duration_seconds, audio_mime_type, audio_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    response["question_id"],
                    index,
                    station["questions"][index]["text"],
                    response["transcript"],
                    response["duration_seconds"],
                    response["audio_mime_type"],
                    response["audio_id"],
                ),
            )
        connection.commit()
        return jsonify({"attempt_id": attempt_id, "attempt": {"id": attempt_id}}), 201

    @app.post("/api/evaluate")
    def evaluate():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body must be an object."}), 400
        station = _station_by_id(str(payload.get("station_id") or ""))
        if station is None:
            return jsonify({"error": "Station not found."}), 404
        responses, error = _validate_responses(station, payload.get("responses"))
        if error:
            return jsonify({"error": error}), 400

        attempt_id = str(payload.get("attempt_id") or "")
        connection = None
        if attempt_id:
            connection = _db()
            attempt = connection.execute(
                "SELECT station_id FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                return jsonify({"error": "Attempt not found."}), 404
            if attempt["station_id"] != station["id"]:
                return jsonify({"error": "Attempt and station do not match."}), 400

        evaluation = evaluate_responses(station, responses or [])
        if attempt_id and connection is not None:
            connection.execute(
                """
                INSERT INTO evaluations (
                    attempt_id, provider, model, rubric_version,
                    overall_score, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    rubric_version = excluded.rubric_version,
                    overall_score = excluded.overall_score,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    attempt_id,
                    evaluation.get("provider", "local"),
                    evaluation.get("model", "unknown"),
                    evaluation.get("rubric_version", "melbourne-coaching-v1"),
                    evaluation.get("overall_score", 0),
                    json.dumps(evaluation, ensure_ascii=False),
                    _utc_now(),
                ),
            )
            connection.commit()
        return jsonify({"evaluation": evaluation})

    @app.get("/api/history")
    def history():
        connection = _db()
        rows = connection.execute(
            """
            SELECT a.*, e.overall_score, e.provider AS evaluation_provider,
                   e.payload_json AS evaluation_payload,
                   (SELECT COUNT(*) FROM responses r WHERE r.attempt_id = a.id) AS response_count
            FROM attempts a
            LEFT JOIN evaluations e ON e.attempt_id = a.id
            ORDER BY a.created_at DESC
            LIMIT 100
            """
        ).fetchall()
        stations = _stations()
        station_map = {station["id"]: station for station in stations}
        station_number_map = {
            station["id"]: number for number, station in enumerate(stations, start=1)
        }
        attempts = []
        for row in rows:
            station = station_map.get(row["station_id"])
            question_map = {
                question["id"]: question["text"]
                for question in (station or {}).get("questions", [])
            }
            response_rows = connection.execute(
                """
                SELECT question_id, question_index, question_text, transcript, duration_seconds,
                       audio_mime_type, audio_id
                FROM responses
                WHERE attempt_id = ?
                ORDER BY question_index
                """,
                (row["id"],),
            ).fetchall()
            evaluation = None
            if row["evaluation_payload"]:
                try:
                    evaluation = json.loads(row["evaluation_payload"])
                except (TypeError, json.JSONDecodeError):
                    evaluation = None
            attempts.append(
                {
                    "id": row["id"],
                    "station_id": _public_station_id(row["station_id"]),
                    "station_number": row["station_number"] or station_number_map.get(row["station_id"]),
                    "scenario": (
                        row["station_scenario"]
                        or (station or {}).get("scenario")
                        or "Scenario unavailable for this older practice."
                    ),
                    "mode": row["mode"],
                    "coaching_mode": row["coaching_mode"],
                    "strict_mode": bool(row["strict_mode"]),
                    "created_at": row["created_at"],
                    "overall_score": row["overall_score"],
                    "evaluation_provider": row["evaluation_provider"],
                    "response_count": row["response_count"],
                    "responses": [
                        {
                            "question_id": f"{_public_station_id(row['station_id'])}-q{index + 1}",
                            "question_text": (
                                response["question_text"]
                                if response["question_text"] is not None
                                else question_map.get(response["question_id"])
                                or f"Question {index + 1}"
                            ),
                            "transcript": response["transcript"],
                            "duration_seconds": response["duration_seconds"],
                            "audio_mime_type": response["audio_mime_type"],
                            "audio_id": response["audio_id"],
                        }
                        for index, response in enumerate(response_rows)
                    ],
                    "evaluation": evaluation,
                }
            )
        return jsonify(
            {
                "attempts": attempts
            }
        )

    @app.delete("/api/recordings/<audio_id>")
    def delete_unattached_recording(audio_id: str):
        if re.fullmatch(r"[a-f0-9]{32}", audio_id) is None:
            return jsonify({"error": "Invalid recording ID."}), 400
        attached = _db().execute(
            "SELECT 1 FROM responses WHERE audio_id = ? LIMIT 1", (audio_id,)
        ).fetchone()
        if attached is not None:
            return jsonify({"error": "Recording belongs to a saved attempt."}), 409
        deleted = _delete_recording_files(app.config["RECORDINGS_DIR"], audio_id)
        return jsonify({"deleted": bool(deleted), "audio_id": audio_id})

    @app.delete("/api/attempts/<attempt_id>")
    def delete_attempt(attempt_id: str):
        connection = _db()
        rows = connection.execute(
            "SELECT audio_id, audio_mime_type FROM responses WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchall()
        deleted = connection.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,)).rowcount
        connection.commit()
        if not deleted:
            return jsonify({"error": "Attempt not found."}), 404

        for row in rows:
            audio_id = row["audio_id"]
            if not audio_id:
                continue
            still_referenced = connection.execute(
                "SELECT 1 FROM responses WHERE audio_id = ? LIMIT 1", (audio_id,)
            ).fetchone()
            if still_referenced is None:
                _delete_recording_files(app.config["RECORDINGS_DIR"], audio_id)
        return jsonify({"deleted": True, "attempt_id": attempt_id})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8765")), debug=False)
