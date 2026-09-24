(() => {
  "use strict";

  const API = {
    stations: "/api/stations",
    attempts: "/api/attempts",
    transcribe: "/api/transcribe",
    evaluate: "/api/evaluate",
    history: "/api/history",
    config: "/api/config",
    recordings: "/api/recordings",
  };

  const PHASE_SECONDS = Object.freeze({ scenario: 60, prep: 15, recording: 60 });
  const TIMER_CIRCUMFERENCE = 2 * Math.PI * 59;
  const SCORE_CIRCUMFERENCE = 2 * Math.PI * 62;
  const viewIds = [
    "setup-view",
    "mic-view",
    "session-view",
    "review-view",
    "evaluation-loading-view",
    "results-view",
    "history-view",
  ];

  const state = {
    stations: [],
    filteredStations: [],
    selectedStationId: null,
    selectedStation: null,
    mode: "simulation",
    strictMode: false,
    phase: "setup",
    currentQuestionIndex: 0,
    responses: [],
    stream: null,
    audioContext: null,
    analyserFrame: 0,
    micReady: false,
    micDetectedSound: false,
    textOnly: false,
    mimeType: "",
    recorder: null,
    recorderStoppedPromise: null,
    recordingStartedAt: 0,
    finishingRecording: false,
    deadlineTimer: null,
    transcriptionPromises: new Map(),
    sessionStartedAt: null,
    attemptId: null,
    evaluation: null,
    history: [],
    pendingExitAction: null,
    sessionGeneration: 0,
    evaluationGeneration: 0,
    micRequestGeneration: 0,
    abandonedByPageHide: false,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function escapeHTML(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, Number(value) || 0));
  }

  function asText(value, fallback = "") {
    if (Array.isArray(value)) return value.filter(Boolean).join("; ");
    if (value && typeof value === "object") {
      return value.summary || value.text || value.feedback || value.message || fallback;
    }
    return value === null || value === undefined ? fallback : String(value);
  }

  function getMode() {
    return $("input[name='session-mode']:checked")?.value || "simulation";
  }

  function dimensionLabel(value) {
    const key = String(value || "").toLowerCase();
    return (
      {
        directness: "Directness & relevance",
        structure: "Structure",
        empathy: "Empathy",
        ethical_reasoning: "Ethical reasoning",
        professionalism: "Professional judgement",
        critical_thinking: "Critical thinking",
        communication: "Communication",
        delivery: "Timed delivery",
        completion: "Completion",
      }[key] || String(value || "Dimension").replaceAll("_", " ")
    );
  }

  function normalizeQuestion(question, index, stationId) {
    if (typeof question === "string") {
      return { id: `${stationId}-q${index + 1}`, text: question, modelAnswer: "" };
    }
    return {
      id: String(question?.id ?? question?.question_id ?? `${stationId}-q${index + 1}`),
      text: asText(question?.text ?? question?.question ?? question?.prompt),
      modelAnswer: asText(question?.model_answer ?? question?.sample_answer ?? question?.example_answer),
    };
  }

  function normalizeStation(station, index) {
    const id = String(station?.id ?? station?.station_id ?? station?.slug ?? `station-${index + 1}`);
    const rawQuestions = station?.questions ?? station?.prompts ?? station?.follow_ups ?? [];
    const questionModels = station?.model_answers ?? station?.sample_answers ?? [];
    const questions = (Array.isArray(rawQuestions) ? rawQuestions : [])
      .map((question, questionIndex) => normalizeQuestion(question, questionIndex, id))
      .filter((question) => question.text)
      .slice(0, 4)
      .map((question, questionIndex) => ({
        ...question,
        modelAnswer: question.modelAnswer || asText(questionModels[questionIndex]),
      }));

    return {
      id,
      index: Number(station?.number ?? station?.index ?? index + 1),
      scenario: asText(station?.scenario ?? station?.stem ?? station?.context ?? station?.prompt),
      questions,
    };
  }

  function stationLabel(stationOrNumber) {
    const rawNumber =
      typeof stationOrNumber === "object" ? stationOrNumber?.index ?? stationOrNumber?.number : stationOrNumber;
    const number = Number(rawNumber);
    return Number.isFinite(number) && number > 0
      ? `Station ${String(number).padStart(2, "0")}`
      : "Station";
  }

  function showView(viewId, { scroll = true } = {}) {
    viewIds.forEach((id) => {
      const element = document.getElementById(id);
      if (element) element.hidden = id !== viewId;
    });
    if (scroll) window.scrollTo({ top: 0, behavior: "auto" });
  }

  function setNavigation(route) {
    $$(".nav-button").forEach((button) => {
      const active = button.dataset.route === route;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
  }

  function showToast(message, kind = "info", lifetime = 4200) {
    const toast = document.createElement("div");
    toast.className = `toast${kind === "error" ? " is-error" : ""}`;
    toast.textContent = message;
    $("#toast-region").appendChild(toast);
    window.setTimeout(() => toast.remove(), lifetime);
  }

  async function fetchJSON(url, options = {}, timeoutMs = 20000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        signal: controller.signal,
      });
      const raw = await response.text();
      let payload = {};
      if (raw) {
        try {
          payload = JSON.parse(raw);
        } catch {
          payload = { message: raw };
        }
      }
      if (!response.ok) {
        throw new Error(payload.error || payload.message || `Request failed (${response.status})`);
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") throw new Error("The request timed out. Please try again.");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function loadStations() {
    const stationList = $("#station-list");
    const retry = $("#retry-stations");
    retry.hidden = true;
    stationList.innerHTML = `
      <div class="station-skeleton"><span></span><span></span></div>
      <div class="station-skeleton"><span></span><span></span></div>`;
    $("#continue-to-mic").disabled = true;

    try {
      const payload = await fetchJSON(API.stations, {}, 15000);
      const rawStations = Array.isArray(payload) ? payload : payload.stations ?? payload.items ?? payload.data ?? [];
      state.stations = (Array.isArray(rawStations) ? rawStations : []).map(normalizeStation);
      if (!state.stations.length) throw new Error("No stations are currently available.");
      applyStationFilters();

      const firstUsable = state.filteredStations.find((station) => station.questions.length >= 4 && station.scenario);
      if (firstUsable) selectStation(firstUsable.id);
    } catch (error) {
      state.stations = [];
      state.filteredStations = [];
      stationList.innerHTML = `<div class="empty-list">We couldn’t load the station bank.<br>${escapeHTML(error.message)}</div>`;
      $("#station-count").textContent = "0";
      retry.hidden = false;
    }
  }

  function configuredValue(payload, providerName) {
    const key = providerName.toLowerCase();
    const candidates = [
      payload?.[`${key}_configured`],
      payload?.[`${key}_enabled`],
      payload?.[key],
      payload?.providers?.[key],
      payload?.config?.[key],
      payload?.services?.[key],
    ];
    for (const candidate of candidates) {
      if (typeof candidate === "boolean") return candidate;
      if (typeof candidate === "string") {
        const normalized = candidate.toLowerCase();
        if (["true", "configured", "ready", "available", "enabled", "set"].includes(normalized)) return true;
        if (["false", "missing", "unavailable", "disabled", "not_configured", "unset"].includes(normalized)) return false;
      }
      if (candidate && typeof candidate === "object") {
        const nested = candidate.configured ?? candidate.enabled ?? candidate.available ?? candidate.has_key;
        if (typeof nested === "boolean") return nested;
        if (typeof candidate.status === "string") {
          const normalized = candidate.status.toLowerCase();
          if (["configured", "ready", "available", "enabled"].includes(normalized)) return true;
          if (["missing", "unavailable", "disabled", "not_configured"].includes(normalized)) return false;
        }
      }
    }
    return null;
  }

  function renderProviderStatus(elementId, label, configured) {
    const element = document.getElementById(elementId);
    element.className = "provider-badge";
    if (configured === false || configured === null) element.classList.add("is-missing");
    element.innerHTML = `<i aria-hidden="true"></i>${label} ${configured ? "ready" : configured === false ? "not set" : "unknown"}`;
  }

  async function loadRuntimeStatus() {
    $("#sandbox-entitlement").textContent = "Free · open source";
    $("#sandbox-panel-entitlement").textContent = "Unlimited local practice";

    const configPromise = fetchJSON(API.config, {}, 10000)
      .then((payload) => {
        const deepseek = configuredValue(payload, "deepseek");
        const deepgram = configuredValue(payload, "deepgram");
        renderProviderStatus("deepseek-status", "DeepSeek", deepseek);
        renderProviderStatus("deepgram-status", "Deepgram", deepgram);
        const configuredCount = [deepseek, deepgram].filter(Boolean).length;
        const summary = $("#runtime-provider-summary");
        summary.textContent = `AI config · ${configuredCount}/2 ready`;
        summary.classList.toggle("is-ready", configuredCount > 0);
        summary.title = `DeepSeek ${deepseek ? "ready" : "not set"} · Deepgram ${deepgram ? "ready" : "not set"}`;
      })
      .catch(() => {
        renderProviderStatus("deepseek-status", "DeepSeek", null);
        renderProviderStatus("deepgram-status", "Deepgram", null);
        $("#runtime-provider-summary").textContent = "AI config · unknown";
      });

    await configPromise;
  }

  function applyStationFilters() {
    const query = $("#station-search").value.trim().toLocaleLowerCase("en");
    const numberMatch = query.match(/^(?:station\s*)?0*(\d+)$/i);
    state.filteredStations = state.stations.filter((station) => {
      if (!query) return true;
      if (numberMatch) return station.index === Number(numberMatch[1]);
      return stationLabel(station).toLocaleLowerCase("en").includes(query);
    });
    renderStationList();
  }

  function renderStationList() {
    const list = $("#station-list");
    $("#station-count").textContent = String(state.filteredStations.length);

    if (!state.filteredStations.length) {
      list.innerHTML = '<div class="empty-list">No matching station number.<br>Try a number from the available list.</div>';
      return;
    }

    list.innerHTML = state.filteredStations
      .map((station) => {
        const selected = station.id === state.selectedStationId;
        const complete = station.questions.length >= 4 && Boolean(station.scenario);
        return `
          <button
            class="station-option${selected ? " is-selected" : ""}"
            type="button"
            role="option"
            aria-selected="${selected}"
            data-station-id="${escapeHTML(station.id)}"
            ${complete ? "" : "disabled"}
          >
            <span class="station-option-index">${String(station.index).padStart(2, "0")}</span>
            <span class="station-option-copy">
              <strong>${escapeHTML(stationLabel(station))}</strong>
              <small>${complete ? "Four connected questions · ~6 min" : "Unavailable"}</small>
            </span>
          </button>`;
      })
      .join("");

    $$(".station-option", list).forEach((button) => {
      button.addEventListener("click", () => selectStation(button.dataset.stationId));
    });
  }

  function selectStation(stationId) {
    const station = state.stations.find((item) => item.id === String(stationId));
    if (!station) return;
    state.selectedStationId = station.id;
    state.selectedStation = station;
    $("#continue-to-mic").disabled = station.questions.length < 4 || !station.scenario;
    renderStationList();
  }

  function selectRandomStation() {
    const candidates = state.stations.filter(
      (station) => station.questions.length >= 4 && station.scenario && station.id !== state.selectedStationId,
    );
    const pool = candidates.length ? candidates : state.stations.filter((station) => station.questions.length >= 4);
    if (!pool.length) {
      showToast("No complete stations are currently available.", "error");
      return;
    }
    selectStation(pool[Math.floor(Math.random() * pool.length)].id);
    $("#station-search").value = "";
    applyStationFilters();
    const selectedButton = $(`.station-option[data-station-id="${CSS.escape(state.selectedStationId)}"]`);
    selectedButton?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function updateModeNote() {
    const mode = getMode();
    $("#mode-note").textContent =
      mode === "guided"
        ? "Keep the simulation timing, with one concise structure cue per question."
        : "Complete all four questions without pausing, then review the full station.";
  }

  function openMicCheck() {
    if (!state.selectedStation || state.selectedStation.questions.length < 4) {
      showToast("Choose a complete station first.", "error");
      return;
    }
    state.mode = getMode();
    state.strictMode = false;
    state.phase = "mic";
    state.textOnly = false;
    state.micReady = Boolean(state.stream?.active);
    $("#begin-session").disabled = !state.micReady;
    $("#begin-session").firstChild.textContent = "Start 60-second scenario ";
    $("#mic-status").textContent = state.micReady ? "Microphone ready" : "Microphone not checked";
    $("#mic-status").className = `mic-status${state.micReady ? " is-good" : ""}`;
    showView("mic-view");
    setNavigation("train");
  }

  function chooseMimeType() {
    if (!window.MediaRecorder) return "";
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4"];
    return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || "";
  }

  async function checkMicrophone() {
    const button = $("#check-mic");
    const status = $("#mic-status");
    const requestGeneration = ++state.micRequestGeneration;
    button.disabled = true;
    button.lastChild.textContent = " Requesting access…";
    status.className = "mic-status";
    status.textContent = "Allow microphone access in your browser when prompted.";

    try {
      releaseMedia();
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error("This browser does not support audio recording.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      if (state.micRequestGeneration !== requestGeneration || state.phase !== "mic") {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      state.stream = stream;
      state.mimeType = chooseMimeType();
      state.micReady = true;
      state.textOnly = false;
      state.micDetectedSound = false;
      $("#begin-session").disabled = false;
      $("#mic-visual").classList.add("is-listening");
      status.textContent = "Microphone connected. Say a sentence to test your level.";
      monitorMicrophone(stream);
    } catch (error) {
      if (state.micRequestGeneration !== requestGeneration || state.phase !== "mic") return;
      state.micReady = false;
      state.stream = null;
      status.className = "mic-status is-error";
      status.textContent = `${error.message || "Microphone access failed."} You can still use transcript-only mode.`;
      $("#begin-session").disabled = true;
    } finally {
      if (state.micRequestGeneration === requestGeneration && state.phase === "mic") {
        button.disabled = false;
        button.lastChild.textContent = " Check again";
      }
    }
  }

  function monitorMicrophone(stream) {
    stopMicMeter();
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    try {
      const context = new AudioContextClass();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.72;
      const source = context.createMediaStreamSource(stream);
      source.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      state.audioContext = context;

      const draw = () => {
        if (!state.stream || state.stream !== stream) return;
        analyser.getByteTimeDomainData(data);
        let energy = 0;
        for (const value of data) {
          const normalized = (value - 128) / 128;
          energy += normalized * normalized;
        }
        const rms = Math.sqrt(energy / data.length);
        const level = clamp(rms * 520, 3, 100);
        $("#level-meter-fill").style.width = `${level}%`;
        $("#mic-visual").style.setProperty("--mic-level", String(level / 100));
        if (level > 18 && !state.micDetectedSound) {
          state.micDetectedSound = true;
          const status = $("#mic-status");
          status.className = "mic-status is-good";
          status.textContent = "Sound detected. Your microphone is ready.";
        }
        state.analyserFrame = requestAnimationFrame(draw);
      };
      draw();
    } catch {
      // A level meter is helpful but not required for recording.
    }
  }

  function stopMicMeter() {
    if (state.analyserFrame) cancelAnimationFrame(state.analyserFrame);
    state.analyserFrame = 0;
    if (state.audioContext && state.audioContext.state !== "closed") state.audioContext.close().catch(() => {});
    state.audioContext = null;
    $("#mic-visual")?.classList.remove("is-listening");
    if ($("#level-meter-fill")) $("#level-meter-fill").style.width = "3%";
  }

  function releaseMedia() {
    stopMicMeter();
    if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
    state.micReady = false;
  }

  function enableTextOnlyMode() {
    state.micRequestGeneration += 1;
    releaseMedia();
    state.textOnly = true;
    const status = $("#mic-status");
    status.className = "mic-status is-good";
    status.textContent = "Transcript-only mode enabled. Timing stays the same; enter your answers after the station.";
    const beginButton = $("#begin-session");
    beginButton.disabled = false;
    beginButton.firstChild.textContent = "Start 60-second scenario ";
  }

  function makeResponse(question) {
    return {
      questionId: question.id,
      questionText: question.text,
      transcript: "",
      userEdited: false,
      durationSeconds: 0,
      audioBlob: null,
      audioUrl: "",
      audioId: null,
      mimeType: "",
      transcriptionStatus: state.textOnly ? "manual" : "idle",
      transcriptionError: "",
    };
  }

  function beginSession() {
    if (!state.selectedStation) return;
    if (!state.textOnly && !state.stream?.active) {
      showToast("The microphone disconnected. Check it again or use transcript-only mode.", "error");
      return;
    }
    state.micRequestGeneration += 1;
    state.mode = getMode();
    state.strictMode = false;
    state.sessionGeneration += 1;
    state.evaluationGeneration += 1;
    state.responses.forEach((response) => response.audioUrl && URL.revokeObjectURL(response.audioUrl));
    state.responses = state.selectedStation.questions.slice(0, 4).map(makeResponse);
    state.currentQuestionIndex = 0;
    state.sessionStartedAt = new Date().toISOString();
    state.attemptId = null;
    state.evaluation = null;
    state.transcriptionPromises.clear();
    stopMicMeter();
    showView("session-view");
    setNavigation("train");
    startScenario();
  }

  function startScenario() {
    state.phase = "scenario";
    state.currentQuestionIndex = 0;
    renderSessionPhase();
    startDeadline(PHASE_SECONDS.scenario, startQuestionPrep);
  }

  function startQuestionPrep() {
    stopDeadline();
    state.phase = "prep";
    renderSessionPhase();
    startDeadline(PHASE_SECONDS.prep, startRecording);
  }

  function createRecorder(stream) {
    const options = state.mimeType ? { mimeType: state.mimeType } : undefined;
    const recorder = options ? new MediaRecorder(stream, options) : new MediaRecorder(stream);
    const chunks = [];
    state.recorderStoppedPromise = new Promise((resolve) => {
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size) chunks.push(event.data);
      });
      recorder.addEventListener(
        "stop",
        () => {
          const type = recorder.mimeType || state.mimeType || chunks[0]?.type || "application/octet-stream";
          resolve(chunks.length ? new Blob(chunks, { type }) : null);
        },
        { once: true },
      );
      recorder.addEventListener(
        "error",
        () => resolve(chunks.length ? new Blob(chunks, { type: recorder.mimeType || state.mimeType }) : null),
        { once: true },
      );
    });
    return recorder;
  }

  function startRecording() {
    stopDeadline();
    state.phase = "recording";
    state.finishingRecording = false;
    state.recordingStartedAt = performance.now();
    state.recorder = null;
    state.recorderStoppedPromise = null;

    if (!state.textOnly && state.stream?.active) {
      try {
        state.recorder = createRecorder(state.stream);
        state.recorder.start(250);
      } catch (error) {
        state.recorder = null;
        state.recorderStoppedPromise = null;
        state.responses[state.currentQuestionIndex].transcriptionStatus = "error";
        state.responses[state.currentQuestionIndex].transcriptionError = error.message;
        showToast("This answer could not be recorded. You can enter the transcript after the station.", "error");
      }
    }

    renderSessionPhase();
    startDeadline(PHASE_SECONDS.recording, () => finishRecording("timeout"));
  }

  async function finishRecording(reason = "early") {
    if (state.phase !== "recording" || state.finishingRecording) return;
    const sessionGeneration = state.sessionGeneration;
    const responseIndex = state.currentQuestionIndex;
    const response = state.responses[responseIndex];
    const recorder = state.recorder;
    const recorderStoppedPromise = state.recorderStoppedPromise;
    if (!response) return;
    state.finishingRecording = true;
    stopDeadline();
    const action = $("#phase-action");
    action.disabled = true;
    action.textContent = "Saving this answer…";

    response.durationSeconds = clamp((performance.now() - state.recordingStartedAt) / 1000, 0, PHASE_SECONDS.recording);

    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        // An inactive recorder produces no blob; transcript entry remains available.
      }
    }

    if (recorderStoppedPromise) {
      const blob = await recorderStoppedPromise;
      if (
        state.sessionGeneration !== sessionGeneration ||
        state.phase !== "recording" ||
        state.responses[responseIndex] !== response
      ) {
        return;
      }
      if (blob?.size) {
        response.audioBlob = blob;
        response.mimeType = blob.type || recorder?.mimeType || state.mimeType;
        response.audioUrl = URL.createObjectURL(blob);
        transcribeResponse(responseIndex, blob);
      } else if (!state.textOnly) {
        response.transcriptionStatus = "error";
        response.transcriptionError = "No audio was captured";
      }
    }

    if (
      state.sessionGeneration !== sessionGeneration ||
      state.phase !== "recording" ||
      state.responses[responseIndex] !== response
    ) {
      return;
    }
    state.recorder = null;
    state.recorderStoppedPromise = null;
    state.finishingRecording = false;

    if (responseIndex >= 3) {
      finishStation();
    } else {
      state.currentQuestionIndex = responseIndex + 1;
      startQuestionPrep();
    }

    if (reason === "timeout") return;
  }

  function finishStation() {
    stopDeadline();
    state.phase = "review";
    releaseMedia();
    renderReview();
    showView("review-view");
  }

  function startDeadline(seconds, onDone) {
    stopDeadline();
    const durationMs = seconds * 1000;
    const deadline = performance.now() + durationMs;
    const timer = { deadline, durationMs, frame: 0, timeout: 0, fired: false, onDone };
    state.deadlineTimer = timer;

    const fire = () => {
      if (state.deadlineTimer !== timer || timer.fired) return;
      timer.fired = true;
      if (timer.frame) cancelAnimationFrame(timer.frame);
      if (timer.timeout) window.clearTimeout(timer.timeout);
      state.deadlineTimer = null;
      updateTimerVisual(0, durationMs);
      onDone();
    };

    const tick = (now) => {
      if (state.deadlineTimer !== timer || timer.fired) return;
      const remainingMs = Math.max(0, deadline - now);
      updateTimerVisual(remainingMs, durationMs);
      if (remainingMs <= 0) {
        fire();
        return;
      }
      timer.frame = requestAnimationFrame(tick);
    };
    timer.timeout = window.setTimeout(fire, durationMs);
    tick(performance.now());
  }

  function stopDeadline() {
    const timer = state.deadlineTimer;
    if (timer?.frame) cancelAnimationFrame(timer.frame);
    if (timer?.timeout) window.clearTimeout(timer.timeout);
    state.deadlineTimer = null;
  }

  function updateTimerVisual(remainingMs, durationMs) {
    const remainingSeconds = Math.ceil(remainingMs / 1000);
    const fraction = durationMs > 0 ? clamp(remainingMs / durationMs, 0, 1) : 0;
    $("#timer-seconds").textContent = String(remainingSeconds);
    $("#timer-ring-progress").style.strokeDashoffset = String(TIMER_CIRCUMFERENCE * (1 - fraction));
    $("#timer-wrap").classList.toggle("is-urgent", remainingSeconds <= 5);
    $("#timer-seconds").setAttribute("aria-label", `${remainingSeconds} seconds remaining`);
  }

  function renderSessionPhase() {
    const station = state.selectedStation;
    const questionIndex = state.currentQuestionIndex;
    const question = station.questions[questionIndex];
    const scenarioPhase = state.phase === "scenario";
    const prepPhase = state.phase === "prep";
    const recordingPhase = state.phase === "recording";

    $("#session-view").dataset.phase = state.phase;

    $("#session-station-number").textContent = stationLabel(station).toUpperCase();
    $("#recording-indicator").hidden = !recordingPhase;
    $("#coach-cue").hidden = state.mode !== "guided" || scenarioPhase;

    if (scenarioPhase) {
      $("#phase-pill").textContent = "READ · SCENARIO";
      $("#phase-overline").textContent = "SCENARIO";
      $("#session-phase-title").textContent = "Read the scenario";
      $("#prompt-category").textContent = "Scenario";
      $("#prompt-text").textContent = station.scenario;
      $("#prompt-card").hidden = false;
      $("#strict-hidden-card").hidden = true;
      $("#phase-hint").textContent = "The scenario disappears after 60 seconds, then Question 1 appears.";
      $("#phase-action").textContent = "I’m ready — start question 1";
    } else if (prepPhase) {
      $("#phase-pill").textContent = `QUESTION ${questionIndex + 1} / 4`;
      $("#phase-overline").textContent = "PREPARE";
      $("#session-phase-title").textContent = "Prepare your answer";
      $("#prompt-category").textContent = `Question ${questionIndex + 1}`;
      $("#prompt-text").textContent = question.text;
      $("#prompt-card").hidden = false;
      $("#strict-hidden-card").hidden = true;
      $("#phase-hint").textContent = "Recording begins after 15 seconds. The question stays visible throughout your answer.";
      $("#phase-action").textContent = "I’m ready — start answering";
    } else if (recordingPhase) {
      $("#phase-pill").textContent = `QUESTION ${questionIndex + 1} / 4`;
      $("#phase-overline").textContent = "ANSWER";
      $("#session-phase-title").textContent = state.textOnly ? "Deliver your answer" : "Recording your answer";
      $("#prompt-category").textContent = `Question ${questionIndex + 1}`;
      $("#prompt-text").textContent = question.text;
      $("#prompt-card").hidden = false;
      $("#strict-hidden-card").hidden = true;
      $("#phase-hint").textContent = state.textOnly
        ? "Transcript-only mode does not record audio. Speak normally, then enter your answer in review."
        : "Speak at a natural pace. End early when you have finished.";
      $("#phase-action").textContent = "Finish answer early";
    }

    $("#phase-action").disabled = false;
    updateProgress(questionIndex, state.phase);
    requestAnimationFrame(() => $("#session-phase-title").focus?.({ preventScroll: true }));
  }

  function updateProgress(currentIndex, phase) {
    $$("[data-progress]").forEach((bar) => {
      const index = Number(bar.dataset.progress);
      bar.classList.toggle("is-complete", index < currentIndex || (index === currentIndex && phase === "review"));
      bar.classList.toggle("is-current", index === currentIndex && phase !== "scenario" && phase !== "review");
    });
  }

  function handlePhaseAction() {
    if (state.phase === "scenario") startQuestionPrep();
    else if (state.phase === "prep") startRecording();
    else if (state.phase === "recording") finishRecording("early");
  }

  function extensionForMime(type) {
    if (String(type).includes("mp4")) return "m4a";
    if (String(type).includes("ogg")) return "ogg";
    return "webm";
  }

  function discardRecording(audioId) {
    if (!audioId) return;
    fetch(`${API.recordings}/${encodeURIComponent(audioId)}`, {
      method: "DELETE",
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {});
  }

  function transcribeResponse(index, blob) {
    const response = state.responses[index];
    const sessionGeneration = state.sessionGeneration;
    response.transcriptionStatus = "pending";
    updateTranscriptUI(index);

    const formData = new FormData();
    formData.append("audio", blob, `question-${index + 1}.${extensionForMime(blob.type)}`);
    formData.append("station_id", state.selectedStation.id);
    formData.append("question_id", response.questionId);
    formData.append("language", "en");

    const promise = fetchJSON(API.transcribe, { method: "POST", body: formData }, 90000)
      .then((payload) => {
        const audioId = payload.audio_id ?? payload.audioId ?? payload.data?.audio_id ?? payload.data?.audioId ?? null;
        if (state.sessionGeneration !== sessionGeneration || state.responses[index] !== response) {
          discardRecording(audioId);
          return;
        }
        response.audioId = audioId;
        const transcript = asText(payload.transcript ?? payload.text ?? payload.data?.transcript ?? payload.data?.text);
        if (!transcript) {
          response.transcriptionStatus = "manual";
          response.transcriptionError = asText(payload.warning ?? payload.message, "Enter the transcript manually.");
          return;
        }
        if (!response.userEdited) response.transcript = transcript;
        response.transcriptionStatus = "ready";
        response.transcriptionError = "";
      })
      .catch((error) => {
        if (state.sessionGeneration !== sessionGeneration || state.responses[index] !== response) return;
        response.transcriptionStatus = "error";
        response.transcriptionError = error.message;
      })
      .finally(() => {
        if (state.transcriptionPromises.get(index) !== promise) return;
        state.transcriptionPromises.delete(index);
        if (state.sessionGeneration !== sessionGeneration || state.responses[index] !== response) return;
        updateTranscriptUI(index);
      });

    state.transcriptionPromises.set(index, promise);
    return promise;
  }

  function transcriptStatus(response) {
    if (response.transcriptionStatus === "pending") return ["Transcribing", "is-pending"];
    if (response.transcriptionStatus === "ready") return ["Transcript ready", "is-ready"];
    if (response.transcriptionStatus === "error") return ["Review manually", "is-error"];
    if (response.transcriptionStatus === "manual") return ["Manual entry", ""];
    return ["Awaiting transcript", "is-pending"];
  }

  function renderReview() {
    const evaluateButton = $("#evaluate-attempt");
    evaluateButton.disabled = false;
    $("span", evaluateButton).textContent = "Save & generate coaching";
    $("#review-scenario-station").textContent = stationLabel(state.selectedStation);
    $("#review-scenario-text").textContent = state.selectedStation?.scenario || "Scenario unavailable.";
    const grid = $("#transcript-grid");
    grid.innerHTML = state.responses
      .map((response, index) => {
        const [statusLabel, statusClass] = transcriptStatus(response);
        const audio = response.audioUrl
          ? `<audio controls preload="metadata" src="${escapeHTML(response.audioUrl)}" aria-label="Question ${index + 1} recording"></audio>`
          : '<div class="audio-placeholder">No recording for this question. Enter your answer below.</div>';
        return `
          <article class="transcript-card" data-response-index="${index}">
            <div class="transcript-card-head">
              <span class="question-label">QUESTION ${String(index + 1).padStart(2, "0")}</span>
              <span class="transcript-state ${statusClass}" data-transcript-state>${statusLabel}</span>
            </div>
            <p class="transcript-question">${escapeHTML(response.questionText)}</p>
            <div class="audio-row">${audio}</div>
            <label for="transcript-${index}">Editable transcript</label>
            <textarea id="transcript-${index}" data-transcript-input placeholder="Paste or correct your English answer here…">${escapeHTML(response.transcript)}</textarea>
            <div class="transcript-meta">
              <span>${Math.round(response.durationSeconds)} sec</span>
              <span data-word-count>${countWords(response.transcript)} words</span>
            </div>
          </article>`;
      })
      .join("");

    $$("[data-transcript-input]", grid).forEach((textarea) => {
      textarea.addEventListener("input", () => {
        const card = textarea.closest("[data-response-index]");
        const index = Number(card.dataset.responseIndex);
        state.responses[index].transcript = textarea.value.trim();
        state.responses[index].userEdited = true;
        $("[data-word-count]", card).textContent = `${countWords(textarea.value)} words`;
      });
    });
  }

  function updateTranscriptUI(index) {
    const card = $(`[data-response-index="${index}"]`, $("#transcript-grid"));
    if (!card) return;
    const response = state.responses[index];
    const [label, statusClass] = transcriptStatus(response);
    const status = $("[data-transcript-state]", card);
    status.className = `transcript-state ${statusClass}`;
    status.textContent = label;
    const textarea = $("[data-transcript-input]", card);
    if (!response.userEdited && document.activeElement !== textarea) textarea.value = response.transcript;
    $("[data-word-count]", card).textContent = `${countWords(textarea.value)} words`;
  }

  function countWords(text) {
    const value = String(text || "").trim();
    if (!value) return 0;
    const latinTokens = value.match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g) || [];
    const cjkCharacters = value.match(/[\u3400-\u9fff]/g) || [];
    return latinTokens.length + cjkCharacters.length;
  }

  function buildAttemptPayload() {
    return {
      station_id: state.selectedStation.id,
      mode: "rapid4",
      coaching_mode: state.mode,
      strict_mode: state.strictMode,
      started_at: state.sessionStartedAt,
      completed_at: new Date().toISOString(),
      responses: state.responses.map((response, index) => ({
        question_id: response.questionId,
        question_number: index + 1,
        transcript: response.transcript.trim(),
        duration_seconds: Number(response.durationSeconds.toFixed(2)),
        audio_mime_type: response.mimeType || null,
        audio_id: response.audioId,
        has_audio: Boolean(response.audioBlob),
      })),
    };
  }

  async function saveAndEvaluate() {
    if (state.phase === "evaluating") return;
    const evaluationGeneration = ++state.evaluationGeneration;
    $$("[data-transcript-input]", $("#transcript-grid")).forEach((textarea, index) => {
      state.responses[index].transcript = textarea.value.trim();
    });
    if (state.responses.every((response) => !response.transcript) && !state.transcriptionPromises.size) {
      showToast("Add at least one transcript before generating coaching.", "error");
      $("#transcript-0")?.focus();
      return;
    }

    state.phase = "evaluating";
    const evaluateButton = $("#evaluate-attempt");
    evaluateButton.disabled = true;
    $("span", evaluateButton).textContent = "Generating coaching…";
    showView("evaluation-loading-view");
    if (state.transcriptionPromises.size) {
      $("#evaluation-loading-copy").textContent = "Finishing the remaining transcripts before the coaching review.";
      await Promise.allSettled([...state.transcriptionPromises.values()]);
      if (state.evaluationGeneration !== evaluationGeneration) return;
    }
    if (state.responses.every((response) => !response.transcript)) {
      state.phase = "review";
      renderReview();
      showView("review-view");
      showToast("No transcript text was returned. Enter at least one answer manually.", "error");
      $("#transcript-0")?.focus();
      return;
    }
    $("#evaluation-loading-copy").textContent = "Comparing all four answers for clarity, structure, empathy, and professional judgement.";
    const attemptPayload = buildAttemptPayload();

    try {
      const saved = await fetchJSON(
        API.attempts,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(attemptPayload),
        },
        20000,
      );
      if (state.evaluationGeneration !== evaluationGeneration) return;
      state.attemptId = saved.attempt_id ?? saved.id ?? saved.attempt?.id ?? saved.data?.id ?? null;
    } catch (error) {
      if (state.evaluationGeneration !== evaluationGeneration) return;
      showToast(`This attempt could not be saved: ${error.message}`, "error", 6000);
    }
    if (state.evaluationGeneration !== evaluationGeneration) return;

    const evaluationPayload = {
      attempt_id: state.attemptId,
      station_id: state.selectedStation.id,
      mode: "rapid4",
      coaching_mode: state.mode,
      strict_mode: state.strictMode,
      responses: attemptPayload.responses.map(({ question_id, question_number, transcript, duration_seconds }) => ({
        question_id,
        question_number,
        transcript,
        duration_seconds,
      })),
    };

    try {
      const payload = await fetchJSON(
        API.evaluate,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(evaluationPayload),
        },
        125000,
      );
      if (state.evaluationGeneration !== evaluationGeneration) return;
      state.evaluation = normalizeEvaluation(payload.evaluation ?? payload.feedback ?? payload.data ?? payload);
      if (state.evaluation.warning) showToast(state.evaluation.warning, "error", 6500);
    } catch (error) {
      if (state.evaluationGeneration !== evaluationGeneration) return;
      state.evaluation = buildLocalEvaluation();
      showToast(`AI coaching is unavailable, so a local structure check was used: ${error.message}`, "error", 6500);
    }

    if (state.evaluationGeneration !== evaluationGeneration) return;

    state.phase = "results";
    renderResults(state.evaluation);
    showView("results-view");
  }

  function scoreToPercent(value, max) {
    const score = Number(value);
    const explicitMax = Number(max);
    if (!Number.isFinite(score)) return 0;
    if (Number.isFinite(explicitMax) && explicitMax > 0) return Math.round(clamp((score / explicitMax) * 100, 0, 100));
    if (score <= 10) return Math.round(clamp(score * 10, 0, 100));
    return Math.round(clamp(score, 0, 100));
  }

  function displayScoreOutOfTen(percent) {
    return (clamp(percent, 0, 100) / 10).toFixed(1);
  }

  function scoreFromBreakdown(rawScores) {
    if (!rawScores) return 0;
    const items = Array.isArray(rawScores) ? rawScores : typeof rawScores === "object" ? Object.values(rawScores) : [];
    const scores = items
      .map((item) => {
        if (typeof item === "number" || typeof item === "string") return scoreToPercent(item);
        if (item && typeof item === "object") {
          return scoreToPercent(item.score ?? item.value ?? item.rating, item.max_score ?? item.max);
        }
        return NaN;
      })
      .filter((score) => Number.isFinite(score));
    return scores.length ? Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length) : 0;
  }

  function normalizeDimensions(rawDimensions) {
    if (Array.isArray(rawDimensions)) {
      return rawDimensions.map((item, index) => ({
        name: dimensionLabel(asText(item?.name ?? item?.dimension ?? item?.label, `Dimension ${index + 1}`)),
        score: scoreToPercent(item?.score ?? item?.value ?? item?.rating, item?.max_score ?? item?.max),
      }));
    }
    if (rawDimensions && typeof rawDimensions === "object") {
      return Object.entries(rawDimensions).map(([name, item]) => ({
        name: dimensionLabel(name),
        score: scoreToPercent(
          typeof item === "object" ? item.score ?? item.value ?? item.rating : item,
          typeof item === "object" ? item.max_score ?? item.max : undefined,
        ),
      }));
    }
    return [];
  }

  function fallbackAnswerStructure(questionText) {
    const question = String(questionText || "").toLocaleLowerCase("en");
    if (/\b(choose|justify|recommend)\b/.test(question)) {
      return [
        "先明确选择：第一句话直接说你会选什么。",
        "展开核心理由：最多两个，并解释为什么它们最重要。",
        "承认一个主要局限，再给出简短的缓解办法。",
        "最后收束：重申当前最优先保护的人、价值或结果。",
      ];
    }
    if (/\b(stakeholder|evidence|consult)\b/.test(question)) {
      return [
        "先回应任务：说明你会先补充信息，再形成建议。",
        "相关方：选 1–2 组关键的人，并说明他们能提供什么。",
        "证据：选 1–2 类关键数据，并说明它们如何影响判断。",
        "最后收束：用这些信息作出透明、可解释的决定。",
      ];
    }
    if (/\b(compare|comparison|options)\b/.test(question)) {
      return [
        "先给比较标准：用一句话说明你依据什么判断。",
        "展开点 1：用第一个标准比较各选项。",
        "展开点 2：只补一个不同的标准，并指出核心取舍。",
        "最后收束：除非题目要求，不必提前作最终选择。",
      ];
    }
    if (/longer term|long term|\bprepare\b/.test(question)) {
      return [
        "先定目标：说明长期准备要减少什么风险。",
        "展开点 1：讲清一个具体机制，以及它怎样发挥作用。",
        "展开点 2：再补一个不同层面的机制，不罗列完整清单。",
        "最后收束：说明如何协调或复盘成效。",
      ];
    }
    if (/\b(impartial|neutral)\b|take sides/.test(question)) {
      return [
        "先表态：目标是公平处理，而不是判断谁的人品更好。",
        "分别倾听并核对事实，给双方同样的表达机会。",
        "使用一致标准处理问题，不因私人关系改变判断。",
        "最后收束：不站队；只有影响持续时才升级。",
      ];
    }
    if (/\b(outcome|success)\b|aim for/.test(question)) {
      return [
        "先说理想结果：一句话明确你希望最终实现什么。",
        "兼顾人：说明相关者在关系或支持方面怎样才算改善。",
        "兼顾事：说明任务、安全或公平方面怎样才算改善。",
        "最后收束：追求可行结果，而不是强迫所有人完全一致。",
      ];
    }
    if (/\bshould\b|would you intervene/.test(question)) {
      return [
        "先给立场：直接回答 yes、no 或 it depends，并说明条件。",
        "展开最重要的理由：解释这个选择保护了什么。",
        "说明行动边界：你会做到哪一步，不会越过什么权限。",
        "最后收束：给出只有风险持续时才采用的升级条件。",
      ];
    }
    if (/\b(reflect|learn|experience)\b/.test(question)) {
      return [
        "先直接回答：点明一个真实经历、变化或认识。",
        "展开点 1：给一个具体细节，说明你当时怎么做。",
        "展开点 2：解释它怎样改变了你后来的行为。",
        "最后收束：把学习落到未来的具体做法。",
      ];
    }
    if (/\b(approach|respond)\b|what would you do/.test(question)) {
      return [
        "先表态：一句话说明首要目标和第一步。",
        "先处理人或事实：倾听、澄清并确认风险。",
        "再处理事情：提出一个可执行方案，并解释原因。",
        "最后收束：说明边界，以及何时才需要升级。",
      ];
    }
    return [
      "先直接回答：第一句话回应本问，不重复背景。",
      "展开点 1：讲清最重要的理由或行动。",
      "展开点 2：只在有帮助时补一个不同角度。",
      "最后收束：用优先级、边界或目标结束。",
    ];
  }

  function normalizeAnswerStructure(rawStructure, questionText) {
    const steps = Array.isArray(rawStructure)
      ? rawStructure
      : typeof rawStructure === "string"
        ? rawStructure.split(/\s*(?:→|\n+)\s*/)
        : [];
    if (steps.length < 3 || steps.length > 4 || steps.some((step) => typeof step !== "string")) {
      return fallbackAnswerStructure(questionText);
    }
    const cleaned = steps.map((step) => step.trim().replace(/\s+/g, " "));
    if (
      cleaned.some((step) => !step || step.length > 240) ||
      new Set(cleaned.map((step) => step.toLocaleLowerCase())).size !== cleaned.length
    ) {
      return fallbackAnswerStructure(questionText);
    }
    const cjkCounts = cleaned.map((step) => (step.match(/[\u3400-\u4dbf\u4e00-\u9fff]/g) || []).length);
    const lightlyExplained = cjkCounts
      .map((count, index) => ({ count, index }))
      .filter(({ count }) => count < 8);
    const briefEnglishWords = lightlyExplained.length
      ? cleaned[lightlyExplained[0].index].match(/[A-Za-z][A-Za-z'-]*/g) || []
      : [];
    const hasSubstantiveChinese =
      cjkCounts.reduce((sum, count) => sum + count, 0) >= 24 &&
      lightlyExplained.length <= 1 &&
      (!lightlyExplained.length ||
        ((lightlyExplained[0].count === 0 || lightlyExplained[0].count >= 4) &&
          briefEnglishWords.length >= 1 &&
          briefEnglishWords.length <= 12));
    return hasSubstantiveChinese ? cleaned : fallbackAnswerStructure(questionText);
  }

  function normalizeQuestionFeedback(rawQuestions) {
    const items = Array.isArray(rawQuestions)
      ? rawQuestions
      : rawQuestions && typeof rawQuestions === "object"
        ? Object.values(rawQuestions)
        : [];
    return state.responses.map((response, index) => {
      const raw = items[index] || {};
      const explicitScore = raw.score ?? raw.overall_score ?? raw.rating;
      return {
        questionId: raw.question_id ?? raw.id ?? response.questionId,
        questionText: response.questionText,
        score:
          explicitScore === null || explicitScore === undefined
            ? scoreFromBreakdown(raw.scores)
            : scoreToPercent(explicitScore, raw.max_score ?? raw.max),
        strength: asText(
          raw.worked ?? raw.strengths ?? raw.strength ?? raw.did_well ?? raw.positive,
          "已完成回答，可继续打磨表达。",
        ),
        priority: asText(raw.priority ?? raw.improvement ?? raw.improve ?? raw.next_step, "让第一句更直接地回应问题。"),
        evidence: asText(raw.evidence ?? raw.quote ?? raw.transcript_evidence, excerpt(response.transcript)),
        answerStructure: normalizeAnswerStructure(
          raw.answer_structure ?? raw.answerStructure ?? raw.structure_steps ?? raw.answer_plan ?? raw.structure,
          response.questionText,
        ),
        modelAnswer: asText(
          raw.model_answer ?? raw.sample_answer ?? raw.example_answer,
          state.selectedStation.questions[index]?.modelAnswer || "暂无示范答案。",
        ),
      };
    });
  }

  function normalizeEvaluation(raw) {
    const overallRaw = raw?.overall_score ?? raw?.score ?? raw?.total_score ?? raw?.overall?.score;
    let overallScore = scoreToPercent(overallRaw, raw?.max_score ?? raw?.overall?.max_score);
    let dimensions = normalizeDimensions(raw?.dimensions ?? raw?.dimension_scores ?? raw?.scores);
    const questions = normalizeQuestionFeedback(raw?.questions ?? raw?.question_feedback ?? raw?.per_question);
    if (!overallScore && questions.some((question) => question.score)) {
      overallScore = Math.round(questions.reduce((sum, question) => sum + question.score, 0) / questions.length);
    }
    if (!dimensions.length) dimensions = buildLocalDimensions();

    return {
      overallScore,
      summary: asText(
        raw?.summary ?? raw?.overall_feedback ?? raw?.one_line_summary ?? raw?.overall?.feedback,
        "你已完成整站回答。下一步是让立场、理由和行动之间更紧密。",
      ),
      nextFocus: asText(
        raw?.next_focus ?? raw?.next_training_goal ?? raw?.priority ?? raw?.actionable_next_step,
        "每题开头先用一句话明确回应，再解释理由。",
      ),
      repetition: asText(
        raw?.repetition ?? raw?.repetition_analysis ?? raw?.cross_question_repetition,
        "本地检查未判定跨题重复；请对照 transcript 人工复核。",
      ),
      dimensions,
      questions,
      provider: asText(raw?.provider ?? raw?.source, "AI / local coaching"),
      warning: asText(raw?.warning, ""),
    };
  }

  function excerpt(text, maxLength = 170) {
    const value = String(text || "").trim();
    if (!value) return "本题 transcript 为空。";
    return value.length > maxLength ? `“${value.slice(0, maxLength).trim()}…”` : `“${value}”`;
  }

  function buildLocalDimensions() {
    const combined = state.responses.map((response) => response.transcript).join(" ").toLowerCase();
    const totalWords = state.responses.reduce((sum, response) => sum + countWords(response.transcript), 0);
    const filled = state.responses.filter((response) => response.transcript.trim()).length;
    const hasStructure = /\b(first|second|finally|because|therefore|however|initially|then)\b/i.test(combined);
    const hasEmpathy = /\b(feel|concern|perspective|listen|support|understand|respect|empathy)\b/i.test(combined);
    const hasAction = /\b(i would|i will|speak|ask|check|escalate|document|follow up|reflect)\b/i.test(combined);
    const completion = Math.round((filled / 4) * 100);
    return [
      { name: "Directness & relevance", score: clamp(46 + filled * 9 + (hasAction ? 9 : 0), 0, 88) },
      { name: "Structure", score: clamp(44 + (hasStructure ? 25 : 0) + Math.min(totalWords / 18, 14), 0, 90) },
      { name: "Empathy & stakeholders", score: clamp(45 + (hasEmpathy ? 28 : 0) + filled * 3, 0, 90) },
      { name: "Professional judgement", score: clamp(47 + (hasAction ? 24 : 0) + filled * 3, 0, 90) },
      { name: "Completion", score: completion },
    ].map((item) => ({ ...item, score: Math.round(item.score) }));
  }

  function buildLocalEvaluation() {
    const dimensions = buildLocalDimensions();
    const overallScore = Math.round(dimensions.reduce((sum, item) => sum + item.score, 0) / dimensions.length);
    const questions = state.responses.map((response, index) => {
      const words = countWords(response.transcript);
      const hasDirectOpening = /^(i would|my first|the key|in this|yes|no|first)/i.test(response.transcript.trim());
      return {
        questionId: response.questionId,
        questionText: response.questionText,
        score: clamp(45 + Math.min(words / 3, 24) + (hasDirectOpening ? 10 : 0), 0, 84),
        strength:
          words >= 55
            ? "回答有足够内容可供评估，也有机会展开具体理由。"
            : "你在限时内完成了对问题的响应。",
        priority: hasDirectOpening
          ? "保留开头的明确立场，但只展开 1–2 个最重要的理由。"
          : "把第一句改成对问题的直接回答，然后再解释。",
        evidence: excerpt(response.transcript),
        answerStructure: fallbackAnswerStructure(response.questionText),
        modelAnswer: state.selectedStation.questions[index]?.modelAnswer || "本地模式暂无示范答案。",
      };
    });
    return {
      overallScore,
      summary: "你已完成整站限时表达。这是本地结构检查；它会帮你看完成度与表达线索，不等同于 AI 内容评审。",
      nextFocus: "每题开头先用一句话明确回应，再用不超过两个发展充分的观点支撑它。",
      repetition: "当前为本地降级检查，未进行语义级跨题重复分析。",
      dimensions,
      questions,
      provider: "local fallback",
      warning: "",
    };
  }

  function renderResults(evaluation) {
    const score = clamp(evaluation.overallScore, 0, 100);
    $("#results-title").textContent = `${stationLabel(state.selectedStation)} review`;
    $("#result-scenario-station").textContent = stationLabel(state.selectedStation);
    $("#result-scenario-text").textContent = state.selectedStation?.scenario || "Scenario unavailable.";
    $("#result-score").textContent = displayScoreOutOfTen(score);
    $("#result-summary").textContent = evaluation.summary;
    $("#next-focus").textContent = evaluation.nextFocus;
    $("#repetition-note").textContent = evaluation.repetition;
    $("#result-meta").innerHTML = [
      stationLabel(state.selectedStation),
      state.mode === "guided" ? "Guided" : "Simulation",
      evaluation.provider === "deepseek" ? "DeepSeek coaching" : "Local coaching",
      evaluation.warning ? "Fallback used" : null,
    ]
      .filter(Boolean)
      .map((item) => `<span>${escapeHTML(item)}</span>`)
      .join("");

    const scoreRing = $("#score-ring");
    scoreRing.style.strokeDashoffset = String(SCORE_CIRCUMFERENCE);
    requestAnimationFrame(() => {
      scoreRing.style.strokeDashoffset = String(SCORE_CIRCUMFERENCE * (1 - score / 100));
    });

    $("#dimension-list").innerHTML = evaluation.dimensions
      .map(
        (dimension) => `
          <div class="dimension-row">
            <span>${escapeHTML(dimension.name)}</span>
            <div class="dimension-bar"><i data-width="${clamp(dimension.score, 0, 100)}"></i></div>
            <strong>${displayScoreOutOfTen(dimension.score)}</strong>
          </div>`,
      )
      .join("");
    requestAnimationFrame(() => {
      $$(".dimension-bar i").forEach((bar) => {
        bar.style.width = `${bar.dataset.width}%`;
      });
    });

    $("#feedback-list").innerHTML = evaluation.questions
      .map(
        (question, index) => `
          <article class="feedback-card${index === 0 ? " is-open" : ""}">
            <button class="feedback-toggle" type="button" aria-expanded="${index === 0}" data-feedback-toggle>
              <span class="feedback-number">${String(index + 1).padStart(2, "0")}</span>
              <span class="feedback-title">
                <strong>${escapeHTML(question.questionText)}</strong>
                <span>${escapeHTML(question.priority)}</span>
              </span>
              <span class="feedback-score">${displayScoreOutOfTen(question.score)}</span>
              <svg class="feedback-chevron" viewBox="0 0 18 18" aria-hidden="true"><path d="m4 7 5 5 5-5" /></svg>
            </button>
            <div class="feedback-body" ${index === 0 ? "" : "hidden"}>
              <div class="feedback-block"><h3>Strength · 优点</h3><p>${escapeHTML(question.strength)}</p></div>
              <div class="feedback-block"><h3>Priority · 改进</h3><p>${escapeHTML(question.priority)}</p></div>
              <div class="feedback-block feedback-block--structure">
                <h3>答题结构 · Answer plan</h3>
                <ol>${normalizeAnswerStructure(question.answerStructure, question.questionText)
                  .map((step) => `<li>${escapeHTML(step)}</li>`)
                  .join("")}</ol>
              </div>
              <div class="feedback-block feedback-block--wide"><h3>Transcript evidence</h3><p>${escapeHTML(question.evidence)}</p></div>
              <div class="feedback-block feedback-block--model"><h3>High-standard answer · 高标准参考</h3><p>${escapeHTML(question.modelAnswer)}</p></div>
            </div>
          </article>`,
      )
      .join("");

    $$("[data-feedback-toggle]").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const card = toggle.closest(".feedback-card");
        const body = $(".feedback-body", card);
        const open = !card.classList.contains("is-open");
        card.classList.toggle("is-open", open);
        body.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
      });
    });
  }

  function isSessionInProgress() {
    return ["scenario", "prep", "recording", "review", "evaluating"].includes(state.phase);
  }

  function requestExit(action) {
    if (!isSessionInProgress()) {
      action();
      return;
    }
    state.pendingExitAction = action;
    $("#exit-modal").hidden = false;
    $("#cancel-exit").focus();
  }

  function abortSession({ discardStoredRecordings = true } = {}) {
    state.micRequestGeneration += 1;
    state.sessionGeneration += 1;
    state.evaluationGeneration += 1;
    stopDeadline();
    if (state.recorder?.state && state.recorder.state !== "inactive") {
      try {
        state.recorder.stop();
      } catch {
        // Best-effort cleanup while abandoning a recording.
      }
    }
    state.recorder = null;
    state.recorderStoppedPromise = null;
    state.finishingRecording = false;
    releaseMedia();
    state.responses.forEach((response) => {
      if (response.audioUrl) URL.revokeObjectURL(response.audioUrl);
      if (discardStoredRecordings && response.audioId) discardRecording(response.audioId);
    });
    state.responses = [];
    state.transcriptionPromises.clear();
    state.attemptId = null;
    state.evaluation = null;
    state.pendingExitAction = null;
    state.phase = "setup";
  }

  function goToSetup() {
    state.micRequestGeneration += 1;
    state.evaluationGeneration += 1;
    if (!isSessionInProgress()) {
      stopDeadline();
      releaseMedia();
      state.phase = "setup";
    }
    setNavigation("train");
    showView("setup-view");
  }

  async function openHistory() {
    state.micRequestGeneration += 1;
    state.evaluationGeneration += 1;
    if (state.phase === "mic") releaseMedia();
    state.phase = "history";
    setNavigation("history");
    showView("history-view");
    await loadHistory();
  }

  function historyDate(value) {
    const date = value ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) return "Unknown date";
    return new Intl.DateTimeFormat("en-AU", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
  }

  function historyScore(attempt) {
    const raw =
      attempt?.overall_score ??
      attempt?.score ??
      attempt?.evaluation?.overall_score ??
      attempt?.evaluation?.score ??
      attempt?.feedback?.overall_score;
    return scoreToPercent(raw, attempt?.max_score ?? attempt?.evaluation?.max_score);
  }

  async function loadHistory() {
    const list = $("#history-list");
    list.innerHTML = '<div class="history-loading"><span></span><span></span><span></span></div>';
    try {
      const payload = await fetchJSON(API.history, {}, 15000);
      const attempts = Array.isArray(payload) ? payload : payload.attempts ?? payload.history ?? payload.items ?? payload.data ?? [];
      state.history = Array.isArray(attempts) ? attempts : [];
      renderHistory();
    } catch (error) {
      state.history = [];
      list.innerHTML = `
        <div class="history-error">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 16.5v.1"/><circle cx="12" cy="12" r="9"/></svg>
          <strong>Practice history is unavailable</strong>
          <p>${escapeHTML(error.message)}</p>
        </div>`;
      renderHistoryStats();
    }
  }

  function renderHistoryStats() {
    const scores = state.history.map(historyScore).filter((score) => score > 0);
    $("#history-count").textContent = String(state.history.length);
    $("#history-average").textContent = scores.length
      ? displayScoreOutOfTen(scores.reduce((sum, score) => sum + score, 0) / scores.length)
      : "—";

    let trend = null;
    if (scores.length >= 2) {
      const chronological = [...scores].reverse();
      const midpoint = Math.max(1, Math.floor(chronological.length / 2));
      const earlier = chronological.slice(0, midpoint);
      const recent = chronological.slice(midpoint);
      const average = (items) => items.reduce((sum, item) => sum + item, 0) / items.length;
      trend = recent.length ? Math.round(average(recent) - average(earlier)) : chronological.at(-1) - chronological[0];
    }
    $("#history-trend").textContent =
      trend === null ? "—" : `${trend > 0 ? "+" : ""}${(trend / 10).toFixed(1)}`;
    $("#history-trend").style.color = trend > 0 ? "var(--accent)" : trend < 0 ? "var(--danger)" : "";
    $("#history-trend-label").textContent = trend === null ? "At least 2 needed" : trend > 0 ? "Trending up" : trend < 0 ? "Review the pattern" : "Holding steady";
  }

  function renderHistory() {
    renderHistoryStats();
    const list = $("#history-list");
    if (!state.history.length) {
      list.innerHTML = `
        <div class="history-empty">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h14v17H5zM8 8h8M8 12h8M8 16h5"/></svg>
          <strong>No completed stations yet</strong>
          <p>Complete your first station to see scores, modes, and progress over time.</p>
        </div>`;
      return;
    }

    list.innerHTML = state.history
      .map((attempt, index) => {
        const liveStation = state.stations.find((station) => station.id === String(attempt.station_id));
        const number = Number(attempt.station_number) || liveStation?.index;
        const label = stationLabel(number);
        const mode = (attempt.coaching_mode ?? attempt.mode ?? "simulation") === "guided" ? "Guided" : "Simulation";
        const score = historyScore(attempt);
        const createdAt = attempt.completed_at ?? attempt.created_at ?? attempt.date;
        return `
          <article class="history-row">
            <time class="history-date">${escapeHTML(historyDate(createdAt))}</time>
            <div class="history-station"><strong>${escapeHTML(label)}</strong></div>
            <span class="history-mode">${mode}</span>
            <span class="history-score">${score ? displayScoreOutOfTen(score) : "—"}<small>${score ? " / 10" : ""}</small></span>
            <button class="history-open" type="button" data-history-index="${index}" aria-label="Open the detailed review for ${escapeHTML(label)}">
              <svg viewBox="0 0 18 18" aria-hidden="true"><path d="M4 9h10M10 5l4 4-4 4"/></svg>
            </button>
          </article>`;
      })
      .join("");

    $$("[data-history-index]", list).forEach((button) => {
      button.addEventListener("click", () => openHistoryAttempt(Number(button.dataset.historyIndex)));
    });
  }

  function openHistoryAttempt(index) {
    const attempt = state.history[index];
    const rawEvaluation = attempt?.evaluation ?? attempt?.feedback ?? attempt?.result;
    const rawResponses = attempt?.responses ?? rawEvaluation?.responses;
    if (!rawEvaluation || !Array.isArray(rawResponses)) {
      showToast("This record contains a summary only; question-level details are unavailable.");
      return;
    }
    const stationData = attempt.station ?? {};
    const liveStation = state.stations.find((station) => station.id === String(attempt.station_id));
    const normalized = normalizeStation(
      {
        id: attempt.station_id ?? stationData.id ?? liveStation?.id ?? "history",
        number: attempt.station_number ?? liveStation?.index,
        scenario:
          attempt.scenario ??
          stationData.scenario ??
          liveStation?.scenario ??
          "Scenario unavailable for this older practice.",
        questions: rawResponses.map((response, responseIndex) => ({
          id: response.question_id ?? `history-q${responseIndex + 1}`,
          text: response.question_text || response.question || `Question ${responseIndex + 1}`,
        })),
      },
      Math.max(0, Number(attempt.station_number ?? liveStation?.index ?? 1) - 1),
    );
    state.selectedStation = normalized;
    state.selectedStationId = normalized.id;
    state.responses = rawResponses.slice(0, 4).map((response, responseIndex) => ({
      ...makeResponse(normalized.questions[responseIndex]),
      transcript: asText(response.transcript),
      durationSeconds: Number(response.duration_seconds ?? response.duration ?? 0),
    }));
    state.mode = attempt.coaching_mode ?? (attempt.mode === "guided" ? "guided" : "simulation");
    state.strictMode = Boolean(attempt.strict_mode);
    state.evaluation = normalizeEvaluation(rawEvaluation);
    renderResults(state.evaluation);
    setNavigation("train");
    showView("results-view");
  }

  function wireEvents() {
    $("#station-search").addEventListener("input", applyStationFilters);
    $("#retry-stations").addEventListener("click", loadStations);
    $("#random-station").addEventListener("click", selectRandomStation);
    $$("input[name='session-mode']").forEach((input) => input.addEventListener("change", updateModeNote));
    $("#continue-to-mic").addEventListener("click", openMicCheck);
    $$("[data-back-to-setup]").forEach((button) => button.addEventListener("click", goToSetup));
    $("#check-mic").addEventListener("click", checkMicrophone);
    $("#text-only-mode").addEventListener("click", enableTextOnlyMode);
    $("#begin-session").addEventListener("click", beginSession);
    $("#phase-action").addEventListener("click", handlePhaseAction);
    $("#leave-session").addEventListener("click", () => requestExit(goToSetup));
    $("#evaluate-attempt").addEventListener("click", saveAndEvaluate);
    $("#new-session-from-results").addEventListener("click", goToSetup);
    $("#open-history-from-results").addEventListener("click", openHistory);
    $("#new-session-from-history").addEventListener("click", goToSetup);
    $("#refresh-history").addEventListener("click", loadHistory);

    $$(".nav-button").forEach((button) => {
      button.addEventListener("click", () => {
        const destination = button.dataset.route;
        const action = destination === "history" ? openHistory : goToSetup;
        requestExit(action);
      });
    });
    $("#brand-home").addEventListener("click", (event) => {
      event.preventDefault();
      requestExit(goToSetup);
    });

    $("#cancel-exit").addEventListener("click", () => {
      $("#exit-modal").hidden = true;
      state.pendingExitAction = null;
      $("#leave-session").focus();
    });
    $("#confirm-exit").addEventListener("click", () => {
      const action = state.pendingExitAction;
      $("#exit-modal").hidden = true;
      state.pendingExitAction = null;
      abortSession();
      action?.();
    });
    $("#exit-modal").addEventListener("click", (event) => {
      if (event.target === $("#exit-modal")) $("#cancel-exit").click();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("#exit-modal").hidden) $("#cancel-exit").click();
    });

    window.addEventListener("pagehide", () => {
      const discardStoredRecordings = isSessionInProgress();
      state.abandonedByPageHide = true;
      abortSession({ discardStoredRecordings });
    });
    window.addEventListener("pageshow", (event) => {
      if (!event.persisted || !state.abandonedByPageHide) return;
      state.abandonedByPageHide = false;
      $("#exit-modal").hidden = true;
      setNavigation("train");
      showView("setup-view", { scroll: false });
    });
  }

  function initialize() {
    $("#timer-ring-progress").style.strokeDasharray = String(TIMER_CIRCUMFERENCE);
    $("#score-ring").style.strokeDasharray = String(SCORE_CIRCUMFERENCE);
    wireEvents();
    updateModeNote();
    setNavigation("train");
    showView("setup-view", { scroll: false });
    loadStations();
    loadRuntimeStatus();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
