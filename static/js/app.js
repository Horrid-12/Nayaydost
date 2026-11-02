// @ts-check
/* global MediaRecorder, AudioContext, webkitAudioContext, SpeechSynthesisUtterance */

/**
 * NyayaDost frontend.
 *
 * The app is deliberately framework-free: one state object, small render
 * functions, and a single API helper that turns every failure into a
 * citizen-friendly message. All user or API text is inserted with
 * textContent, never innerHTML.
 */

/** @typedef {{ code: string, english_name: string, native_name: string, tts_lang: string }} LanguageOption */
/** @typedef {{ id: string, label: string, label_en: string, statute: string, severity: string }} NoticeTypeOption */
/** @typedef {{ id: string, title: string, description: string, notice_type: string, text: string }} SampleNotice */
/** @typedef {{ max_upload_mb: number, max_text_chars: number, max_tts_chars: number, max_pdf_pages: number }} AppLimits */
/** @typedef {{ version: string, mode: string, sarvam_configured: boolean, languages: LanguageOption[], notice_types: NoticeTypeOption[], samples: SampleNotice[], limits: AppLimits, generated_at: string }} BootstrapData */

const STORAGE = {
  theme: "nyayadost.theme",
  language: "nyayadost.language",
  checksPrefix: "nyayadost.checks.",
};

const TTS_LANG = {
  en: "en-IN",
  hi: "hi-IN",
  mr: "mr-IN",
  gu: "gu-IN",
  ta: "ta-IN",
  te: "te-IN",
  bn: "bn-IN",
};

const state = {
  /** @type {BootstrapData | null} */
  bootstrap: null,
  language: readStorage(STORAGE.language) || "en",
  theme: document.documentElement.getAttribute("data-theme") || "light",
  inputMode: "text",
  /** @type {File | null} */
  selectedFile: null,
  /** @type {string | null} */
  pdfUrl: null,
  /** @type {any} */
  analysis: null,
  /** @type {any} */
  guide: null,
  guideType: "cheque_bounce",
  guideLanguage: readStorage(STORAGE.language) || "en",
  /** @type {any} */
  aidOptions: null,
  /** @type {string | null} */
  aidState: null,
  recording: {
    /** @type {MediaRecorder | null} */
    recorder: null,
    /** @type {MediaStream | null} */
    stream: null,
    /** @type {Blob[]} */
    chunks: [],
    /** @type {number | null} */
    timer: null,
    startedAt: 0,
    /** @type {Blob | null} */
    blob: null,
  },
  audio: {
    /** @type {HTMLAudioElement | null} */
    element: null,
    /** @type {string | null} */
    url: null,
    /** @type {string | null} */
    analysisId: null,
    /** @type {number[]} */
    peaks: [],
  },
  speaking: false,
};

let toastTimer = null;
let stageTimer = null;

/* --------------------------------------------------------------------------
   Small DOM and utility helpers
   -------------------------------------------------------------------------- */

/**
 * @param {string} id
 * @returns {HTMLElement}
 */
function byId(id) {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error("Missing element #" + id);
  }
  return node;
}

/**
 * @param {string} id
 * @returns {HTMLInputElement}
 */
function inputById(id) {
  return /** @type {HTMLInputElement} */ (byId(id));
}

/**
 * @param {string} id
 * @returns {HTMLSelectElement}
 */
function selectById(id) {
  return /** @type {HTMLSelectElement} */ (byId(id));
}

/**
 * @param {string} id
 * @returns {HTMLTextAreaElement}
 */
function textareaById(id) {
  return /** @type {HTMLTextAreaElement} */ (byId(id));
}

/**
 * @param {string} tag
 * @param {string} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (typeof text === "string") node.textContent = text;
  return node;
}

/**
 * @param {string} id
 * @param {string} text
 */
function setText(id, text) {
  byId(id).textContent = text;
}

/**
 * @param {string} id
 * @param {boolean} visible
 */
function show(id, visible) {
  const node = byId(id);
  if (visible) node.removeAttribute("hidden");
  else node.setAttribute("hidden", "");
}

/**
 * @param {string} key
 * @returns {string | null}
 */
function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

/**
 * @param {string} key
 * @param {string} value
 */
function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (error) {
    /* Private browsing may block storage. The app still works. */
  }
}

/**
 * @param {number} ms
 * @returns {Promise<void>}
 */
function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * @param {string} template
 * @param {Record<string, string | number>} values
 * @returns {string}
 */
function formatTemplate(template, values) {
  let result = template;
  for (const key of Object.keys(values)) {
    result = result.split("{" + key + "}").join(String(values[key]));
  }
  return result;
}

/**
 * @param {string} message
 * @param {"info" | "success" | "error"} [kind]
 */
function showToast(message, kind = "info") {
  const toast = byId("toast");
  toast.textContent = message;
  toast.className = "toast is-visible" + (kind === "error" ? " is-error" : kind === "success" ? " is-success" : "");
  toast.removeAttribute("hidden");
  if (toastTimer !== null) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.classList.remove("is-visible");
    window.setTimeout(() => toast.setAttribute("hidden", ""), 220);
  }, 4200);
}

/**
 * @param {string} message
 * @param {string} [hint]
 * @param {"error" | "info"} [kind]
 */
function showInputError(message, hint, kind = "error") {
  const box = byId("input-error");
  box.textContent = "";
  const strong = el("strong", "", kind === "info" ? "A note on this result" : "We need a small correction");
  const body = el("span", "", message);
  box.appendChild(strong);
  box.appendChild(body);
  if (hint) {
    const hintNode = el("p", "field-hint", hint);
    box.appendChild(hintNode);
  }
  box.className = "inline-alert" + (kind === "info" ? " is-info" : "");
  box.removeAttribute("hidden");
}

function clearInputError() {
  const box = byId("input-error");
  box.textContent = "";
  box.setAttribute("hidden", "");
}

class ApiError extends Error {
  /**
   * @param {string} message
   * @param {{ hint?: string, code?: string, status?: number }} [options]
   */
  constructor(message, options = {}) {
    super(message);
    this.name = "ApiError";
    this.hint = options.hint || "";
    this.code = options.code || "network_error";
    this.status = options.status || 0;
  }
}

/**
 * Fetch JSON with a timeout and a single, friendly error shape.
 * @param {string} path
 * @param {RequestInit & { timeout?: number }} [options]
 * @returns {Promise<any>}
 */
async function api(path, options = {}) {
  const { timeout = 30000, ...init } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  const headers = new Headers(init.headers || {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");

  try {
    const response = await fetch(path, { ...init, headers, signal: controller.signal });
    const raw = await response.text();
    let payload = null;
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch (error) {
        payload = null;
      }
    }

    if (!response.ok || (payload && payload.ok === false)) {
      const detail = payload && payload.error ? payload.error : null;
      throw new ApiError(
        detail && detail.message
          ? detail.message
          : "The request could not be completed. Please try again.",
        {
          hint: detail && detail.hint ? detail.hint : "",
          code: detail && detail.code ? detail.code : "http_error",
          status: response.status,
        }
      );
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error && error.name === "AbortError") {
      throw new ApiError("NyayaDost took too long to respond.", {
        hint: "Check your connection and try again. A smaller PDF or pasted text is often faster.",
        code: "timeout",
      });
    }
    throw new ApiError("We could not reach NyayaDost.", {
      hint: "Check your internet connection and try again. Nothing you typed has been sent anywhere else.",
      code: "network_error",
    });
  } finally {
    window.clearTimeout(timer);
  }
}

/* --------------------------------------------------------------------------
   Theme
   -------------------------------------------------------------------------- */

/**
 * @param {string} theme
 */
function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  state.theme = next;
  document.documentElement.setAttribute("data-theme", next);
  writeStorage(STORAGE.theme, next);

  const toggle = byId("theme-toggle");
  toggle.setAttribute("aria-pressed", String(next === "dark"));
  toggle.setAttribute("aria-label", next === "dark" ? "Switch to light mode" : "Switch to dark mode");

  const metas = document.querySelectorAll('meta[name="theme-color"]');
  metas.forEach((meta) => {
    meta.setAttribute("content", next === "dark" ? "#0D1117" : "#FBF9F4");
  });

  if (state.audio.peaks.length) drawWaveform(state.audio.peaks);
}

function bindTheme() {
  applyTheme(state.theme);
  byId("theme-toggle").addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });
}

/* --------------------------------------------------------------------------
   Bootstrap
   -------------------------------------------------------------------------- */

/**
 * @param {HTMLSelectElement} select
 * @param {Array<{ value: string, label: string }>} options
 * @param {string} selected
 */
function populateSelect(select, options, selected) {
  select.textContent = "";
  for (const item of options) {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    if (item.value === selected) option.selected = true;
    select.appendChild(option);
  }
}

/**
 * @param {BootstrapData} data
 */
function applyBootstrap(data) {
  state.bootstrap = data;

  const modeChip = byId("mode-chip");
  modeChip.textContent = data.mode === "live" ? "Sarvam live" : "Offline demo";
  modeChip.classList.toggle("is-live", data.mode === "live");
  modeChip.removeAttribute("hidden");

  setText("footer-mode", data.mode === "live" ? "Sarvam live" : "Offline demo · local rulebook");
  setText("footer-version", "v" + data.version);
  setText("upload-limit", String(data.limits.max_upload_mb));

  const languageSelect = selectById("language-select");
  const languageOptions = data.languages.map((language) => ({
    value: language.code,
    label: language.native_name + " · " + language.english_name,
  }));
  const known = data.languages.some((language) => language.code === state.language);
  if (!known) state.language = "en";
  populateSelect(languageSelect, languageOptions, state.language);

  const guideLanguage = selectById("guide-language");
  const guideKnown = data.languages.some((language) => language.code === state.guideLanguage);
  if (!guideKnown) state.guideLanguage = state.language;
  populateSelect(guideLanguage, languageOptions, state.guideLanguage);

  const noticeOptions = data.notice_types.map((notice) => ({
    value: notice.id,
    label: notice.label,
  }));
  const guideType = selectById("guide-type");
  const guideTypeKnown = data.notice_types.some((notice) => notice.id === state.guideType);
  if (!guideTypeKnown && data.notice_types.length) state.guideType = data.notice_types[0].id;
  populateSelect(guideType, noticeOptions, state.guideType);

  renderSamples();
  updateAnalyzeState();
}

/**
 * @param {string} noticeType
 * @returns {string}
 */
function noticeLabel(noticeType) {
  if (!state.bootstrap) return noticeType.replace(/_/g, " ");
  const found = state.bootstrap.notice_types.find((notice) => notice.id === noticeType);
  return found ? found.label : noticeType.replace(/_/g, " ");
}

/**
 * @param {string} code
 * @returns {string}
 */
function languageName(code) {
  if (!state.bootstrap) return code;
  const found = state.bootstrap.languages.find((language) => language.code === code);
  return found ? found.native_name : code;
}

function renderSamples() {
  const list = byId("sample-list");
  list.textContent = "";
  if (!state.bootstrap || !state.bootstrap.samples.length) {
    const note = el("p", "field-hint", "Samples are unavailable right now. Paste your notice instead.");
    list.appendChild(note);
    return;
  }

  for (const sample of state.bootstrap.samples) {
    const card = el("div", "sample-card");
    const type = el("span", "sample-type", noticeLabel(sample.notice_type));
    const title = el("p", "sample-title", sample.title);
    const description = el("p", "sample-desc", sample.description);
    const button = el("button", "button tiny sample-load", "Load");
    button.setAttribute("type", "button");
    button.addEventListener("click", () => {
      const textarea = textareaById("notice-text");
      textarea.value = sample.text;
      updateCharCount();
      setInputMode("text");
      updateAnalyzeState();
      clearInputError();
      textarea.focus();
      textarea.scrollIntoView({ behavior: "smooth", block: "center" });
      showToast("Sample loaded. Press “Explain this notice”.", "success");
    });
    card.appendChild(type);
    card.appendChild(title);
    card.appendChild(description);
    card.appendChild(button);
    list.appendChild(card);
  }
}

async function loadBootstrap() {
  try {
    const data = await api("/api/bootstrap?language=" + encodeURIComponent(state.language));
    applyBootstrap(data);
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    showInputError(
      apiError.message || "We could not load the app data.",
      apiError.hint || "Refresh the page. If the server is starting, wait a few seconds and try again."
    );
    showToast("NyayaDost could not load its language list.", "error");
  }
}

/* --------------------------------------------------------------------------
   Input handling
   -------------------------------------------------------------------------- */

/**
 * @param {"text" | "upload" | "dictate"} mode
 */
function setInputMode(mode) {
  state.inputMode = mode;
  const tabs = document.querySelectorAll("[data-input-tab]");
  tabs.forEach((tab) => {
    const element = /** @type {HTMLElement} */ (tab);
    const active = element.dataset.inputTab === mode;
    element.classList.toggle("is-active", active);
    element.setAttribute("aria-selected", String(active));
  });
  const panels = ["text", "upload", "dictate"];
  for (const panel of panels) {
    const node = byId("tab-" + panel);
    if (panel === mode) node.removeAttribute("hidden");
    else node.setAttribute("hidden", "");
  }
}

function updateCharCount() {
  const textarea = textareaById("notice-text");
  const count = textarea.value.length;
  const limit = state.bootstrap ? state.bootstrap.limits.max_text_chars : 50000;
  const label = count.toLocaleString("en-IN") + " characters";
  setText("char-count", count > limit ? label + " · over the limit" : label);
  byId("char-count").style.color = count > limit ? "var(--danger)" : "";
}

function updateAnalyzeState() {
  const textarea = textareaById("notice-text");
  const textLength = textarea.value.trim().length;
  const limit = state.bootstrap ? state.bootstrap.limits.max_text_chars : 50000;
  const hasUsableText = textLength >= 30 && textLength <= limit;
  const hasFile = state.selectedFile !== null;
  inputById("analyze-button").disabled = !(hasUsableText || hasFile);
}

function bindInput() {
  const textarea = textareaById("notice-text");
  textarea.addEventListener("input", () => {
    updateCharCount();
    updateAnalyzeState();
    if (!byId("input-error").hasAttribute("hidden")) clearInputError();
  });
  textarea.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (!inputById("analyze-button").disabled) analyzeNotice();
    }
  });

  byId("clear-text").addEventListener("click", () => {
    textarea.value = "";
    updateCharCount();
    updateAnalyzeState();
    clearInputError();
    textarea.focus();
  });

  document.querySelectorAll("[data-input-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const mode = /** @type {HTMLElement} */ (tab).dataset.inputTab;
      if (mode === "text" || mode === "upload" || mode === "dictate") setInputMode(mode);
    });
  });

  byId("analyze-button").addEventListener("click", analyzeNotice);
  updateCharCount();
  updateAnalyzeState();
}

function bindUpload() {
  const dropzone = byId("dropzone");
  const fileInput = inputById("pdf-input");

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
    });
  });
  dropzone.addEventListener("drop", (event) => {
    const dragEvent = /** @type {DragEvent} */ (event);
    const files = dragEvent.dataTransfer && dragEvent.dataTransfer.files;
    if (files && files.length) selectPdf(files[0]);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length) selectPdf(fileInput.files[0]);
  });

  byId("remove-file").addEventListener("click", clearSelectedPdf);
  byId("pdf-open").addEventListener("click", (event) => {
    if (!state.pdfUrl) event.preventDefault();
  });

  document.querySelectorAll("[data-pdf-zoom]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!state.pdfUrl) return;
      const zoom = /** @type {HTMLElement} */ (button).dataset.pdfZoom || "page-width";
      const frame = /** @type {HTMLIFrameElement} */ (byId("pdf-frame"));
      frame.src = state.pdfUrl + "#zoom=" + zoom + "&toolbar=1&navpanes=0";
    });
  });
}

/**
 * @param {File} file
 */
function selectPdf(file) {
  clearInputError();
  const limitMb = state.bootstrap ? state.bootstrap.limits.max_upload_mb : 10;
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (!isPdf) {
    showInputError("That file is not a PDF.", "Choose a PDF file, or paste the notice text in the text tab.");
    showToast("Please choose a PDF file.", "error");
    return;
  }
  if (file.size > limitMb * 1024 * 1024) {
    showInputError(
      "That PDF is larger than " + limitMb + " MB.",
      "Upload a smaller PDF, or paste only the notice text."
    );
    showToast("That PDF is too large.", "error");
    return;
  }

  if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
  state.selectedFile = file;
  state.pdfUrl = URL.createObjectURL(file);

  setText("file-name", file.name);
  setText("file-size", formatBytes(file.size) + " · PDF preview below");
  const frame = /** @type {HTMLIFrameElement} */ (byId("pdf-frame"));
  frame.src = state.pdfUrl + "#zoom=page-width&toolbar=1&navpanes=0";
  const openLink = /** @type {HTMLAnchorElement} */ (byId("pdf-open"));
  openLink.href = state.pdfUrl;
  show("file-preview", true);
  updateAnalyzeState();
  showToast("PDF selected. Press “Explain this notice”.", "success");
}

function clearSelectedPdf() {
  if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
  state.pdfUrl = null;
  state.selectedFile = null;
  inputById("pdf-input").value = "";
  const frame = /** @type {HTMLIFrameElement} */ (byId("pdf-frame"));
  frame.removeAttribute("src");
  show("file-preview", false);
  updateAnalyzeState();
}

/**
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

/* --------------------------------------------------------------------------
   Dictation
   -------------------------------------------------------------------------- */

function bindDictation() {
  const recordButton = byId("record-button");
  recordButton.addEventListener("click", () => {
    if (state.recording.recorder && state.recording.recorder.state === "recording") {
      stopRecording();
    } else {
      startRecording();
    }
  });

  byId("record-stop").addEventListener("click", stopRecording);
  byId("record-discard").addEventListener("click", discardRecording);
  byId("use-transcript").addEventListener("click", transcribeRecording);

  inputById("audio-input").addEventListener("change", () => {
    const input = inputById("audio-input");
    const file = input.files && input.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      showInputError("That recording is larger than 10 MB.", "Record a shorter message, or upload a smaller audio file.");
      return;
    }
    state.recording.blob = file;
    const playback = /** @type {HTMLAudioElement} */ (byId("record-playback"));
    playback.src = URL.createObjectURL(file);
    playback.removeAttribute("hidden");
    show("use-transcript", true);
    clearInputError();
    showToast("Audio ready. Transcribe it when you are ready.", "success");
  });
}

async function startRecording() {
  clearInputError();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
    showInputError(
      "Your browser cannot record audio here.",
      "Use Chrome, Edge, Firefox, or Safari over HTTPS (or localhost), or upload an audio file below."
    );
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickRecordingMime();
    const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    state.recording.stream = stream;
    state.recording.recorder = recorder;
    state.recording.chunks = [];
    state.recording.startedAt = Date.now();

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) state.recording.chunks.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      const blob = new Blob(state.recording.chunks, { type: recorder.mimeType || "audio/webm" });
      state.recording.blob = blob;
      const playback = /** @type {HTMLAudioElement} */ (byId("record-playback"));
      if (playback.src) URL.revokeObjectURL(playback.src);
      playback.src = URL.createObjectURL(blob);
      playback.removeAttribute("hidden");
      show("use-transcript", true);
      show("record-actions", false);
      stopStream();
      state.recording.recorder = null;
    });

    recorder.start();
    byId("record-button").setAttribute("aria-pressed", "true");
    setText("record-label", "Stop recording");
    setText("record-hint", "Recording… speak clearly and include the date, sender, and amount.");
    show("record-actions", true);
    show("use-transcript", false);
    byId("record-timer").removeAttribute("hidden");
    state.recording.timer = window.setInterval(updateRecordingTimer, 250);
    updateRecordingTimer();
  } catch (error) {
    const message =
      error && (error.name === "NotAllowedError" || error.name === "SecurityError")
        ? "Microphone permission was not granted."
        : "We could not start the microphone.";
    showInputError(
      message,
      "Allow microphone access in your browser settings, or upload an audio file instead."
    );
    showToast(message, "error");
  }
}

function pickRecordingMime() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  for (const candidate of candidates) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return "";
}

function stopRecording() {
  const recorder = state.recording.recorder;
  if (recorder && recorder.state !== "inactive") recorder.stop();
  if (state.recording.timer !== null) {
    window.clearInterval(state.recording.timer);
    state.recording.timer = null;
  }
  byId("record-button").setAttribute("aria-pressed", "false");
  setText("record-label", "Start recording");
  setText("record-hint", "Recording stopped. Play it back, or transcribe it with Sarvam Saaras.");
}

function discardRecording() {
  stopRecording();
  stopStream();
  state.recording.blob = null;
  state.recording.chunks = [];
  const playback = /** @type {HTMLAudioElement} */ (byId("record-playback"));
  playback.pause();
  if (playback.src) URL.revokeObjectURL(playback.src);
  playback.removeAttribute("src");
  playback.setAttribute("hidden", "");
  show("use-transcript", false);
  show("record-actions", false);
  byId("record-timer").textContent = "00:00";
  setText("record-hint", "Speak the notice aloud. Your browser may ask for microphone permission.");
}

function stopStream() {
  if (state.recording.stream) {
    state.recording.stream.getTracks().forEach((track) => track.stop());
    state.recording.stream = null;
  }
}

function updateRecordingTimer() {
  const elapsed = Math.max(0, Math.floor((Date.now() - state.recording.startedAt) / 1000));
  const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const seconds = String(elapsed % 60).padStart(2, "0");
  byId("record-timer").textContent = minutes + ":" + seconds;
}

async function transcribeRecording() {
  const blob = state.recording.blob;
  if (!blob) {
    showInputError("There is no recording to transcribe.", "Record a message first, or upload an audio file.");
    return;
  }
  const button = byId("use-transcript");
  button.setAttribute("disabled", "");
  const originalLabel = button.textContent || "Use this transcript";
  button.textContent = "Transcribing…";
  clearInputError();
  try {
    const form = new FormData();
    form.append("file", blob, "dictation.webm");
    form.append("language", state.language);
    const data = await api("/api/stt", { method: "POST", body: form, timeout: 60000 });
    const textarea = textareaById("notice-text");
    textarea.value = data.transcript || "";
    updateCharCount();
    updateAnalyzeState();
    setInputMode("text");
    textarea.focus();
    if (data.warning) {
      showInputError(data.warning, "You can edit the transcript before analysing it.", "info");
    } else {
      showToast("Transcript ready. Check it before analysing.", "success");
    }
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    showInputError(apiError.message, apiError.hint);
    showToast(apiError.message, "error");
  } finally {
    button.removeAttribute("disabled");
    button.textContent = originalLabel;
  }
}

/* --------------------------------------------------------------------------
   Analysis
   -------------------------------------------------------------------------- */

function setStage(name, status) {
  const item = document.querySelector('#processing-stages li[data-stage="' + name + '"]');
  if (!item) return;
  item.classList.remove("is-active", "is-done");
  if (status === "active") item.classList.add("is-active");
  if (status === "done") item.classList.add("is-done");
}

function startProcessing() {
  clearInputError();
  show("processing", true);
  show("empty-state", false);
  show("result-root", false);
  setText("result-panel-note", "Reading the notice");
  const stages = ["parse", "distil", "translate"];
  stages.forEach((stage) => setStage(stage, ""));
  setStage("parse", "active");
  let index = 0;
  if (stageTimer !== null) window.clearInterval(stageTimer);
  stageTimer = window.setInterval(() => {
    if (index < stages.length - 1) {
      setStage(stages[index], "done");
      index += 1;
      setStage(stages[index], "active");
    }
  }, 700);
}

async function finishProcessing() {
  if (stageTimer !== null) {
    window.clearInterval(stageTimer);
    stageTimer = null;
  }
  ["parse", "distil", "translate"].forEach((stage) => setStage(stage, "done"));
  await delay(280);
}

function stopProcessing() {
  if (stageTimer !== null) {
    window.clearInterval(stageTimer);
    stageTimer = null;
  }
  show("processing", false);
}

/**
 * @param {() => Promise<any>} requestFactory
 */
async function performAnalysis(requestFactory) {
  const hadResult = Boolean(state.analysis);
  startProcessing();
  const started = Date.now();
  try {
    const data = await requestFactory();
    const remaining = Math.max(0, 1400 - (Date.now() - started));
    if (remaining) await delay(remaining);
    await finishProcessing();
    state.analysis = data;
    renderAnalysis(data);
    stopProcessing();
    show("empty-state", false);
    show("result-root", true);
    setText("result-panel-note", "Explained just now");
    document.title = data.notice_type_label_en + " — NyayaDost";
    if (window.innerWidth < 980) {
      byId("result-root").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    stopProcessing();
    if (hadResult) show("result-root", true);
    else show("empty-state", true);
    setText("result-panel-note", hadResult ? "Previous result kept" : "Waiting for a notice");
    const apiError = /** @type {ApiError} */ (error);
    showInputError(apiError.message, apiError.hint);
    showToast(apiError.message, "error");
  }
}

async function analyzeNotice() {
  const textarea = textareaById("notice-text");
  const text = textarea.value.trim();
  const limit = state.bootstrap ? state.bootstrap.limits.max_text_chars : 50000;

  if (state.inputMode === "upload" && state.selectedFile) {
    const form = new FormData();
    form.append("file", state.selectedFile, state.selectedFile.name);
    form.append("language", state.language);
    await performAnalysis(() => api("/api/analyze/upload", { method: "POST", body: form, timeout: 45000 }));
    return;
  }

  if (text.length < 30) {
    showInputError(
      "Please add at least a few lines of the notice.",
      "Paste the text, upload a PDF, or load a sample. Thirty characters is the minimum."
    );
    showToast("Add the notice text first.", "error");
    return;
  }
  if (text.length > limit) {
    showInputError(
      "This notice is longer than the " + limit.toLocaleString("en-IN") + " character limit.",
      "Paste only the notice pages that contain the demand and the deadline."
    );
    return;
  }

  await performAnalysis(() =>
    api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language: state.language, source_name: "Pasted notice" }),
      timeout: 45000,
    })
  );
}

/* --------------------------------------------------------------------------
   Result rendering
   -------------------------------------------------------------------------- */

/**
 * @param {any} data
 */
function renderAnalysis(data) {
  const labels = data.labels || {};
  setText("result-kicker", data.notice_type_label_en + " · " + displayDate(data.generated_at));
  setText("result-type", data.notice_type_label);
  setText("result-statute", data.statute || "");
  setText("confidence-value", Math.round(data.confidence * 100) + "%");
  byId("confidence-ring").style.setProperty("--confidence", String(Math.round(data.confidence * 100)));

  const badgeRow = byId("badge-row");
  badgeRow.textContent = "";
  badgeRow.appendChild(makeBadge(data.mode === "live" ? "Sarvam live" : "Offline rulebook", data.mode === "live" ? "is-live" : "is-offline"));
  badgeRow.appendChild(makeBadge(languageName(data.language), ""));
  if (data.degraded) badgeRow.appendChild(makeBadge("Fallback used", "is-warning"));
  if (data.source && data.source.kind === "pdf") badgeRow.appendChild(makeBadge("PDF", ""));

  const warning = byId("result-warning");
  if (data.warning) {
    warning.textContent = data.warning;
    warning.removeAttribute("hidden");
  } else {
    warning.textContent = "";
    warning.setAttribute("hidden", "");
  }

  setText("summary-label", labels.summary || "What This Notice Means");
  setText("deadline-label", labels.deadlines || "Critical Deadlines");
  setText("steps-label", labels.steps || "Immediate Next Steps");
  setText("audio-label", labels.audio || "Listen to this explanation");
  setText("original-label", labels.original || "Original Legalese");
  setText("glossary-label", labels.glossary || "Legal Terms, Decoded");
  setText("reply-label", labels.reply || "Reply Draft");
  setText("summary-title", data.notice_type_label || "Summary");
  setText("summary-body", data.summary_body || "");
  setText("original-text", data.original_text || "");
  setText("result-disclaimer", data.disclaimer || "");

  renderFacts(data.facts || []);
  renderDeadlines(data.deadlines || [], labels);
  renderSteps(data.steps || [], data.analysis_id, labels);
  renderGlossary(data.glossary || []);
  renderReply(data.reply || {}, labels);
  resetAudio(data);
  resetTranslation();

  setText("audio-title", "Listen in " + languageName(data.language));
  setText("audio-note", "Load a spoken explanation from Sarvam Bulbul, or use your device voice.");
  byId("audio-load").textContent = "Load audio";
  byId("audio-load").removeAttribute("disabled");

  switchResultTab("breakdown");
}

/**
 * @param {string} text
 * @param {string} className
 * @returns {HTMLElement}
 */
function makeBadge(text, className) {
  const badge = el("span", "badge " + className, text);
  return badge;
}

/**
 * @param {string} iso
 * @returns {string}
 */
function displayDate(iso) {
  if (!iso) return "";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "";
  return value.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/**
 * @param {Array<{ label: string, value: string }>} facts
 */
function renderFacts(facts) {
  const strip = byId("facts-strip");
  strip.textContent = "";
  for (const fact of facts) {
    const item = el("div", "fact-item");
    item.appendChild(el("span", "fact-label", fact.label));
    item.appendChild(el("span", "fact-value", fact.value));
    strip.appendChild(item);
  }
  if (!facts.length) {
    const item = el("div", "fact-item");
    item.appendChild(el("span", "fact-label", "Key facts"));
    item.appendChild(el("span", "fact-value", "Read the notice text for the full facts."));
    strip.appendChild(item);
  }
}

/**
 * @param {Array<any>} deadlines
 * @param {Record<string, string>} labels
 */
function renderDeadlines(deadlines, labels) {
  const grid = byId("deadline-grid");
  grid.textContent = "";
  for (const deadline of deadlines) {
    const severity = ["critical", "warning", "normal"].includes(deadline.severity) ? deadline.severity : "warning";
    const card = el("article", "deadline-card severity-" + severity);
    const top = el("div", "deadline-top");
    const label = el("p", "deadline-label", deadline.label || "Response deadline");
    const days = el("div", "deadline-days");
    const remaining = Number(deadline.days_remaining);
    const overdue = remaining < 0;
    const number = el("strong", "", String(Math.abs(remaining)));
    const unit = el(
      "small",
      "",
      overdue
        ? labels.overdue || "Deadline has passed"
        : remaining === 0
          ? labels.due_today || "Due today"
          : formatTemplate(labels.days_left || "{days} days left", { days: remaining })
    );
    days.appendChild(number);
    days.appendChild(unit);
    top.appendChild(label);
    top.appendChild(days);
    card.appendChild(top);
    card.appendChild(el("p", "deadline-date", deadline.date_display || deadline.date));
    card.appendChild(el("span", "deadline-source", deadline.source_label || ""));
    if (deadline.note) card.appendChild(el("p", "deadline-note", deadline.note));
    grid.appendChild(card);
  }
  if (!deadlines.length) {
    grid.appendChild(el("p", "field-hint", "No deadline could be read from this notice. Treat 15 days from receipt as a working date and confirm with an advocate."));
  }
}

/**
 * @param {Array<any>} steps
 * @param {string} analysisId
 * @param {Record<string, string>} labels
 */
function renderSteps(steps, analysisId, labels) {
  const list = byId("steps-list");
  list.textContent = "";
  const storageKey = STORAGE.checksPrefix + analysisId;
  let checked = [];
  try {
    const raw = window.localStorage.getItem(storageKey);
    checked = raw ? JSON.parse(raw) : [];
  } catch (error) {
    checked = [];
  }
  if (!Array.isArray(checked)) checked = [];

  const ordered = steps.slice().sort((a, b) => Number(a.priority) - Number(b.priority));
  for (const step of ordered) {
    const item = el("li", "step-item");
    const checkbox = /** @type {HTMLInputElement} */ (document.createElement("input"));
    checkbox.type = "checkbox";
    checkbox.className = "step-check";
    checkbox.id = "step-" + step.id;
    checkbox.setAttribute("aria-label", step.title);
    checkbox.checked = checked.includes(step.id);
    item.classList.toggle("is-done", checkbox.checked);

    const body = el("div", "step-body");
    const titleLine = el("div", "step-title");
    titleLine.appendChild(el("span", "step-number", String(step.priority).padStart(2, "0")));
    titleLine.appendChild(document.createTextNode(step.title));
    body.appendChild(titleLine);
    if (step.detail) body.appendChild(el("p", "step-detail", step.detail));

    checkbox.addEventListener("change", () => {
      item.classList.toggle("is-done", checkbox.checked);
      const current = new Set(readChecked(storageKey));
      if (checkbox.checked) current.add(step.id);
      else current.delete(step.id);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(Array.from(current)));
      } catch (error) {
        /* Storage is a convenience, not a requirement. */
      }
      updateStepProgress();
    });

    item.appendChild(checkbox);
    item.appendChild(body);
    list.appendChild(item);
  }

  setText("steps-progress-label", formatTemplate(labels.checklist_progress || "{done} of {total} steps completed", {
    done: 0,
    total: ordered.length,
  }));
  updateStepProgress();
}

/**
 * @param {string} storageKey
 * @returns {string[]}
 */
function readChecked(storageKey) {
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch (error) {
    return [];
  }
}

function updateStepProgress() {
  const list = byId("steps-list");
  const checks = list.querySelectorAll(".step-check");
  const total = checks.length;
  let done = 0;
  checks.forEach((check) => {
    if (/** @type {HTMLInputElement} */ (check).checked) done += 1;
  });
  const ratio = total ? (done / total) * 100 : 0;
  const bar = byId("steps-progress-bar");
  bar.style.width = ratio + "%";
  const labelTemplate =
    state.analysis && state.analysis.labels && state.analysis.labels.checklist_progress
      ? state.analysis.labels.checklist_progress
      : "{done} of {total} steps completed";
  setText("steps-progress-label", formatTemplate(labelTemplate, { done, total }));
}

/**
 * @param {Array<{ term: string, meaning: string }>} glossary
 */
function renderGlossary(glossary) {
  const list = byId("glossary-list");
  list.textContent = "";
  for (const item of glossary) {
    const row = el("div", "glossary-item");
    row.appendChild(el("dt", "glossary-term", item.term));
    row.appendChild(el("dd", "glossary-meaning", item.meaning));
    list.appendChild(row);
  }
  if (!glossary.length) {
    const row = el("div", "glossary-item");
    row.appendChild(el("dt", "glossary-term", "No glossary terms"));
    row.appendChild(el("dd", "glossary-meaning", "This notice did not contain a term from the curated glossary."));
    list.appendChild(row);
  }
}

/**
 * @param {{ subject?: string, note?: string, template?: string }} reply
 * @param {Record<string, string>} labels
 */
function renderReply(reply, labels) {
  setText("reply-subject", reply.subject || labels.reply || "Reply to the notice");
  setText("reply-note", reply.note || labels.reply_note || "");
  setText("reply-template", reply.template || "");
}

/* --------------------------------------------------------------------------
   Result tabs, copy, share, print
   -------------------------------------------------------------------------- */

/**
 * @param {string} tab
 */
function switchResultTab(tab) {
  const tabs = document.querySelectorAll("[data-result-tab]");
  tabs.forEach((button) => {
    const element = /** @type {HTMLElement} */ (button);
    const active = element.dataset.resultTab === tab;
    element.classList.toggle("is-active", active);
    element.setAttribute("aria-selected", String(active));
  });
  const panels = ["breakdown", "original", "glossary", "reply"];
  for (const panel of panels) {
    if (panel === tab) byId("tab-" + panel).removeAttribute("hidden");
    else byId("tab-" + panel).setAttribute("hidden", "");
  }
}

function bindResultTabs() {
  document.querySelectorAll("[data-result-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = /** @type {HTMLElement} */ (button).dataset.resultTab;
      if (tab) switchResultTab(tab);
    });
  });
}

/**
 * @param {string} text
 * @returns {Promise<void>}
 */
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(area);
  if (!copied) throw new Error("Copy failed");
}

function bindResultActions() {
  byId("copy-summary").addEventListener("click", async () => {
    if (!state.analysis) return;
    try {
      await copyText(state.analysis.summary_title + "\n\n" + state.analysis.summary_body);
      showToast("Summary copied to the clipboard.", "success");
    } catch (error) {
      showToast("Copy did not work in this browser. Select the text and copy it manually.", "error");
    }
  });

  byId("copy-reply").addEventListener("click", async () => {
    if (!state.analysis) return;
    try {
      await copyText(state.analysis.reply.template || "");
      showToast("Reply draft copied. Fill in the blanks before sending.", "success");
    } catch (error) {
      showToast("Copy did not work in this browser. Select the draft and copy it manually.", "error");
    }
  });

  byId("print-button").addEventListener("click", () => window.print());
  byId("print-reply").addEventListener("click", () => window.print());

  byId("share-button").addEventListener("click", async () => {
    if (!state.analysis) return;
    const text = buildShareText(state.analysis);
    if (navigator.share) {
      try {
        await navigator.share({ title: state.analysis.notice_type_label, text });
        return;
      } catch (error) {
        if (error && error.name === "AbortError") return;
      }
    }
    try {
      await copyText(text);
      showToast("Checklist copied. Paste it into WhatsApp or email.", "success");
    } catch (error) {
      showToast("Sharing is not available in this browser.", "error");
    }
  });

  byId("speak-summary").addEventListener("click", () => {
    if (!state.analysis) return;
    if (state.speaking && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      state.speaking = false;
      return;
    }
    const deadlines = state.analysis.deadlines
      .map((deadline) => deadline.label + ": " + deadline.date_display)
      .join(". ");
    const text =
      state.analysis.summary_body +
      " " +
      (deadlines ? state.analysis.labels.response_deadline + ": " + deadlines : "");
    speakText(text, state.analysis.language);
  });

  byId("device-voice").addEventListener("click", () => {
    if (!state.analysis) return;
    const steps = state.analysis.steps.slice(0, 4).map((step) => step.title).join(". ");
    speakText(
      state.analysis.summary_title + ". " + state.analysis.summary_body + ". " + steps,
      state.analysis.language
    );
  });

  byId("translate-button").addEventListener("click", translateOriginal);
}

/**
 * @param {any} data
 * @returns {string}
 */
function buildShareText(data) {
  const deadlines = data.deadlines
    .map((deadline) => "• " + deadline.label + " — " + deadline.date_display + " (" + deadline.source_label + ")")
    .join("\n");
  const steps = data.steps
    .slice()
    .sort((a, b) => a.priority - b.priority)
    .map((step, index) => (index + 1) + ". " + step.title)
    .join("\n");
  return (
    data.notice_type_label +
    "\n\n" +
    data.summary_body +
    "\n\n" +
    (data.labels.deadlines || "Critical Deadlines") +
    ":\n" +
    (deadlines || "No deadline found.") +
    "\n\n" +
    (data.labels.steps || "Immediate Next Steps") +
    ":\n" +
    steps +
    "\n\n" +
    data.disclaimer +
    "\n\nShared from NyayaDost"
  );
}

/**
 * @param {string} text
 * @param {string} language
 */
function speakText(text, language) {
  if (!("speechSynthesis" in window)) {
    showToast("Your browser does not support the device voice. Load the Sarvam audio instead.", "error");
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = TTS_LANG[language] || "en-IN";
  utterance.rate = 0.95;
  utterance.pitch = 1;
  const voices = window.speechSynthesis.getVoices();
  const match =
    voices.find((voice) => voice.lang === utterance.lang) ||
    voices.find((voice) => voice.lang && voice.lang.split("-")[0] === language);
  if (match) utterance.voice = match;
  utterance.addEventListener("start", () => {
    state.speaking = true;
    setText("speak-summary", "◼ Stop reading");
  });
  utterance.addEventListener("end", () => {
    state.speaking = false;
    setText("speak-summary", "◉ Read aloud");
  });
  utterance.addEventListener("error", () => {
    state.speaking = false;
    setText("speak-summary", "◉ Read aloud");
    showToast("The device voice could not read this text.", "error");
  });
  window.speechSynthesis.speak(utterance);
}

/* --------------------------------------------------------------------------
   Translation
   -------------------------------------------------------------------------- */

function resetTranslation() {
  show("translated-text", false);
  show("translation-warning", false);
  byId("translation-warning").textContent = "";
  byId("translate-button").removeAttribute("disabled");
  byId("translate-button").textContent = "Translate the original";
}

async function translateOriginal() {
  if (!state.analysis) return;
  const button = byId("translate-button");
  button.setAttribute("disabled", "");
  button.textContent = "Translating…";
  show("translation-warning", false);
  show("translated-text", false);
  try {
    const data = await api("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: state.analysis.original_text,
        target_language: state.language,
        source_language: "auto",
      }),
      timeout: 45000,
    });
    const warning = byId("translation-warning");
    if (data.warning) {
      warning.textContent = data.warning;
      warning.className = "inline-alert is-info";
      warning.removeAttribute("hidden");
    }
    const output = byId("translated-text");
    output.textContent = data.translated_text || "";
    output.removeAttribute("hidden");
    if (!data.warning) showToast("Translation ready.", "success");
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    const warning = byId("translation-warning");
    warning.textContent = apiError.message + (apiError.hint ? " " + apiError.hint : "");
    warning.className = "inline-alert";
    warning.removeAttribute("hidden");
    showToast(apiError.message, "error");
  } finally {
    button.removeAttribute("disabled");
    button.textContent = "Translate the original";
  }
}

/* --------------------------------------------------------------------------
   Audio player
   -------------------------------------------------------------------------- */

function resetAudio(data) {
  cleanupAudio();
  setText("audio-note", "Load a spoken explanation from Sarvam Bulbul, or use your device voice.");
  if (data) setText("audio-title", "Listen in " + languageName(data.language));
}

function cleanupAudio() {
  if (state.audio.element) {
    state.audio.element.pause();
    state.audio.element.removeAttribute("src");
    state.audio.element.load();
  }
  if (state.audio.url) URL.revokeObjectURL(state.audio.url);
  state.audio = { element: null, url: null, analysisId: null, peaks: [] };
  show("audio-player", false);
  show("audio-controls", false);
  byId("wave-progress").style.width = "0%";
  setText("audio-time", "0:00 / 0:00");
  setText("audio-play", "▶");
  byId("audio-play").setAttribute("aria-label", "Play audio");
}

function bindAudio() {
  byId("audio-load").addEventListener("click", loadAudio);
  byId("audio-play").addEventListener("click", toggleAudioPlayback);
  byId("waveform").addEventListener("pointerdown", beginScrub);
  byId("waveform").addEventListener("pointermove", moveScrub);
  byId("waveform").addEventListener("pointerup", endScrub);
  byId("waveform").addEventListener("pointercancel", endScrub);

  document.querySelectorAll("[data-speed]").forEach((button) => {
    button.addEventListener("click", () => {
      const speed = Number(/** @type {HTMLElement} */ (button).dataset.speed || "1");
      if (state.audio.element) state.audio.element.playbackRate = speed;
      document.querySelectorAll("[data-speed]").forEach((other) => {
        other.classList.toggle("is-active", other === button);
      });
    });
  });
}

let scrubbing = false;

/**
 * @param {PointerEvent} event
 */
function beginScrub(event) {
  if (!state.audio.element) return;
  scrubbing = true;
  /** @type {HTMLElement} */ (event.currentTarget).setPointerCapture(event.pointerId);
  seekFromPointer(event);
}

/**
 * @param {PointerEvent} event
 */
function moveScrub(event) {
  if (!scrubbing) return;
  seekFromPointer(event);
}

function endScrub() {
  scrubbing = false;
}

/**
 * @param {PointerEvent} event
 */
function seekFromPointer(event) {
  const audio = state.audio.element;
  if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
  const target = /** @type {HTMLElement} */ (event.currentTarget);
  const rect = target.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  audio.currentTime = ratio * audio.duration;
  updateAudioProgress();
}

async function loadAudio() {
  if (!state.analysis) return;
  if (state.audio.element && state.audio.analysisId === state.analysis.analysis_id) {
    toggleAudioPlayback();
    return;
  }
  const button = byId("audio-load");
  button.setAttribute("disabled", "");
  button.textContent = "Preparing…";
  setText("audio-note", "Sarvam is preparing the spoken explanation…");
  try {
    const data = await api("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: state.analysis.tts_text, language: state.language, pace: 1 }),
      timeout: 60000,
    });
    setupAudio(data);
    button.textContent = "Reload audio";
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    setText("audio-note", apiError.message + (apiError.hint ? " " + apiError.hint : ""));
    showToast(apiError.message, "error");
    button.textContent = "Load audio";
  } finally {
    button.removeAttribute("disabled");
  }
}

/**
 * @param {any} data
 */
function setupAudio(data) {
  cleanupAudio();
  let binary;
  try {
    binary = window.atob(data.audio_base64 || "");
  } catch (error) {
    setText("audio-note", "The audio data could not be decoded. Try loading it again.");
    showToast("The audio could not be decoded.", "error");
    return;
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const blob = new Blob([bytes], { type: data.mime_type || "audio/wav" });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.preload = "auto";
  state.audio.element = audio;
  state.audio.url = url;
  state.audio.analysisId = state.analysis ? state.analysis.analysis_id : null;
  state.audio.peaks = pseudoWaveform(data.transcript || "nyayadost");

  show("audio-player", true);
  show("audio-controls", true);
  drawWaveform(state.audio.peaks);

  audio.addEventListener("timeupdate", updateAudioProgress);
  audio.addEventListener("loadedmetadata", updateAudioProgress);
  audio.addEventListener("ended", () => {
    setText("audio-play", "▶");
    byId("audio-play").setAttribute("aria-label", "Play audio");
  });
  audio.addEventListener("error", () => {
    setText("audio-note", "The audio could not be played. Try loading it again, or use the device voice.");
  });

  const warning = data.warning || "";
  setText(
    "audio-note",
    warning ||
      (data.is_mock
        ? "Demo audio is a soft tone, not speech. Use the device voice button to hear the full explanation."
        : "Spoken explanation generated by Sarvam Bulbul.")
  );

  decodeWaveform(blob).then((peaks) => {
    if (peaks.length && state.audio.element === audio) {
      state.audio.peaks = peaks;
      drawWaveform(peaks);
    }
  });

  audio.play().catch(() => {
    setText("audio-play", "▶");
    byId("audio-play").setAttribute("aria-label", "Play audio");
  });
}

function toggleAudioPlayback() {
  const audio = state.audio.element;
  if (!audio) {
    loadAudio();
    return;
  }
  if (audio.paused) {
    audio.play().catch(() => {
      showToast("The browser blocked audio playback. Press play again.", "error");
    });
  } else {
    audio.pause();
  }
  const playing = !audio.paused;
  setText("audio-play", playing ? "❚❚" : "▶");
  byId("audio-play").setAttribute("aria-label", playing ? "Pause audio" : "Play audio");
}

function updateAudioProgress() {
  const audio = state.audio.element;
  if (!audio) return;
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  const current = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
  const ratio = duration > 0 ? current / duration : 0;
  byId("wave-progress").style.width = Math.max(0, Math.min(100, ratio * 100)) + "%";
  setText("audio-time", formatTime(current) + " / " + formatTime(duration));
  const playing = !audio.paused && !audio.ended;
  setText("audio-play", playing ? "❚❚" : "▶");
  byId("audio-play").setAttribute("aria-label", playing ? "Pause audio" : "Play audio");
}

/**
 * @param {number} seconds
 * @returns {string}
 */
function formatTime(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(safe / 60);
  return minutes + ":" + String(safe % 60).padStart(2, "0");
}

/**
 * @param {string} seed
 * @returns {number[]}
 */
function pseudoWaveform(seed) {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const bars = 120;
  const values = [];
  let current = hash >>> 0;
  for (let index = 0; index < bars; index += 1) {
    current = (Math.imul(current, 1664525) + 1013904223) >>> 0;
    const base = 0.18 + (current / 4294967295) * 0.82;
    const envelope = Math.sin((index / bars) * Math.PI) * 0.35 + 0.65;
    values.push(Math.max(0.08, Math.min(1, base * envelope)));
  }
  return values;
}

/**
 * @param {Blob} blob
 * @returns {Promise<number[]>}
 */
async function decodeWaveform(blob) {
  try {
    const Context = window.AudioContext || /** @type {any} */ (window).webkitAudioContext;
    if (!Context) return [];
    const context = new Context();
    const buffer = await context.decodeAudioData(await blob.arrayBuffer());
    const channel = buffer.getChannelData(0);
    const bars = 120;
    const bucket = Math.max(1, Math.floor(channel.length / bars));
    const peaks = [];
    for (let index = 0; index < bars; index += 1) {
      let peak = 0;
      const start = index * bucket;
      const end = Math.min(channel.length, start + bucket);
      for (let sample = start; sample < end; sample += 8) {
        const value = Math.abs(channel[sample]);
        if (value > peak) peak = value;
      }
      peaks.push(Math.max(0.06, Math.min(1, peak * 3.2)));
    }
    await context.close();
    return peaks;
  } catch (error) {
    return [];
  }
}

/**
 * @param {number[]} peaks
 */
function drawWaveform(peaks) {
  const canvas = /** @type {HTMLCanvasElement} */ (byId("waveform"));
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width || 720));
  const height = 64;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);

  const styles = window.getComputedStyle(document.documentElement);
  const barColor = styles.getPropertyValue("--rule-strong").trim() || "#b9a88c";
  const accent = styles.getPropertyValue("--stamp").trim() || "#8b1e1e";
  const values = peaks.length ? peaks : pseudoWaveform("nyayadost");
  const bars = values.length;
  const gap = 2;
  const barWidth = Math.max(1, (width - gap * (bars - 1)) / bars);
  const center = height / 2;

  for (let index = 0; index < bars; index += 1) {
    const value = values[index];
    const barHeight = Math.max(2, value * (height - 10));
    const x = index * (barWidth + gap);
    context.fillStyle = index / bars < 0.5 ? barColor : accent;
    context.globalAlpha = 0.55 + value * 0.35;
    context.fillRect(x, center - barHeight / 2, barWidth, barHeight);
  }
  context.globalAlpha = 1;
}

/* --------------------------------------------------------------------------
   NyayaGuide
   -------------------------------------------------------------------------- */

function bindGuide() {
  byId("guide-load").addEventListener("click", loadGuide);
  selectById("guide-type").addEventListener("change", () => {
    state.guideType = selectById("guide-type").value;
  });
  selectById("guide-language").addEventListener("change", () => {
    state.guideLanguage = selectById("guide-language").value;
  });
}

async function loadGuide() {
  const type = selectById("guide-type").value || state.guideType;
  const language = selectById("guide-language").value || state.guideLanguage;
  state.guideType = type;
  state.guideLanguage = language;
  show("guide-loading", true);
  show("guide-empty", false);
  show("guide-root", false);
  try {
    const data = await api(
      "/api/guide/" + encodeURIComponent(type) + "?language=" + encodeURIComponent(language),
      { timeout: 30000 }
    );
    state.guide = data;
    renderGuide(data);
    show("guide-root", true);
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    const empty = byId("guide-empty");
    empty.textContent = "";
    empty.appendChild(el("p", "", apiError.message));
    if (apiError.hint) empty.appendChild(el("p", "field-hint", apiError.hint));
    show("guide-empty", true);
    showToast(apiError.message, "error");
  } finally {
    show("guide-loading", false);
  }
}

/**
 * @param {any} data
 */
function renderGuide(data) {
  setText("guide-type-label", data.notice_type_label || "NyayaGuide");
  setText("guide-title-text", data.title || "Guide");
  setText("guide-overview", data.overview || "");
  setText("guide-native-summary", data.native_summary || "");
  setText("guide-disclaimer", data.disclaimer || "");

  const steps = byId("guide-steps");
  steps.textContent = "";
  for (const step of data.steps || []) {
    const item = el("li", "guide-step");
    const body = el("div", "");
    body.appendChild(el("strong", "", step.title || ""));
    if (step.detail) body.appendChild(el("p", "", step.detail));
    item.appendChild(body);
    steps.appendChild(item);
  }

  fillPlainList("guide-documents", data.documents || []);
  fillPlainList("guide-flags", data.lawyer_flags || [], "flag-list");
  fillPlainList("guide-mistakes", data.mistakes || [], "mistake-list");
  fillPlainList("guide-reply-points", data.reply_points || []);

  const timeline = byId("guide-timeline");
  timeline.textContent = "";
  for (const point of data.timeline || []) {
    const item = el("li", "timeline-item");
    item.appendChild(el("span", "timeline-when", point.when || ""));
    item.appendChild(el("span", "timeline-action", point.action || ""));
    timeline.appendChild(item);
  }
}

/**
 * @param {string} id
 * @param {string[]} items
 * @param {string} [extraClass]
 */
function fillPlainList(id, items, extraClass = "") {
  const list = byId(id);
  list.textContent = "";
  list.className = "plain-list" + (extraClass ? " " + extraClass : "");
  for (const item of items) {
    list.appendChild(el("li", "", item));
  }
  if (!items.length) list.appendChild(el("li", "", "None listed for this notice type."));
}

/* --------------------------------------------------------------------------
   Legal Aid Finder
   -------------------------------------------------------------------------- */

function bindLegalAid() {
  byId("aid-form").addEventListener("submit", submitLegalAid);
  selectById("aid-state").addEventListener("change", populateDistricts);
}

async function loadLegalAidOptions() {
  try {
    const data = await api("/api/legal-aid/options", { timeout: 30000 });
    state.aidOptions = data;
    const select = selectById("aid-state");
    select.textContent = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Choose a state";
    select.appendChild(placeholder);
    for (const item of data.states || []) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name;
      select.appendChild(option);
    }
    populateDistricts();
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    const box = byId("aid-error");
    box.textContent = apiError.message + (apiError.hint ? " " + apiError.hint : "");
    box.removeAttribute("hidden");
  }
}

function populateDistricts() {
  const stateSelect = selectById("aid-state");
  const districtSelect = selectById("aid-district");
  const selectedState = stateSelect.value;
  state.aidState = selectedState || null;
  districtSelect.textContent = "";

  if (!selectedState || !state.aidOptions) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Choose a state first";
    districtSelect.appendChild(option);
    return;
  }

  const found = (state.aidOptions.states || []).find((item) => item.name === selectedState);
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a district";
  districtSelect.appendChild(placeholder);
  if (found) {
    for (const district of found.districts || []) {
      const option = document.createElement("option");
      option.value = district.name;
      option.textContent = district.name;
      districtSelect.appendChild(option);
    }
  }
  const other = document.createElement("option");
  other.value = "__other__";
  other.textContent = "My district is not listed";
  districtSelect.appendChild(other);
}

async function submitLegalAid(event) {
  event.preventDefault();
  const box = byId("aid-error");
  box.textContent = "";
  box.setAttribute("hidden", "");

  const stateName = selectById("aid-state").value.trim();
  const districtSelectValue = selectById("aid-district").value.trim();
  const otherDistrict = inputById("aid-district-other").value.trim();
  const district = otherDistrict || (districtSelectValue === "__other__" ? "" : districtSelectValue);

  if (!stateName) {
    showAidError("Choose your state or Union Territory first.");
    return;
  }
  if (!district) {
    showAidError("Choose a district, or type your district in the box.");
    return;
  }

  const button = byId("aid-submit");
  button.setAttribute("disabled", "");
  const original = button.textContent || "Find free legal help";
  button.textContent = "Looking up the DLSA…";
  try {
    const data = await api(
      "/api/legal-aid?state=" + encodeURIComponent(stateName) + "&district=" + encodeURIComponent(district),
      { timeout: 30000 }
    );
    renderLegalAid(data);
    show("aid-empty", false);
    show("aid-root", true);
  } catch (error) {
    const apiError = /** @type {ApiError} */ (error);
    showAidError(apiError.message + (apiError.hint ? " " + apiError.hint : ""));
    showToast(apiError.message, "error");
  } finally {
    button.removeAttribute("disabled");
    button.textContent = original;
  }
}

/**
 * @param {string} message
 */
function showAidError(message) {
  const box = byId("aid-error");
  box.textContent = message;
  box.removeAttribute("hidden");
}

/**
 * @param {any} data
 */
function renderLegalAid(data) {
  setText("aid-match-label", data.matched ? "Matched in the demo directory" : "Nearest guidance");
  setText("aid-dlsa-name", data.dlsa_name || "District Legal Services Authority");
  setText("aid-address", data.address || "");
  setText("aid-phone", data.phone || data.helpline || "15100");
  setText("aid-hours", data.hours || "");
  setText("aid-note", data.note || "");
  const website = /** @type {HTMLAnchorElement} */ (byId("aid-website"));
  website.href = data.website || "https://nalsa.gov.in";
  website.textContent = (data.website || "https://nalsa.gov.in").replace(/^https?:\/\//, "");

  const badge = byId("aid-badge");
  badge.textContent = data.matched ? "Matched" : "Approximate";
  badge.classList.toggle("is-approx", !data.matched);

  fillPlainList("aid-eligibility", data.eligibility || []);
  fillPlainList("aid-documents", data.documents || []);

  const steps = byId("aid-steps");
  steps.textContent = "";
  for (const item of data.application_steps || []) {
    const row = el("li", "guide-step");
    const body = el("div", "");
    body.appendChild(el("p", "", item));
    row.appendChild(body);
    steps.appendChild(row);
  }
}

/* --------------------------------------------------------------------------
   Language switching
   -------------------------------------------------------------------------- */

async function changeLanguage() {
  const selected = selectById("language-select").value;
  if (!selected || selected === state.language) return;
  state.language = selected;
  state.guideLanguage = selected;
  writeStorage(STORAGE.language, selected);
  selectById("guide-language").value = selected;
  showToast("Switching the explanation to " + languageName(selected) + "…", "info");

  try {
    const data = await api("/api/bootstrap?language=" + encodeURIComponent(selected));
    applyBootstrap(data);
    selectById("guide-language").value = selected;
  } catch (error) {
    /* The analysis can still be re-run even if labels did not refresh. */
  }

  if (state.analysis) {
    const sourceText = state.analysis.original_text;
    const sourceName = state.analysis.source && state.analysis.source.name ? state.analysis.source.name : "Pasted notice";
    await performAnalysis(() =>
      api("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: sourceText, language: selected, source_name: sourceName }),
        timeout: 45000,
      })
    );
  }

  if (state.guide) {
    await loadGuide();
  }
}

/* --------------------------------------------------------------------------
   Init
   -------------------------------------------------------------------------- */

function bindGlobalErrors() {
  window.addEventListener("offline", () => {
    showToast("You are offline. Pasted-text features need the local server to be running.", "error");
  });
  window.addEventListener("online", () => {
    showToast("You are back online.", "success");
  });
}

async function init() {
  bindTheme();
  bindInput();
  bindUpload();
  bindDictation();
  bindResultTabs();
  bindResultActions();
  bindAudio();
  bindGuide();
  bindLegalAid();
  bindGlobalErrors();

  selectById("language-select").addEventListener("change", changeLanguage);

  await loadBootstrap();
  await Promise.allSettled([loadLegalAidOptions(), loadGuide()]);

  if (!state.bootstrap) {
    showInputError(
      "NyayaDost could not load its starter data.",
      "Make sure the server is running, then refresh this page."
    );
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
