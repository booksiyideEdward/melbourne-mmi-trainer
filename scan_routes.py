from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request

from services.scan_coach import (
    MAX_PREVIOUS_QUESTIONS,
    MAX_SCAN_IMAGE_BYTES,
    SCAN_INPUT_MODES,
    ScanCoachNotConfigured,
    ScanCoachServiceError,
    detect_image_mime,
    generate_scan_coaching,
)


scan_bp = Blueprint("scan_coach", __name__)


@scan_bp.get("/scan")
def scan_page():
    return render_template("scan.html")


@scan_bp.post("/api/scan-coach")
def scan_coach():
    upload = request.files.get("image")
    if upload is None:
        return jsonify({"error": "Choose one question image first."}), 400

    image_bytes = upload.stream.read(MAX_SCAN_IMAGE_BYTES + 1)
    if not image_bytes:
        return jsonify({"error": "The selected image is empty."}), 400
    if len(image_bytes) > MAX_SCAN_IMAGE_BYTES:
        return jsonify({"error": "The image is too large. Use a file smaller than 10 MB."}), 413

    mime_type = detect_image_mime(image_bytes)
    if mime_type is None:
        return jsonify({"error": "Use a JPEG, PNG, WebP or GIF image."}), 415

    input_mode = str(request.form.get("input_mode") or "question").strip().lower()
    if input_mode not in SCAN_INPUT_MODES:
        return jsonify({"error": "Choose Scenario or Question for this image."}), 400

    station_context = str(request.form.get("station_context") or "").strip()
    if len(station_context) > 6000:
        return jsonify({"error": "The saved station context is too long."}), 400
    try:
        previous_questions = json.loads(request.form.get("previous_questions") or "[]")
    except json.JSONDecodeError:
        return jsonify({"error": "The saved question context is invalid."}), 400
    if (
        not isinstance(previous_questions, list)
        or len(previous_questions) > MAX_PREVIOUS_QUESTIONS
        or any(not isinstance(question, str) or len(question) > 3000 for question in previous_questions)
    ):
        return jsonify({"error": "The saved question context is invalid."}), 400

    try:
        result = generate_scan_coaching(
            image_bytes,
            mime_type,
            input_mode=input_mode,
            station_context=station_context,
            previous_questions=previous_questions,
        )
    except ScanCoachNotConfigured:
        return jsonify({"error": "DeepSeek Vision is not configured on this device."}), 503
    except ScanCoachServiceError:
        return jsonify({"error": "The question could not be analysed. Please try again."}), 502
    except ValueError:
        return jsonify({"error": "The saved station context is invalid."}), 400

    response = jsonify({"result": result})
    response.headers["Cache-Control"] = "no-store"
    return response
