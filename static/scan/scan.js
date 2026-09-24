(() => {
  "use strict";

  const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
  const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
  const loadingMessages = {
    scenario: [
      "Reading the station scenario…",
      "Separating the scenario from any visible question…",
      "Saving the context for later questions…",
    ],
    question: [
      "Reading the question…",
      "Building a concise 15-second speaking map…",
      "Writing a high-standard reference answer…",
    ],
  };

  const state = {
    file: null,
    previewDataUrl: "",
    previewReader: null,
    selectionVersion: 0,
    inputMode: "scenario",
    stationContext: "",
    previousQuestions: [],
    request: null,
    loadingTimer: null,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function compactText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function announce(message) {
    $("#scan-live-region").textContent = "";
    window.setTimeout(() => {
      $("#scan-live-region").textContent = message;
    }, 30);
  }

  function formatBytes(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function inferredType(file) {
    if (file.type) return file.type.toLowerCase();
    const extension = file.name.split(".").pop()?.toLowerCase();
    return {
      jpg: "image/jpeg",
      jpeg: "image/jpeg",
      png: "image/png",
      webp: "image/webp",
      gif: "image/gif",
    }[extension] || "";
  }

  function scrollToLatest() {
    window.requestAnimationFrame(() => {
      const conversation = $("#scan-conversation");
      conversation.scrollTop = conversation.scrollHeight;
    });
  }

  function updateContextTranscripts() {
    $$('[data-scenario-transcript]').forEach((element) => {
      element.textContent = state.stationContext;
    });
  }

  function updateInterface() {
    const hasContext = Boolean(state.stationContext);
    const isScenario = state.inputMode === "scenario";

    $$('[data-scan-mode]').forEach((button) => {
      const active = button.dataset.scanMode === state.inputMode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });

    $("#scan-station-memory").hidden = !hasContext;
    $("#scan-station-context-preview").textContent = state.stationContext;
    $("#scan-attachment-mode").textContent = isScenario
      ? "Scenario image"
      : hasContext ? "Question · saved scenario will be used" : "Standalone question";
    $("#scan-drop-copy").textContent = isScenario
      ? "Add the complete station scenario"
      : hasContext ? "Add any question from this station" : "Add a complete standalone question";
    $("#scan-composer-hint").textContent = isScenario
      ? hasContext ? "Sending this starts a new station and replaces the saved scenario." : "This starts a new station."
      : hasContext ? "The saved scenario will be included automatically." : "No scenario will be added.";
    $("#scan-send span").textContent = isScenario ? "Send scenario" : "Send question";
    $("#scan-send").disabled = !state.file || Boolean(state.request);
    updateContextTranscripts();
  }

  function setInputMode(mode, { focus = false, speak = true } = {}) {
    if (mode !== "scenario" && mode !== "question") return;
    state.inputMode = mode;
    updateInterface();
    if (focus) {
      $("#scan-composer").focus();
      $("#scan-composer").scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (speak) announce(`${mode === "scenario" ? "Scenario" : "Question"} mode selected.`);
  }

  function clearContext() {
    $$('[data-scenario-transcript]').forEach((element) => {
      element.removeAttribute("data-scenario-transcript");
    });
    state.stationContext = "";
    state.previousQuestions = [];
    $("#scan-station-memory").open = false;
    updateInterface();
  }

  function saveScenario(text, { clearQuestions = true } = {}) {
    const scenario = compactText(text);
    if (!scenario) return false;
    if (clearQuestions) {
      $$('[data-scenario-transcript]').forEach((element) => {
        element.removeAttribute("data-scenario-transcript");
      });
    }
    state.stationContext = scenario;
    if (clearQuestions) state.previousQuestions = [];
    updateInterface();
    return true;
  }

  function openContextEditor() {
    if (!state.stationContext) return;
    const dialog = $("#scan-edit-dialog");
    $("#scan-context-editor").value = state.stationContext;
    dialog.showModal();
    window.requestAnimationFrame(() => $("#scan-context-editor").focus());
  }

  function cancelPreviewRead() {
    state.selectionVersion += 1;
    if (state.previewReader?.readyState === FileReader.LOADING) state.previewReader.abort();
    state.previewReader = null;
  }

  function clearAttachment() {
    cancelPreviewRead();
    state.file = null;
    state.previewDataUrl = "";
    $("#scan-camera-input").value = "";
    $("#scan-gallery-input").value = "";
    $("#scan-image-preview").removeAttribute("src");
    $("#scan-attachment").hidden = true;
    updateInterface();
  }

  function showAttachment(file, dataUrl) {
    state.file = file;
    state.previewDataUrl = dataUrl;
    $("#scan-image-preview").src = dataUrl;
    $("#scan-file-name").textContent = file.name || "MMI image";
    $("#scan-file-size").textContent = formatBytes(file.size);
    $("#scan-attachment").hidden = false;
    updateInterface();
    $("#scan-send").focus();
    announce("Image attached and ready to send.");
  }

  function appendAssistantMessage(build) {
    const fragment = $("#scan-assistant-message-template").content.cloneNode(true);
    const article = $(".scan-message", fragment);
    const bubble = $(".scan-response-bubble", fragment);
    build(bubble, article);
    $("#scan-conversation").append(fragment);
    scrollToLatest();
    return article;
  }

  function appendSimpleResponse({ kicker = "SCAN COACH", title, text, transcript = "", actions = [] }) {
    return appendAssistantMessage((bubble) => {
      const label = document.createElement("p");
      label.className = "scan-message-label";
      label.textContent = kicker;
      bubble.append(label);

      const heading = document.createElement("h2");
      heading.textContent = title;
      bubble.append(heading);

      const copy = document.createElement("p");
      copy.textContent = text;
      bubble.append(copy);

      if (transcript) {
        const transcriptBox = document.createElement("div");
        transcriptBox.className = "scan-scenario-transcript";
        const transcriptLabel = document.createElement("strong");
        transcriptLabel.textContent = "Saved scenario transcript";
        const transcriptText = document.createElement("p");
        transcriptText.dataset.scenarioTranscript = "";
        transcriptText.textContent = transcript;
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "scan-text-button";
        edit.textContent = "Edit OCR text";
        edit.addEventListener("click", openContextEditor);
        transcriptBox.append(transcriptLabel, transcriptText, edit);
        bubble.append(transcriptBox);
      }

      if (actions.length) {
        const actionRow = document.createElement("div");
        actionRow.className = "scan-inline-actions";
        actions.forEach(({ label: actionLabel, primary = false, run }) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = primary ? "scan-primary-button" : "scan-secondary-button";
          button.textContent = actionLabel;
          button.addEventListener("click", run);
          actionRow.append(button);
        });
        bubble.append(actionRow);
      }
    });
  }

  function selectFile(file) {
    if (!file) return;
    if (state.request) {
      announce("Wait for the current image, or cancel it first.");
      return;
    }
    cancelPreviewRead();
    const type = inferredType(file);
    if (!ACCEPTED_TYPES.has(type)) {
      appendSimpleResponse({
        kicker: "IMAGE NOT ADDED",
        title: "Choose a different format",
        text: "Use a JPEG, PNG, WebP or GIF image. Convert HEIC images or take a screenshot first.",
      });
      return;
    }
    if (!file.size || file.size > MAX_IMAGE_BYTES) {
      appendSimpleResponse({
        kicker: "IMAGE NOT ADDED",
        title: !file.size ? "This image is empty" : "This image is over 10 MB",
        text: !file.size ? "Choose another image." : "Crop it more tightly or use a screenshot.",
      });
      return;
    }

    const version = state.selectionVersion;
    const reader = new FileReader();
    state.previewReader = reader;
    reader.addEventListener("load", () => {
      if (version !== state.selectionVersion) return;
      showAttachment(file, String(reader.result || ""));
    });
    reader.addEventListener("error", () => {
      if (version !== state.selectionVersion) return;
      appendSimpleResponse({ kicker: "IMAGE NOT ADDED", title: "This image could not be opened", text: "Please choose another file." });
    });
    reader.addEventListener("loadend", () => {
      if (state.previewReader === reader) state.previewReader = null;
    });
    reader.readAsDataURL(file);
  }

  function appendUserMessage(dataUrl, mode) {
    const fragment = $("#scan-user-message-template").content.cloneNode(true);
    $(".scan-message-label", fragment).textContent = mode === "scenario" ? "Scenario" : "Question";
    $("img", fragment).src = dataUrl;
    $("#scan-conversation").append(fragment);
    scrollToLatest();
  }

  function appendLoadingMessage(mode, onCancel) {
    const fragment = $("#scan-loading-message-template").content.cloneNode(true);
    const article = $(".scan-message", fragment);
    const status = $('[role="status"]', fragment);
    const cancel = $("button", fragment);
    status.textContent = loadingMessages[mode][0];
    cancel.addEventListener("click", onCancel);
    $("#scan-conversation").append(fragment);
    scrollToLatest();

    let index = 0;
    state.loadingTimer = window.setInterval(() => {
      index = (index + 1) % loadingMessages[mode].length;
      status.textContent = loadingMessages[mode][index];
    }, 4200);
    return article;
  }

  function stopLoading(article) {
    if (state.loadingTimer) window.clearInterval(state.loadingTimer);
    state.loadingTimer = null;
    article?.remove();
  }

  function copyButton(text, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scan-copy-button";
    button.textContent = "Copy";
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
        announce(`${label} copied.`);
        window.setTimeout(() => { button.textContent = "Copy"; }, 1600);
      } catch (_error) {
        announce(`Could not copy ${label.toLowerCase()}.`);
      }
    });
    return button;
  }

  function addRecognisedPrompt(bubble, result) {
    const scenario = compactText(result.recognized?.scenario);
    const question = compactText(result.recognized?.question);
    const details = document.createElement("details");
    details.className = "scan-recognised-prompt";
    const summary = document.createElement("summary");
    summary.textContent = result.scenario_source === "provided"
      ? "Recognised question · saved scenario used"
      : "Recognised prompt · check the reading";
    details.append(summary);
    if (scenario) {
      const block = document.createElement("div");
      const label = document.createElement("strong");
      label.textContent = "Scenario";
      const value = document.createElement("p");
      value.textContent = scenario;
      block.append(label, value);
      details.append(block);
    }
    if (question) {
      const block = document.createElement("div");
      const label = document.createElement("strong");
      label.textContent = "Question";
      const value = document.createElement("p");
      value.textContent = question;
      block.append(label, value);
      details.append(block);
    }
    bubble.append(details);
  }

  function addAnswerCard(bubble, { type, kicker, title, subtitle, body, copyText }) {
    const card = document.createElement("section");
    card.className = `scan-answer-card scan-answer-card--${type}`;
    const header = document.createElement("header");
    const headingWrap = document.createElement("div");
    const label = document.createElement("p");
    label.className = "scan-kicker";
    label.textContent = kicker;
    const heading = document.createElement("h3");
    heading.textContent = title;
    const small = document.createElement("span");
    small.textContent = subtitle;
    heading.append(small);
    headingWrap.append(label, heading);
    header.append(headingWrap, copyButton(copyText, title));
    card.append(header, body);
    bubble.append(card);
  }

  function renderReady(result, uploadMode) {
    const structure = Array.isArray(result.answer_structure) ? result.answer_structure : [];
    const modelAnswer = typeof result.model_answer === "string" ? result.model_answer : "";
    if (structure.length < 3 || structure.length > 4 || !modelAnswer) {
      throw new Error("The coaching response was incomplete. Please try again.");
    }

    const visibleScenario = compactText(result.recognized?.scenario);
    const question = compactText(result.recognized?.question);
    const scenarioSaved = uploadMode === "scenario" && Boolean(visibleScenario);
    if (scenarioSaved) saveScenario(visibleScenario);
    if (question && state.stationContext && (scenarioSaved || result.scenario_source === "provided")) {
      const normalizedQuestion = compactText(question);
      if (!state.previousQuestions.some((item) => compactText(item) === normalizedQuestion)) {
        state.previousQuestions.push(normalizedQuestion);
      }
    }

    appendAssistantMessage((bubble) => {
      const label = document.createElement("p");
      label.className = "scan-message-label";
      label.textContent = scenarioSaved ? "SCENARIO SAVED · QUESTION ANSWERED" : "QUESTION READY";
      const title = document.createElement("h2");
      title.textContent = "A clear route through this question";
      bubble.append(label, title);

      if (scenarioSaved) {
        const note = document.createElement("p");
        note.textContent = "I saved this as the new station context. You can correct the transcript before sending another question.";
        bubble.append(note);
        const transcript = document.createElement("div");
        transcript.className = "scan-scenario-transcript";
        const transcriptLabel = document.createElement("strong");
        transcriptLabel.textContent = "Saved scenario transcript";
        const transcriptText = document.createElement("p");
        transcriptText.dataset.scenarioTranscript = "";
        transcriptText.textContent = state.stationContext;
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "scan-text-button";
        edit.textContent = "Edit OCR text";
        edit.addEventListener("click", openContextEditor);
        transcript.append(transcriptLabel, transcriptText, edit);
        bubble.append(transcript);
      }

      addRecognisedPrompt(bubble, result);

      const list = document.createElement("ol");
      list.className = "scan-answer-plan";
      structure.forEach((step) => {
        const item = document.createElement("li");
        item.textContent = String(step);
        list.append(item);
      });
      addAnswerCard(bubble, {
        type: "plan",
        kicker: "15-SECOND MAP",
        title: "答题结构",
        subtitle: "Answer plan",
        body: list,
        copyText: structure.map((step, index) => `${index + 1}. ${step}`).join("\n"),
      });

      const answer = document.createElement("p");
      answer.className = "scan-model-answer";
      answer.textContent = modelAnswer;
      addAnswerCard(bubble, {
        type: "reference",
        kicker: "ABOUT 60 SECONDS",
        title: "High-standard reference",
        subtitle: "高标准参考",
        body: answer,
        copyText: modelAnswer,
      });
    });

    if (scenarioSaved) setInputMode("question", { speak: false });
    $("#scan-follow-up-actions").hidden = false;
    updateInterface();
    announce("Answer plan and high-standard reference are ready.");
  }

  function renderNonReady(result, uploadMode, file, dataUrl) {
    const status = result?.scan_status || "cropped_or_blurry";
    const scenario = compactText(result?.recognized?.scenario);
    const question = compactText(result?.recognized?.question);
    const isScenarioCapture = status === "scenario_only" || status === "review_without_question";

    if (isScenarioCapture && uploadMode === "scenario" && scenario) {
      saveScenario(scenario);
      appendSimpleResponse({
        kicker: status === "review_without_question" ? "SCENARIO FOUND IN REVIEW" : "SCENARIO SAVED",
        title: "I have the station context",
        text: "The recognised text is below. Correct any OCR mistakes, then send whichever question you want help with.",
        transcript: state.stationContext,
        actions: [{ label: "Send a question", primary: true, run: () => setInputMode("question", { focus: true }) }],
      });
      setInputMode("question", { speak: false });
      $("#scan-follow-up-actions").hidden = false;
      announce("Scenario saved. You can now send any question from this station.");
      return;
    }

    const responses = {
      scenario_only: {
        kicker: "SCENARIO FOUND",
        title: "This image does not contain a question",
        text: uploadMode === "question"
          ? "Because this was sent as a Question, it did not replace the saved context. Switch to Scenario if you want to save it."
          : "The scenario could not be saved. Please try a clearer image.",
      },
      review_without_question: {
        kicker: "REVIEW SCREEN FOUND",
        title: "I found a scenario, but no current question",
        text: uploadMode === "question"
          ? "Review feedback was ignored. Switch to Scenario if this should become your station context."
          : "Please send a clearer crop of the original scenario.",
      },
      question_only_context_missing: {
        kicker: "QUESTION FOUND",
        title: "This question needs its scenario",
        text: "Send the station context in Scenario mode first, then resend this question.",
      },
      multiple_questions: {
        kicker: "MORE THAN ONE QUESTION",
        title: "Show one question at a time",
        text: "Crop or retake the image so the one question you want help with is clearly the target.",
      },
      cropped_or_blurry: {
        kicker: "TEXT INCOMPLETE",
        title: "Some essential text could not be read",
        text: "Retake the current screen more closely and make sure no line is cut off.",
      },
      not_a_prompt: {
        kicker: "PROMPT NOT FOUND",
        title: "No MMI prompt was visible",
        text: "Choose an image containing a complete scenario or interview question.",
      },
    };
    const response = responses[status] || responses.cropped_or_blurry;
    const actions = [];
    if (status === "question_only_context_missing") {
      actions.push({ label: "Send the scenario", primary: true, run: () => setInputMode("scenario", { focus: true }) });
    } else if (isScenarioCapture && uploadMode === "question" && scenario) {
      actions.push({ label: "Resend as Scenario", primary: true, run: () => restoreForRetry(file, dataUrl, "scenario") });
    } else {
      actions.push({ label: "Try this image again", primary: true, run: () => restoreForRetry(file, dataUrl, uploadMode) });
    }
    appendSimpleResponse({
      ...response,
      transcript: "",
      actions,
    });
    if (question) {
      appendSimpleResponse({ kicker: "TEXT RECOGNISED", title: "Question text", text: question });
    }
    announce(`${response.title}. ${response.text}`);
  }

  function restoreForRetry(file, dataUrl, mode) {
    setInputMode(mode, { focus: true, speak: false });
    showAttachment(file, dataUrl);
  }

  async function sendCurrentImage() {
    if (!state.file || state.request) return;
    const file = state.file;
    const dataUrl = state.previewDataUrl;
    const uploadMode = state.inputMode;

    const stationContext = uploadMode === "question" ? state.stationContext : "";
    const previousQuestions = uploadMode === "question" && stationContext
      ? state.previousQuestions
      : [];

    appendUserMessage(dataUrl, uploadMode);
    clearAttachment();
    $("#scan-follow-up-actions").hidden = true;

    const request = { controller: new AbortController(), timeoutId: null };
    state.request = request;
    updateInterface();
    const loading = appendLoadingMessage(uploadMode, () => request.controller.abort());
    request.timeoutId = window.setTimeout(() => request.controller.abort(), 120000);

    const form = new FormData();
    form.append("image", file, file.name || "mmi-prompt.jpg");
    form.append("station_context", stationContext);
    form.append("previous_questions", JSON.stringify(previousQuestions));
    form.append("input_mode", uploadMode);

    try {
      const response = await fetch("/api/scan-coach", {
        method: "POST",
        body: form,
        signal: request.controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (state.request !== request) return;
      if (!response.ok) throw new Error(payload.error || "The image could not be analysed.");
      stopLoading(loading);
      if (payload.result?.scan_status === "ready") renderReady(payload.result, uploadMode);
      else renderNonReady(payload.result || {}, uploadMode, file, dataUrl);
    } catch (error) {
      if (state.request !== request) return;
      stopLoading(loading);
      const message = error?.name === "AbortError"
        ? "The scan took too long or was cancelled."
        : error?.message || "The image could not be analysed.";
      appendSimpleResponse({
        kicker: "SCAN INTERRUPTED",
        title: "This image was not analysed",
        text: message,
        actions: [{ label: "Try this image again", primary: true, run: () => restoreForRetry(file, dataUrl, uploadMode) }],
      });
      announce(message);
    } finally {
      window.clearTimeout(request.timeoutId);
      if (state.request === request) state.request = null;
      updateInterface();
    }
  }

  $$('[data-scan-mode]').forEach((button) => {
    button.addEventListener("click", () => setInputMode(button.dataset.scanMode));
  });
  $("#scan-camera-input").addEventListener("change", (event) => selectFile(event.target.files?.[0]));
  $("#scan-gallery-input").addEventListener("change", (event) => selectFile(event.target.files?.[0]));
  $("#scan-remove-image").addEventListener("click", clearAttachment);
  $("#scan-send").addEventListener("click", sendCurrentImage);
  $("#scan-next-question").addEventListener("click", () => setInputMode("question", { focus: true }));
  $("#scan-new-station-result").addEventListener("click", () => setInputMode("scenario", { focus: true }));
  $("#scan-edit-context").addEventListener("click", openContextEditor);
  $("#scan-clear-context").addEventListener("click", () => {
    clearContext();
    setInputMode("scenario", { focus: true, speak: false });
    appendSimpleResponse({ kicker: "CONTEXT CLEARED", title: "Ready for a new station", text: "Send a scenario, or switch to Question for a standalone prompt." });
  });

  const editDialog = $("#scan-edit-dialog");
  $("#scan-save-context").addEventListener("click", (event) => {
    event.preventDefault();
    const corrected = compactText($("#scan-context-editor").value);
    if (!corrected) {
      announce("The scenario cannot be empty.");
      $("#scan-context-editor").focus();
      return;
    }
    saveScenario(corrected, { clearQuestions: false });
    editDialog.close("save");
    appendSimpleResponse({ kicker: "SCENARIO UPDATED", title: "I will use the corrected text", text: "Later questions will use your edited version of the station context.", transcript: state.stationContext });
    announce("Scenario text updated.");
  });

  const dropZone = $("#scan-drop-zone");
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragging");
    });
  });
  dropZone.addEventListener("drop", (event) => selectFile(event.dataTransfer?.files?.[0]));

  updateInterface();
})();
