const sectionNames = {
  0: "Section 0 - LLM Core",
  1: "Section 1 - Patterns",
  2: "Section 2 - Tool Calling",
  3: "Section 3 - Webhook Integration",
  4: "Section 4 - Code Execution",
  5: "Section 5 - Security Guard",
  6: "Section 6 - Production Mode",
};

const params = new URLSearchParams(window.location.search);
const parsedMax = Number(params.get("max_section"));
const maxSection = Number.isInteger(parsedMax) && parsedMax >= 0 && parsedMax <= 6 ? parsedMax : 0;
const STORAGE_KEY = "agentic_workflow_ui_state_v1";
const backendUrl = params.get("backend_url") || "";
const hasBackend = Boolean(backendUrl);
const thinkingFrames = ["正在思考.", "正在思考..", "正在思考..."];
const ALLOWED_IMAGE_MIME = new Set(["image/png", "image/jpeg", "image/webp"]);
const ALLOWED_DATA_EXT = new Set(["csv", "xlsx"]);
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const DEFAULT_CHAT_PLACEHOLDER = "輸入訊息，按 Enter 送出，Shift+Enter 換行";
const DEFAULT_CODE_LIBRARIES = ["pandas", "matplotlib", "numpy"];

let messageIdSeq = 0;
let conversationIdSeq = 0;

const state = {
  currentSection: maxSection,
  conversations: [],
  currentConversationId: null,
  tasks: [],
  config: {
    llm: {
      model: "gpt-4o",
      system_prompt: "You are a helpful assistant.",
      memory: false,
      memory_rounds: 4,
      rag: false,
      temperature: 0.3,
    },
    workflow: {
      enabled: true,
      mode: "llm",
      router_mode: "pydantic",
      routes: [],
    },
    tool: {
      enabled: false,
      tools: ["create_task", "search_web"],
      mode: "auto",
    },
    webhook: {
      enabled: false,
      workflows: ["calendar_query"],
      calendar_query_url: "",
      mode: "manual",
    },
    code_execution: {
      enabled: false,
      libraries: [...DEFAULT_CODE_LIBRARIES],
      auto_run: false,
    },
    security: {
      moderation: false,
      guardrails: false,
      injection_protection: "basic",
      role: "staff",
    },
    production: {
      enabled: false,
      model_routing: false,
      logging: false,
      fallback: false,
      cost_control: false,
    },
  },
  runtime_env: {
    supported_libraries: [],
  },
};

const sectionSelect = document.getElementById("current-section");
const sectionBadge = document.getElementById("chat-section-badge");
const controlsRoot = document.getElementById("controls-root");
const configPreview = document.getElementById("config-preview");
const chatHistory = document.getElementById("chat-history");
const chatInput = document.getElementById("chat-input");
const chatImageInput = document.getElementById("chat-image");
const chatImageHint = document.getElementById("chat-image-hint");
const sendBtn = document.getElementById("send-btn");
const chatInputRow = document.querySelector(".chat-input-row");
const sectionTemplate = document.getElementById("section-card-template");
const conversationList = document.getElementById("conversation-list");
const newChatBtn = document.getElementById("new-chat-btn");
const currentChatTitle = document.getElementById("current-chat-title");
const taskListEl = document.getElementById("task-list");
const taskInputEl = document.getElementById("task-input");
const addTaskBtn = document.getElementById("add-task-btn");
const controlsFoldEl = document.getElementById("controls-fold");
const runtimeFoldEl = document.getElementById("runtime-fold");
const taskFoldEl = document.getElementById("task-fold");
const routeConfirmBar = document.getElementById("route-confirm-bar");
const routeConfirmText = document.getElementById("route-confirm-text");
const routeYesBtn = document.getElementById("route-yes-btn");
const routeNoBtn = document.getElementById("route-no-btn");

let pendingImageDataUrl = "";
let pendingUploadedFile = null;
let saveTimer = null;
let taskEditingId = null;
let taskEditingDraft = "";
let conversationMenuId = null;
let conversationEditingId = null;
let conversationEditingDraft = "";

function isCodeExecMemoryEnforced() {
  return Boolean(state.config?.code_execution?.enabled);
}

function enforceCodeExecMemoryPolicy() {
  if (!isCodeExecMemoryEnforced()) return;
  state.config.llm.memory = true;
  const rounds = Number(state.config.llm.memory_rounds || 4);
  state.config.llm.memory_rounds = Math.max(4, rounds);
  state.config.code_execution.libraries = [...DEFAULT_CODE_LIBRARIES];
}

function init() {
  for (let i = 0; i <= maxSection; i += 1) {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = sectionNames[i];
    sectionSelect.appendChild(opt);
  }

  loadStateFromStorage();
  if (state.currentSection > maxSection) {
    state.currentSection = maxSection;
  }
  if (state.conversations.length === 0) {
    const first = createConversation({
      title: "新聊天室",
      withWelcome: true,
    });
    state.currentConversationId = first.id;
  } else if (!getConversationById(state.currentConversationId)) {
    state.currentConversationId = state.conversations[0].id;
  }
  recalculateIdCounters();

  sectionSelect.addEventListener("change", (event) => {
    state.currentSection = Number(event.target.value);
    scheduleSaveState();
    render();
  });

  newChatBtn.addEventListener("click", () => {
    const created = createConversation({ title: "新聊天室", withWelcome: true });
    state.currentConversationId = created.id;
    conversationMenuId = null;
    routeConfirmBar.hidden = true;
    scheduleSaveState();
    render();
  });

  sendBtn.addEventListener("click", () => sendMessage());
  routeYesBtn.addEventListener("click", () => submitRouteConfirmation("Yes"));
  routeNoBtn.addEventListener("click", () => submitRouteConfirmation("No"));
  addTaskBtn.addEventListener("click", handleAddTask);
  taskInputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleAddTask();
    }
  });

  chatImageInput.addEventListener("change", async (event) => {
    const [file] = event.target.files || [];
    if (!file) {
      pendingImageDataUrl = "";
      pendingUploadedFile = null;
      if (chatImageHint) chatImageHint.textContent = "可選：上傳圖片或 xlsx/csv 供分析";
      return;
    }

    const ext = String(file.name.split(".").pop() || "").toLowerCase();
    const isImage = ALLOWED_IMAGE_MIME.has(file.type);
    const isDataFile = ALLOWED_DATA_EXT.has(ext);

    if (isImage) {
      if (file.size > MAX_IMAGE_BYTES) {
        pendingImageDataUrl = "";
        pendingUploadedFile = null;
        chatImageInput.value = "";
        alert("圖片太大，請上傳 8MB 以下圖片。");
        return;
      }
      pendingImageDataUrl = await fileToDataUrl(file);
      pendingUploadedFile = null;
      if (chatImageHint) chatImageHint.textContent = `已附加圖片：${file.name}`;
      return;
    }

    if (isDataFile) {
      if (!hasBackend) {
        chatImageInput.value = "";
        alert("目前未啟動後端，無法上傳資料檔。");
        return;
      }
      if (state.currentSection < 4) {
        chatImageInput.value = "";
        alert("資料檔分析請在 Section 4 使用。");
        return;
      }
      try {
        pendingUploadedFile = await uploadDataFileToBackend(file);
        pendingImageDataUrl = "";
        if (chatImageHint) chatImageHint.textContent = `已上傳資料檔：${pendingUploadedFile.name}`;
      } catch (error) {
        pendingUploadedFile = null;
        pendingImageDataUrl = "";
        chatImageInput.value = "";
        alert(`資料檔上傳失敗：${String(error)}`);
      }
      return;
    }

    pendingImageDataUrl = "";
    pendingUploadedFile = null;
    chatImageInput.value = "";
    alert("目前支援：PNG/JPEG/WebP 圖片，或 CSV/XLSX 資料檔。");
  });

  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  // Accordion behavior: Control/Runtime/Task only one open at a time.
  controlsFoldEl.addEventListener("toggle", () => {
    if (controlsFoldEl.open) {
      runtimeFoldEl.open = false;
      taskFoldEl.open = false;
    }
  });
  runtimeFoldEl.addEventListener("toggle", () => {
    if (runtimeFoldEl.open) {
      controlsFoldEl.open = false;
      taskFoldEl.open = false;
    }
  });
  taskFoldEl.addEventListener("toggle", () => {
    if (taskFoldEl.open) {
      controlsFoldEl.open = false;
      runtimeFoldEl.open = false;
    }
  });

  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    if (!event.target.closest(".conversation-actions")) {
      if (conversationMenuId !== null) {
        conversationMenuId = null;
        renderConversations();
      }
    }
  });

  render();
  loadRuntimeEnvironmentInfo();
  loadConversationsFromBackend();
  loadTasksFromBackend();
}

async function loadRuntimeEnvironmentInfo() {
  if (!hasBackend) return;
  try {
    const response = await fetch(`${backendUrl}/health`);
    if (!response.ok) return;
    const payload = await response.json();
    const libs = Array.isArray(payload.supported_libraries) ? payload.supported_libraries : [];
    state.runtime_env.supported_libraries = libs.map((item) => String(item));
    renderControls();
  } catch (_error) {
    // Ignore probing errors.
  }
}

function recalculateIdCounters() {
  let maxConv = 0;
  let maxMsg = 0;

  state.conversations.forEach((conv) => {
    const convNum = Number(String(conv.id || "").replace("conv_", ""));
    if (Number.isFinite(convNum)) maxConv = Math.max(maxConv, convNum);
    (conv.messages || []).forEach((msg) => {
      const msgNum = Number(String(msg.id || "").replace("msg_", ""));
      if (Number.isFinite(msgNum)) maxMsg = Math.max(maxMsg, msgNum);
    });
  });

  conversationIdSeq = maxConv;
  messageIdSeq = maxMsg;
}

function loadStateFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== "object") return;

    if (Number.isInteger(saved.currentSection)) {
      state.currentSection = saved.currentSection;
    }
    if (saved.currentConversationId && typeof saved.currentConversationId === "string") {
      state.currentConversationId = saved.currentConversationId;
    }
    if (Array.isArray(saved.conversations)) {
      state.conversations = normalizeConversations(saved.conversations);
    }
    if (saved.config && typeof saved.config === "object") {
      state.config = { ...state.config, ...saved.config };
      state.config.llm = { ...state.config.llm, ...(saved.config.llm || {}) };
      state.config.workflow = { ...state.config.workflow, ...(saved.config.workflow || {}) };
      state.config.tool = { ...state.config.tool, ...(saved.config.tool || {}) };
      state.config.tool.tools = ["create_task", "search_web"];
      state.config.webhook = { ...state.config.webhook, ...(saved.config.webhook || {}) };
      if (!state.config.webhook.calendar_query_url) {
        const legacyEndpoints = safeParseJson(state.config.webhook.endpoints_json || "");
        if (legacyEndpoints && typeof legacyEndpoints === "object") {
          state.config.webhook.calendar_query_url = String(
            legacyEndpoints.calendar_query || legacyEndpoints.query || "",
          );
        }
      }
      state.config.webhook.workflows = ["calendar_query"];
      state.config.webhook.mode = state.config.webhook.mode === "auto" ? "auto" : "manual";
      state.config.code_execution = { ...state.config.code_execution, ...(saved.config.code_execution || {}) };
      if (!Array.isArray(state.config.code_execution.libraries) || state.config.code_execution.libraries.length === 0) {
        state.config.code_execution.libraries = [...DEFAULT_CODE_LIBRARIES];
      }
      state.config.security = { ...state.config.security, ...(saved.config.security || {}) };
      state.config.production = { ...state.config.production, ...(saved.config.production || {}) };
    }
    if (Array.isArray(saved.tasks)) {
      state.tasks = saved.tasks
        .filter((task) => task && typeof task.id === "string")
        .map((task) => ({
          id: task.id,
          title: String(task.title || ""),
          status: task.status === "done" ? "done" : "pending",
          source: String(task.source || "manual"),
        }));
    }
  } catch (_error) {
    // Ignore broken storage payload and continue with defaults.
  }
}

function scheduleSaveState() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(saveStateToStorage, 120);
}

function saveStateToStorage() {
  const cleanedConversations = state.conversations.map((conv) => ({
    id: conv.id,
    title: conv.title,
    titleManual: Boolean(conv.titleManual),
    pendingRoute: conv.pendingRoute || null,
    createdAt: conv.createdAt,
    messages: (conv.messages || [])
      .filter((msg) => !msg.thinking && (msg.role === "user" || msg.role === "assistant"))
      .map((msg) => ({ id: msg.id, role: msg.role, text: msg.text })),
  }));

  const payload = {
    currentSection: state.currentSection,
    currentConversationId: state.currentConversationId,
    conversations: cleanedConversations,
    tasks: state.tasks,
    config: state.config,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));

  if (hasBackend) {
    syncConversationsToBackend(cleanedConversations, state.currentConversationId);
  }
}

async function loadConversationsFromBackend() {
  if (!hasBackend) return;

  try {
    const response = await fetch(`${backendUrl}/conversations`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    const serverConversations = normalizeConversations(payload.conversations || []);
    if (serverConversations.length > 0) {
      state.conversations = serverConversations;
      if (
        payload.currentConversationId
        && serverConversations.some((conv) => conv.id === payload.currentConversationId)
      ) {
        state.currentConversationId = payload.currentConversationId;
      } else {
        state.currentConversationId = serverConversations[0].id;
      }
      recalculateIdCounters();
      render();
      return;
    }
    // Seed backend with current local state when server has no history.
    scheduleSaveState();
  } catch (_error) {
    // Keep local state when backend conversation sync is unavailable.
  }
}

async function syncConversationsToBackend(conversations, currentConversationId) {
  try {
    await fetch(`${backendUrl}/conversations/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversations,
        currentConversationId,
      }),
    });
  } catch (_error) {
    // Ignore transient sync errors.
  }
}

function normalizeConversations(rawConversations) {
  if (!Array.isArray(rawConversations)) return [];
  return rawConversations
    .filter((conv) => conv && typeof conv.id === "string")
    .map((conv) => ({
      id: conv.id,
      title: typeof conv.title === "string" ? conv.title : "新聊天室",
      titleManual: Boolean(conv.titleManual),
      titleGenerating: false,
      pendingRoute: conv.pendingRoute || null,
      createdAt: Number(conv.createdAt) || Date.now(),
      messages: Array.isArray(conv.messages)
        ? conv.messages
            .filter((msg) => msg && (msg.role === "user" || msg.role === "assistant"))
            .map((msg) => ({
              id: typeof msg.id === "string" ? msg.id : undefined,
              role: msg.role,
              text: typeof msg.text === "string" ? msg.text : "",
            }))
        : [],
    }));
}

function createConversation({ title, withWelcome }) {
  conversationIdSeq += 1;
  const conversation = {
    id: `conv_${conversationIdSeq}`,
    title,
    titleManual: false,
    titleGenerating: false,
    pendingRoute: null,
    messages: withWelcome
      ? [{ role: "assistant", text: "新的聊天室已建立，你可以開始提問。" }]
      : [],
    createdAt: Date.now(),
  };
  state.conversations.unshift(conversation);
  scheduleSaveState();
  return conversation;
}

function getConversationById(id) {
  return state.conversations.find((item) => item.id === id) || null;
}

function getCurrentConversation() {
  return getConversationById(state.currentConversationId);
}

function isConfirmPendingRoute(pending) {
  if (!pending || typeof pending !== "object") return false;
  const stage = String(pending.stage || "");
  // Only confirmation stages should lock free-text input.
  return stage.startsWith("confirm_");
}

function sendMessage(forcedText = null) {
  const text = forcedText === null ? chatInput.value.trim() : String(forcedText).trim();
  if (!text && !pendingImageDataUrl && !pendingUploadedFile) return;

  const conversation = getCurrentConversation();
  if (!conversation) return;
  const pending = conversation.pendingRoute || null;
  const shouldLockInput = isConfirmPendingRoute(pending);
  if (shouldLockInput && forcedText === null) {
    alert("目前正在等待路由確認，請直接點選 Yes / No 按鈕。");
    return;
  }

  let userDisplayText = text;
  if (pendingImageDataUrl) userDisplayText = `${text || "(未輸入文字)"}\n[已附加圖片]`;
  if (pendingUploadedFile) userDisplayText = `${text || "(未輸入文字)"}\n[已附加資料檔：${pendingUploadedFile.name}]`;
  conversation.messages.push({ role: "user", text: userDisplayText });
  bumpConversation(conversation.id);
  scheduleSaveState();

  chatInput.value = "";
  chatImageInput.value = "";
  if (chatImageHint) chatImageHint.textContent = "可選：上傳圖片或 xlsx/csv 供分析";
  render();

  maybeGenerateConversationTitle(conversation.id, text || "圖片分析");

  if (!hasBackend) {
    runMockThinkingReply(text || "（圖片訊息）", conversation.id);
    pendingImageDataUrl = "";
    pendingUploadedFile = null;
    return;
  }

  runBackendThinkingReply(text || "請分析我上傳的資料", pendingImageDataUrl, pendingUploadedFile, conversation.id);
  pendingImageDataUrl = "";
  pendingUploadedFile = null;
}

function submitRouteConfirmation(label) {
  const conversation = getCurrentConversation();
  if (!conversation || !conversation.pendingRoute) return;
  sendMessage(label);
}

function maybeGenerateConversationTitle(conversationId, seedText) {
  const conversation = getConversationById(conversationId);
  if (!conversation) return;

  const userMsgCount = conversation.messages.filter((m) => m.role === "user").length;
  if (userMsgCount !== 1) return;
  if (conversation.titleManual) return;

  if (!hasBackend) {
    conversation.title = buildFallbackTitle(seedText);
    scheduleSaveState();
    renderConversations();
    renderCurrentConversationTitle();
    return;
  }

  if (conversation.titleGenerating) return;
  conversation.titleGenerating = true;

  fetch(`${backendUrl}/title`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: seedText, config: buildExportedConfig() }),
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const title = String(data.title || "").trim();
      conversation.title = title || buildFallbackTitle(seedText);
    })
    .catch(() => {
      conversation.title = buildFallbackTitle(seedText);
    })
    .finally(() => {
      conversation.titleGenerating = false;
      scheduleSaveState();
      renderConversations();
      renderCurrentConversationTitle();
    });
}

function buildFallbackTitle(seedText) {
  const trimmed = (seedText || "新聊天室").replace(/\s+/g, " ").trim();
  if (!trimmed) return "新聊天室";
  return trimmed.length > 16 ? `${trimmed.slice(0, 16)}...` : trimmed;
}

function runMockThinkingReply(userText, conversationId) {
  const conversation = getConversationById(conversationId);
  if (!conversation) return;

  const thinkingId = nextMessageId();
  let frameIdx = 0;

  conversation.messages.push({
    id: thinkingId,
    role: "assistant",
    text: thinkingFrames[frameIdx],
    thinking: true,
  });
  renderIfCurrent(conversationId);

  const interval = setInterval(() => {
    frameIdx = (frameIdx + 1) % thinkingFrames.length;
    const targetConversation = getConversationById(conversationId);
    if (!targetConversation) return;
    const thinkingMsg = targetConversation.messages.find((msg) => msg.id === thinkingId);
    if (!thinkingMsg) return;
    thinkingMsg.text = thinkingFrames[frameIdx];
    renderIfCurrent(conversationId);
  }, 350);

  setTimeout(() => {
    clearInterval(interval);
    replaceThinkingWithFinal(
      conversationId,
      thinkingId,
      `我收到你的文字了：「${userText}」。\n目前尚未連接後端 AI 服務。\n如果要啟用 AI 功能，請在右側調整設定，並啟動對應 Section 的後端。`,
    );
  }, 3000);
}

function nextMessageId() {
  messageIdSeq += 1;
  return `msg_${messageIdSeq}`;
}

async function runBackendThinkingReply(userText, imageDataUrl, uploadedFile, conversationId) {
  const conversation = getConversationById(conversationId);
  if (!conversation) return;

  const thinkingId = nextMessageId();
  let frameIdx = 0;

  conversation.messages.push({
    id: thinkingId,
    role: "assistant",
    text: thinkingFrames[frameIdx],
    thinking: true,
  });
  renderIfCurrent(conversationId);

  const interval = setInterval(() => {
    frameIdx = (frameIdx + 1) % thinkingFrames.length;
    const targetConversation = getConversationById(conversationId);
    if (!targetConversation) return;
    const msg = targetConversation.messages.find((item) => item.id === thinkingId);
    if (!msg) return;
    msg.text = thinkingFrames[frameIdx];
    renderIfCurrent(conversationId);
  }, 350);

  try {
    const payload = {
      message: userText,
      config: buildExportedConfig(),
      history: buildConversationHistory(conversationId),
      image_data_url: imageDataUrl || null,
      uploaded_file: uploadedFile || null,
      router_context: conversation.pendingRoute || null,
    };

    const response = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let detail = "";
      try {
        const errPayload = await response.json();
        detail = errPayload.detail || errPayload.error || "";
      } catch (_e) {
        detail = "";
      }
      throw new Error(`HTTP ${response.status}${detail ? ` - ${detail}` : ""}`);
    }

    const data = await response.json();
    conversation.pendingRoute = data.pending_route || null;
    scheduleSaveState();
    replaceThinkingWithFinal(conversationId, thinkingId, data.reply || "後端未回傳內容。");
    if (data?.router?.action_type === "tool" && data?.router?.target === "create_task") {
      await loadTasksFromBackend();
    }
  } catch (error) {
    replaceThinkingWithFinal(
      conversationId,
      thinkingId,
      `後端呼叫失敗：${String(error)}\n請確認 Section 後端是否已成功啟動。`,
    );
  } finally {
    clearInterval(interval);
  }
}

function replaceThinkingWithFinal(conversationId, thinkingId, finalText) {
  const conversation = getConversationById(conversationId);
  if (!conversation) return;

  const idx = conversation.messages.findIndex((msg) => msg.id === thinkingId);
  if (idx === -1) return;

  conversation.messages[idx] = { role: "assistant", text: finalText };
  bumpConversation(conversationId);
  scheduleSaveState();
  renderIfCurrent(conversationId);
  renderConversations();
}

function buildConversationHistory(conversationId) {
  const conversation = getConversationById(conversationId);
  if (!conversation) return [];

  return conversation.messages
    .filter((msg) => !msg.thinking && (msg.role === "user" || msg.role === "assistant"))
    .map((msg) => ({ role: msg.role, text: msg.text }));
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("圖片讀取失敗"));
    reader.readAsDataURL(file);
  });
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const raw = String(reader.result || "");
      const idx = raw.indexOf(",");
      resolve(idx >= 0 ? raw.slice(idx + 1) : raw);
    };
    reader.onerror = () => reject(new Error("檔案讀取失敗"));
    reader.readAsDataURL(file);
  });
}

async function uploadDataFileToBackend(file) {
  const dataBase64 = await fileToBase64(file);
  const response = await fetch(`${backendUrl}/files`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      data_base64: dataBase64,
    }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `HTTP ${response.status}`);
  }
  const payload = await response.json();
  return payload.file || null;
}

function bumpConversation(conversationId) {
  const idx = state.conversations.findIndex((c) => c.id === conversationId);
  if (idx <= 0) return;
  const [item] = state.conversations.splice(idx, 1);
  state.conversations.unshift(item);
}

function render() {
  sectionSelect.value = String(state.currentSection);
  sectionBadge.textContent = `Section ${state.currentSection}`;
  renderConversations();
  renderCurrentConversationTitle();
  renderControls();
  renderConfigPreview();
  renderChat();
  renderRouteConfirmBar();
  renderTaskPanel();
}

function renderIfCurrent(conversationId) {
  if (state.currentConversationId === conversationId) {
    renderChat();
    renderCurrentConversationTitle();
    renderRouteConfirmBar();
  }
}

function renderConversations() {
  conversationList.innerHTML = "";

  state.conversations.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "conversation-item";
    if (conversation.id === state.currentConversationId) {
      item.classList.add("active");
    }

    item.addEventListener("click", () => {
      state.currentConversationId = conversation.id;
      conversationMenuId = null;
      routeConfirmBar.hidden = true;
      scheduleSaveState();
      render();
    });

    const top = document.createElement("div");
    top.className = "conversation-top";

    const isEditing = conversationEditingId === conversation.id;

    const titleWrap = document.createElement("div");
    titleWrap.className = "conversation-title-wrap";

    let titleNode;
    if (isEditing) {
      const titleInput = document.createElement("input");
      titleInput.type = "text";
      titleInput.className = "conversation-title-input";
      titleInput.value = conversationEditingDraft;
      titleInput.addEventListener("input", (event) => {
        conversationEditingDraft = event.target.value;
      });
      titleInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          saveConversationTitle(conversation.id);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          cancelConversationEdit();
        }
      });
      setTimeout(() => titleInput.focus(), 0);
      titleNode = titleInput;
    } else {
      const title = document.createElement("div");
      title.className = "conversation-title";
      title.textContent = conversation.titleGenerating ? `${conversation.title}...` : conversation.title;
      titleNode = title;
    }
    titleWrap.appendChild(titleNode);

    const actions = document.createElement("div");
    actions.className = "conversation-actions";

    if (isEditing) {
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "conversation-menu-item";
      saveBtn.textContent = "Save";
      saveBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        saveConversationTitle(conversation.id);
      });

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "conversation-menu-item";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        cancelConversationEdit();
      });

      actions.appendChild(saveBtn);
      actions.appendChild(cancelBtn);
    } else {
      const menuBtn = document.createElement("button");
      menuBtn.type = "button";
      menuBtn.className = "conversation-menu-btn";
      menuBtn.textContent = "...";
      menuBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        conversationMenuId = conversationMenuId === conversation.id ? null : conversation.id;
        renderConversations();
      });
      actions.appendChild(menuBtn);
    }

    if (!isEditing && conversationMenuId === conversation.id) {
      const menu = document.createElement("div");
      menu.className = "conversation-menu";

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "conversation-menu-item";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        conversationEditingId = conversation.id;
        conversationEditingDraft = conversation.title || "";
        conversationMenuId = null;
        renderConversations();
      });

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "conversation-menu-item danger";
      deleteBtn.textContent = "Delete";
      deleteBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        conversationMenuId = null;
        handleDeleteConversation(conversation.id);
      });

      menu.appendChild(editBtn);
      menu.appendChild(deleteBtn);
      actions.appendChild(menu);
    }

    top.appendChild(titleWrap);
    top.appendChild(actions);

    const preview = document.createElement("div");
    preview.className = "conversation-preview";
    const last = getLastVisibleMessage(conversation);
    preview.textContent = last ? last.text.replace(/\n/g, " ") : "尚無訊息";

    item.appendChild(top);
    item.appendChild(preview);
    conversationList.appendChild(item);
  });
}

function saveConversationTitle(conversationId) {
  const conversation = getConversationById(conversationId);
  if (!conversation) return;
  const next = (conversationEditingDraft || "").trim();
  if (!next) return;
  conversation.title = next;
  conversation.titleManual = true;
  conversationEditingId = null;
  conversationEditingDraft = "";
  scheduleSaveState();
  renderConversations();
  renderCurrentConversationTitle();
}

function cancelConversationEdit() {
  conversationEditingId = null;
  conversationEditingDraft = "";
  renderConversations();
}

function handleDeleteConversation(conversationId) {
  const idx = state.conversations.findIndex((item) => item.id === conversationId);
  if (idx === -1) return;

  state.conversations.splice(idx, 1);

  if (state.currentConversationId === conversationId) {
    if (state.conversations.length > 0) {
      state.currentConversationId = state.conversations[0].id;
    } else {
      const created = createConversation({ title: "新聊天室", withWelcome: true });
      state.currentConversationId = created.id;
    }
  }

  scheduleSaveState();
  conversationMenuId = null;
  render();
}

function getLastVisibleMessage(conversation) {
  for (let i = conversation.messages.length - 1; i >= 0; i -= 1) {
    const msg = conversation.messages[i];
    if (!msg.thinking) return msg;
  }
  return null;
}

function renderCurrentConversationTitle() {
  const conversation = getCurrentConversation();
  currentChatTitle.textContent = conversation ? conversation.title : "新聊天室";
}

function renderControls() {
  controlsRoot.innerHTML = "";
  controlsRoot.appendChild(renderSectionCard(0, "LLM Core Settings", renderLLMControls));
  controlsRoot.appendChild(renderSectionCard(1, "Patterns", renderWorkflowControls));
  controlsRoot.appendChild(renderSectionCard(2, "Tool Calling", renderToolControls));
  controlsRoot.appendChild(renderSectionCard(3, "Webhook Integration", renderWebhookControls));
  controlsRoot.appendChild(renderSectionCard(4, "Code Execution", renderCodeExecutionControls));
  controlsRoot.appendChild(renderSectionCard(5, "Security Guard", renderSecurityControls));
  controlsRoot.appendChild(renderSectionCard(6, "Production Mode", renderProductionControls));
}

function renderSectionCard(unlockSection, title, renderer) {
  const node = sectionTemplate.content.firstElementChild.cloneNode(true);
  const body = node.querySelector(".section-body");
  const titleNode = node.querySelector(".section-title");
  const lockTag = node.querySelector(".lock-tag");
  const lockedBySection = state.currentSection < unlockSection;
  const lockedByFreshMode = unlockSection === 0 && !hasBackend && maxSection === 0;
  const locked = lockedBySection || lockedByFreshMode;

  titleNode.textContent = title;
  if (lockedByFreshMode) {
    lockTag.textContent = "Locked (need Section 0)";
  } else if (lockedBySection) {
    lockTag.textContent = `Locked (need Section ${unlockSection})`;
  } else {
    lockTag.textContent = "Active";
  }

  if (locked) {
    const note = document.createElement("p");
    note.className = "locked-note";
    note.textContent = lockedByFreshMode
      ? "目前是 fresh 模式，未連接後端，LLM 設定不可調整。"
      : `目前是 Section ${state.currentSection}，此區功能尚未開放。`;
    body.appendChild(note);
  }

  renderer(body, locked);
  return node;
}

function renderLLMControls(container, locked) {
  const memoryForcedByCodeExec = isCodeExecMemoryEnforced();

  container.appendChild(createRadioGroup("Model", "llm_model", [
    ["gpt-5.4", "GPT-5.4"],
    ["gpt-5.4-nano", "GPT-5.4-nano"],
    ["gpt-4o", "gpt-4o"],
  ], state.config.llm.model, (value) => {
    state.config.llm.model = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createTextarea("System Prompt", state.config.llm.system_prompt, (value) => {
    state.config.llm.system_prompt = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Enable Conversation Memory", state.config.llm.memory, (value) => {
    if (memoryForcedByCodeExec && !value) {
      state.config.llm.memory = true;
      renderConfigPreview();
      renderControls();
      return;
    }
    state.config.llm.memory = value;
    renderConfigPreview();
    renderControls();
  }, locked || memoryForcedByCodeExec));

  container.appendChild(createSelect(
    memoryForcedByCodeExec ? "Memory Rounds (4~10, forced by Code Execution)" : "Memory Rounds (1~10)",
    Array.from({ length: 10 }, (_, i) => [String(i + 1), String(i + 1)]),
    String(state.config.llm.memory_rounds),
    (value) => {
      const num = Number(value);
      state.config.llm.memory_rounds = memoryForcedByCodeExec ? Math.max(4, num) : num;
      renderConfigPreview();
    },
    locked || !state.config.llm.memory,
  ));

  container.appendChild(createCheckbox("Enable RAG", state.config.llm.rag, (value) => {
    state.config.llm.rag = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createRange("Temperature", 0, 1, 0.1, state.config.llm.temperature, (value) => {
    state.config.llm.temperature = Number(value);
    renderConfigPreview();
  }, locked));
}

function renderWorkflowControls(container, locked) {
  container.appendChild(createRadioGroup("LLM Mode", "workflow_mode", [
    ["llm", "LLM-based (advanced)"],
    ["rule", "Rule-based"],
  ], state.config.workflow.mode, (value) => {
    state.config.workflow.mode = value;
    renderConfigPreview();
    renderControls();
  }, locked));

  container.appendChild(createRadioGroup("Structured Mode", "router_mode", [
    ["prompt_only", "prompt_only"],
    ["pydantic", "pydantic"],
  ], state.config.workflow.router_mode || "pydantic", (value) => {
    state.config.workflow.router_mode = value;
    renderConfigPreview();
  }, locked || state.config.workflow.mode === "rule"));
}

function renderToolControls(container, locked) {
  container.appendChild(createCheckbox("Enable Tool Calling", state.config.tool.enabled, (value) => {
    state.config.tool.enabled = value;
    renderConfigPreview();
    renderControls();
  }, locked));

  const toolsBlock = document.createElement("div");
  const toolsTitle = document.createElement("div");
  toolsTitle.textContent = "Available Tools";
  const toolsList = document.createElement("div");
  toolsList.className = "option-grid";
  toolsList.textContent = "Create Task, Search Web (Tavily)";
  if (locked || !state.config.tool.enabled) {
    toolsList.style.opacity = "0.5";
  }
  toolsBlock.appendChild(toolsTitle);
  toolsBlock.appendChild(toolsList);
  container.appendChild(toolsBlock);

  container.appendChild(createRadioGroup("Tool Mode", "tool_mode", [
    ["auto", "Auto (LLM decides)"],
    ["manual", "Manual (debug)"],
  ], state.config.tool.mode, (value) => {
    state.config.tool.mode = value;
    renderConfigPreview();
  }, locked || !state.config.tool.enabled));
}

function renderWebhookControls(container, locked) {
  container.appendChild(createCheckbox("Enable Webhook Mode", state.config.webhook.enabled, (value) => {
    state.config.webhook.enabled = value;
    renderConfigPreview();
    renderControls();
  }, locked));

  const workflowsBlock = document.createElement("div");
  const workflowsTitle = document.createElement("div");
  workflowsTitle.textContent = "Available Workflows";
  const workflowsList = document.createElement("div");
  workflowsList.className = "option-grid";
  workflowsList.textContent = "calendar_query (n8n)";
  if (locked || !state.config.webhook.enabled) {
    workflowsList.style.opacity = "0.5";
  }
  workflowsBlock.appendChild(workflowsTitle);
  workflowsBlock.appendChild(workflowsList);
  container.appendChild(workflowsBlock);

  container.appendChild(createTextInput(
    "Calendar Query Webhook URL",
    state.config.webhook.calendar_query_url || "",
    (value) => {
      state.config.webhook.calendar_query_url = value;
      renderConfigPreview();
    },
    locked || !state.config.webhook.enabled,
    "https://your-n8n-domain/webhook/calendar_query",
  ));

  container.appendChild(createRadioGroup("Workflow Mode", "webhook_mode", [
    ["auto", "Auto (execute directly)"],
    ["manual", "Manual (ask Yes/No)"],
  ], state.config.webhook.mode || "manual", (value) => {
    state.config.webhook.mode = value;
    renderConfigPreview();
  }, locked || !state.config.webhook.enabled));
}

function renderCodeExecutionControls(container, locked) {
  container.appendChild(createCheckbox("Enable Code Execution", state.config.code_execution.enabled, (value) => {
    state.config.code_execution.enabled = value;
    if (value) {
      enforceCodeExecMemoryPolicy();
    }
    renderConfigPreview();
    renderControls();
  }, locked));

  container.appendChild(createRadioGroup("Execution Flow", "code_flow_mode", [
    ["auto", "Automatic (execute directly)"],
    ["manual", "Manual (show code + Yes/No)"],
  ], state.config.code_execution.auto_run ? "auto" : "manual", (value) => {
    state.config.code_execution.auto_run = value === "auto";
    renderConfigPreview();
  }, locked));

  const libsWrap = document.createElement("div");
  const libsTitle = document.createElement("div");
  libsTitle.textContent = "Environment Libraries (read-only)";
  const libsList = document.createElement("div");
  libsList.className = "option-grid";
  const detected = state.runtime_env.supported_libraries || [];
  const source = detected.length > 0 ? detected : DEFAULT_CODE_LIBRARIES;
  libsList.textContent = source.join(", ");
  if (locked || !state.config.code_execution.enabled) {
    libsList.style.opacity = "0.5";
  }
  libsWrap.appendChild(libsTitle);
  libsWrap.appendChild(libsList);
  container.appendChild(libsWrap);

}

function renderSecurityControls(container, locked) {
  container.appendChild(createCheckbox("Enable Moderation API", state.config.security.moderation, (value) => {
    state.config.security.moderation = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Enable Guardrails", state.config.security.guardrails, (value) => {
    state.config.security.guardrails = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createRadioGroup("Prompt Injection Protection", "security_injection", [
    ["basic", "Basic"],
    ["strict", "Strict"],
  ], state.config.security.injection_protection, (value) => {
    state.config.security.injection_protection = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createRadioGroup("Tool Permission", "security_role", [
    ["admin", "Admin"],
    ["staff", "Staff"],
    ["viewer", "Viewer"],
  ], state.config.security.role, (value) => {
    state.config.security.role = value;
    renderConfigPreview();
  }, locked));
}

function renderProductionControls(container, locked) {
  container.appendChild(createCheckbox("Enable Production Mode", state.config.production.enabled, (value) => {
    state.config.production.enabled = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Enable Model Routing", state.config.production.model_routing, (value) => {
    state.config.production.model_routing = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Enable Logging", state.config.production.logging, (value) => {
    state.config.production.logging = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Enable Fallback", state.config.production.fallback, (value) => {
    state.config.production.fallback = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Enable Cost Control", state.config.production.cost_control, (value) => {
    state.config.production.cost_control = value;
    renderConfigPreview();
  }, locked));
}

function createSelect(label, options, selected, onChange, disabled) {
  const wrap = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = label;

  const select = document.createElement("select");
  select.disabled = disabled;

  options.forEach(([value, text]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    option.selected = value === selected;
    select.appendChild(option);
  });

  select.addEventListener("change", (event) => onChange(event.target.value));

  wrap.appendChild(title);
  wrap.appendChild(select);
  return wrap;
}

function createTextarea(label, value, onChange, disabled) {
  const wrap = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = label;

  const input = document.createElement("textarea");
  input.value = value;
  input.disabled = disabled;
  input.rows = 4;
  input.addEventListener("input", (event) => onChange(event.target.value));

  wrap.appendChild(title);
  wrap.appendChild(input);
  return wrap;
}

function createTextInput(label, value, onChange, disabled, placeholder = "") {
  const wrap = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = label;

  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  input.placeholder = placeholder;
  input.disabled = disabled;
  input.addEventListener("input", (event) => onChange(event.target.value));

  wrap.appendChild(title);
  wrap.appendChild(input);
  return wrap;
}

function createCheckbox(label, value, onChange, disabled) {
  const wrap = document.createElement("label");
  wrap.className = "inline";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = value;
  input.disabled = disabled;
  input.addEventListener("change", (event) => onChange(event.target.checked));

  wrap.appendChild(input);
  wrap.appendChild(document.createTextNode(label));
  return wrap;
}

function createRange(label, min, max, step, value, onChange, disabled) {
  const wrap = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = `${label}: ${value}`;

  const input = document.createElement("input");
  input.type = "range";
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.disabled = disabled;
  input.addEventListener("input", (event) => {
    title.textContent = `${label}: ${event.target.value}`;
    onChange(event.target.value);
  });

  wrap.appendChild(title);
  wrap.appendChild(input);
  return wrap;
}

function createRadioGroup(titleText, name, options, selected, onChange, disabled) {
  const wrap = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = titleText;
  wrap.appendChild(title);

  const box = document.createElement("div");
  box.className = "option-grid";

  options.forEach(([value, label]) => {
    const row = document.createElement("label");
    row.className = "inline";

    const input = document.createElement("input");
    input.type = "radio";
    input.name = `${name}_${state.currentSection}`;
    input.value = value;
    input.checked = selected === value;
    input.disabled = disabled;
    input.addEventListener("change", () => onChange(value));

    row.appendChild(input);
    row.appendChild(document.createTextNode(label));
    box.appendChild(row);
  });

  wrap.appendChild(box);
  return wrap;
}

function createCheckboxList(titleText, options, selectedArray, onChange, disabled) {
  const wrap = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = titleText;
  wrap.appendChild(title);

  const box = document.createElement("div");
  box.className = "checkbox-list";

  options.forEach(([value, label]) => {
    const row = document.createElement("label");
    row.className = "inline";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = value;
    input.checked = selectedArray.includes(value);
    input.disabled = disabled;
    input.addEventListener("change", () => {
      const next = Array.from(box.querySelectorAll("input[type='checkbox']"))
        .filter((item) => item.checked)
        .map((item) => item.value);
      onChange(next);
    });

    row.appendChild(input);
    row.appendChild(document.createTextNode(label));
    box.appendChild(row);
  });

  wrap.appendChild(box);
  return wrap;
}

function buildExportedConfig() {
  enforceCodeExecMemoryPolicy();
  return {
    llm: {
      model: state.config.llm.model,
      system_prompt: state.config.llm.system_prompt,
      memory: state.config.llm.memory,
      memory_rounds: state.config.llm.memory_rounds,
      rag: state.config.llm.rag,
      temperature: state.config.llm.temperature,
    },
    workflow: {
      enabled: state.currentSection >= 1,
      mode: state.config.workflow.mode,
      router_mode: state.config.workflow.router_mode || "pydantic",
      routes: [],
    },
    tool: {
      enabled: state.currentSection >= 2 ? state.config.tool.enabled : false,
      tools: ["create_task", "search_web"],
      mode: state.config.tool.mode,
    },
    webhook: {
      enabled: state.currentSection >= 3 ? state.config.webhook.enabled : false,
      workflows: ["calendar_query"],
      mode: state.config.webhook.mode || "manual",
      endpoints: {
        calendar_query: state.config.webhook.calendar_query_url || "",
      },
    },
    code_execution: {
      enabled: state.currentSection >= 4 ? state.config.code_execution.enabled : false,
      libraries: state.config.code_execution.libraries,
      auto_run: state.config.code_execution.auto_run,
    },
    security: {
      moderation: state.currentSection >= 5 ? state.config.security.moderation : false,
      guardrails: state.currentSection >= 5 ? state.config.security.guardrails : false,
      injection_protection: state.config.security.injection_protection,
      role: state.config.security.role,
    },
    production: {
      enabled: state.currentSection >= 6 ? state.config.production.enabled : false,
      model_routing: state.config.production.model_routing,
      logging: state.config.production.logging,
      fallback: state.config.production.fallback,
      cost_control: state.config.production.cost_control,
    },
  };
}

function renderConfigPreview() {
  configPreview.textContent = JSON.stringify(buildExportedConfig(), null, 2);
  scheduleSaveState();
}

async function loadTasksFromBackend() {
  if (!hasBackend) {
    renderTaskPanel();
    return;
  }

  try {
    const response = await fetch(`${backendUrl}/tasks`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  } catch (_error) {
    state.tasks = [];
  }
  renderTaskPanel();
}

async function handleAddTask() {
  const title = taskInputEl.value.trim();
  if (!title) return;
  if (!hasBackend) {
    state.tasks.push({
      id: `local_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
      title,
      status: "pending",
      source: "manual",
    });
    taskInputEl.value = "";
    scheduleSaveState();
    renderTaskPanel();
    return;
  }

  try {
    const response = await fetch(`${backendUrl}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, source: "manual" }),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.tasks = Array.isArray(payload.tasks) ? payload.tasks : state.tasks;
    taskInputEl.value = "";
    renderTaskPanel();
  } catch (error) {
    alert(`新增任務失敗：${String(error)}`);
  }
}

async function handleToggleTask(taskId) {
  if (!hasBackend) {
    const task = state.tasks.find((item) => item.id === taskId);
    if (!task) return;
    task.status = task.status === "done" ? "pending" : "done";
    scheduleSaveState();
    renderTaskPanel();
    return;
  }
  try {
    const response = await fetch(`${backendUrl}/tasks/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.tasks = Array.isArray(payload.tasks) ? payload.tasks : state.tasks;
    renderTaskPanel();
  } catch (error) {
    alert(`更新任務失敗：${String(error)}`);
  }
}

function startEditTask(taskId) {
  const task = state.tasks.find((item) => item.id === taskId);
  if (!task) return;
  taskEditingId = taskId;
  taskEditingDraft = String(task.title || "");
  renderTaskPanel();
}

function cancelEditTask() {
  taskEditingId = null;
  taskEditingDraft = "";
  renderTaskPanel();
}

async function saveEditTask(taskId) {
  const title = String(taskEditingDraft || "").trim();
  if (!title) {
    alert("任務名稱不能為空。");
    return;
  }

  if (!hasBackend) {
    const task = state.tasks.find((item) => item.id === taskId);
    if (!task) return;
    task.title = title;
    taskEditingId = null;
    taskEditingDraft = "";
    scheduleSaveState();
    renderTaskPanel();
    return;
  }

  try {
    let response = await fetch(`${backendUrl}/tasks/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, title }),
    });
    if (response.status === 404) {
      response = await fetch(`${backendUrl}/tasks/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId, title }),
      });
    }
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.tasks = Array.isArray(payload.tasks) ? payload.tasks : state.tasks;
    taskEditingId = null;
    taskEditingDraft = "";
    renderTaskPanel();
  } catch (error) {
    alert(`編輯任務失敗：${String(error)}`);
  }
}

async function handleDeleteTask(taskId) {
  const task = state.tasks.find((item) => item.id === taskId);
  if (!task) return;

  if (!hasBackend) {
    state.tasks = state.tasks.filter((item) => item.id !== taskId);
    scheduleSaveState();
    renderTaskPanel();
    return;
  }

  try {
    let response = await fetch(`${backendUrl}/tasks/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    });
    if (response.status === 404) {
      response = await fetch(`${backendUrl}/tasks/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId }),
      });
    }
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.tasks = Array.isArray(payload.tasks) ? payload.tasks : state.tasks;
    renderTaskPanel();
  } catch (error) {
    alert(`刪除任務失敗：${String(error)}`);
  }
}

function renderTaskPanel() {
  taskListEl.innerHTML = "";
  taskInputEl.disabled = false;
  addTaskBtn.disabled = false;

  if (!state.tasks.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty";
    empty.textContent = "目前沒有任務，請新增第一個 task。";
    taskListEl.appendChild(empty);
    return;
  }

  const orderedTasks = state.tasks
    .map((task, idx) => ({ task, idx }))
    .sort((a, b) => {
      const aDone = a.task.status === "done" ? 1 : 0;
      const bDone = b.task.status === "done" ? 1 : 0;
      if (aDone !== bDone) return aDone - bDone;
      return a.idx - b.idx;
    })
    .map((item) => item.task);

  orderedTasks.forEach((task) => {
    const row = document.createElement("div");
    row.className = "task-item";
    if (task.status === "done") {
      row.classList.add("done");
    }

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = task.status === "done";
    checkbox.addEventListener("change", () => handleToggleTask(task.id));

    const isEditing = taskEditingId === task.id;
    const titleWrap = document.createElement("div");
    titleWrap.className = "task-title-wrap";

    let title;
    if (isEditing) {
      title = document.createElement("input");
      title.type = "text";
      title.className = "task-title-input";
      title.value = taskEditingDraft;
      title.addEventListener("input", (event) => {
        taskEditingDraft = event.target.value;
      });
      title.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          saveEditTask(task.id);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          cancelEditTask();
        }
      });
      setTimeout(() => title.focus(), 0);
    } else {
      title = document.createElement("span");
      title.className = "task-title";
      title.textContent = task.title || "(untitled task)";
    }
    titleWrap.appendChild(title);

    const source = document.createElement("span");
    source.className = "task-source";
    source.textContent = task.source || "manual";

    const actions = document.createElement("div");
    actions.className = "task-actions";

    if (isEditing) {
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "task-action-btn";
      saveBtn.textContent = "Save";
      saveBtn.addEventListener("click", () => saveEditTask(task.id));

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "task-action-btn";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", cancelEditTask);

      actions.appendChild(saveBtn);
      actions.appendChild(cancelBtn);
    } else {
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "task-action-btn";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => startEditTask(task.id));

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "task-action-btn danger";
      deleteBtn.textContent = "Delete";
      deleteBtn.addEventListener("click", () => handleDeleteTask(task.id));

      actions.appendChild(editBtn);
      actions.appendChild(deleteBtn);
    }

    row.appendChild(checkbox);
    row.appendChild(titleWrap);
    row.appendChild(source);
    row.appendChild(actions);
    taskListEl.appendChild(row);
  });
}

function renderRouteConfirmBar() {
  const conversation = getCurrentConversation();
  const pending = conversation?.pendingRoute || null;
  const stage = pending?.stage || "";
  const isCollecting = pending && (stage === "collect_datetime" || stage === "collect_code_requirements");
  if (!conversation || !pending || isCollecting || !isConfirmPendingRoute(pending)) {
    routeConfirmBar.hidden = true;
    chatInputRow?.classList.remove("confirm-pending");
    chatInput.disabled = false;
    chatImageInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.placeholder = DEFAULT_CHAT_PLACEHOLDER;
    return;
  }
  routeConfirmText.textContent = `是否要執行 ${pending.action_type}：${pending.target}？`;
  routeConfirmBar.hidden = false;
  chatInputRow?.classList.add("confirm-pending");
  chatInput.disabled = true;
  chatImageInput.disabled = true;
  sendBtn.disabled = true;
  chatInput.placeholder = "請點選 Yes / No 按鈕確認是否執行動作";
}

function safeParseJson(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    return { parse_error: "invalid JSON", raw: text };
  }
}

function renderChat() {
  const conversation = getCurrentConversation();
  chatHistory.innerHTML = "";
  if (!conversation) return;

  conversation.messages.forEach((msg) => {
    const el = document.createElement("div");
    el.className = `msg ${msg.role}`;
    if (msg.thinking) el.classList.add("thinking");

    const content = document.createElement("div");
    content.className = "msg-content";
    if (msg.role === "assistant" && !msg.thinking) {
      content.innerHTML = renderMarkdown(msg.text || "");
    } else {
      content.innerHTML = renderPlainText(msg.text || "");
    }

    el.appendChild(content);
    chatHistory.appendChild(el);
  });

  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function renderPlainText(text) {
  const normalized = normalizeEscapedNewlines(text);
  return escapeHtml(normalized).replace(/\n/g, "<br>");
}

function renderMarkdown(text) {
  const normalizedText = normalizeReferenceTitleLinks(normalizeEscapedNewlines(text));
  const escaped = escapeHtml(normalizedText);
  const fencedRe = /```([\s\S]*?)```/g;
  const codeBlocks = [];
  let withCodeTokens = escaped.replace(fencedRe, (_m, code) => {
    const token = `@@CODEBLOCK_${codeBlocks.length}@@`;
    codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
    return token;
  });

  withCodeTokens = withCodeTokens
    .replace(
      /!\[([^\]]*)\]\((data:image\/[a-zA-Z0-9.+-]+;base64,[^)]+|https?:\/\/[^\s)]+)\)/g,
      '<img src="$2" alt="$1" loading="lazy" />',
    )
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    )
    .replace(
      /(^|[\s(>])(https?:\/\/[^\s<)]+)/g,
      '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>',
    );

  const lines = withCodeTokens.split("\n");
  const html = [];
  let inUl = false;
  let inOl = false;

  lines.forEach((line) => {
    const h4Match = line.match(/^\s*####\s+(.+)$/);
    const h3Match = line.match(/^\s*###\s+(.+)$/);
    const h2Match = line.match(/^\s*##\s+(.+)$/);
    const h1Match = line.match(/^\s*#\s+(.+)$/);
    const ulMatch = line.match(/^\s*[-*]\s+(.+)$/);
    const olMatch = line.match(/^\s*\d+\.\s+(.+)$/);

    if (h4Match || h3Match || h2Match || h1Match) {
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
      if (h4Match) {
        html.push(`<h4>${h4Match[1]}</h4>`);
      } else if (h3Match) {
        html.push(`<h3>${h3Match[1]}</h3>`);
      } else if (h2Match) {
        html.push(`<h2>${h2Match[1]}</h2>`);
      } else {
        html.push(`<h1>${h1Match[1]}</h1>`);
      }
      return;
    }

    if (ulMatch) {
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        html.push("<ul>");
        inUl = true;
      }
      html.push(`<li>${ulMatch[1]}</li>`);
      return;
    }

    if (olMatch) {
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        html.push("<ol>");
        inOl = true;
      }
      html.push(`<li>${olMatch[1]}</li>`);
      return;
    }

    if (inUl) {
      html.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      html.push("</ol>");
      inOl = false;
    }

    if (!line.trim()) {
      html.push("<br>");
      return;
    }
    html.push(`<p>${line}</p>`);
  });

  if (inUl) html.push("</ul>");
  if (inOl) html.push("</ol>");

  let out = html.join("");
  codeBlocks.forEach((block, idx) => {
    out = out.replace(`@@CODEBLOCK_${idx}@@`, block);
  });
  return out;
}

function normalizeEscapedNewlines(text) {
  return String(text || "").replace(/\\n/g, "\n");
}

function normalizeReferenceTitleLinks(text) {
  const lines = String(text || "").split("\n");
  const out = [];

  for (let i = 0; i < lines.length; i += 1) {
    const current = lines[i] || "";
    const next = lines[i + 1] || "";

    const titleMatch = current.match(/^(\s*\d+\.\s+)(.+)$/);
    const urlMatch = next.trim().match(/^(https?:\/\/\S+)$/);

    if (titleMatch && urlMatch) {
      const prefix = titleMatch[1];
      const title = titleMatch[2].trim();
      const url = urlMatch[1].trim();
      out.push(`${prefix}[${title}](${url})`);
      i += 1;
      continue;
    }

    out.push(current);
  }

  return out.join("\n");
}

function escapeHtml(raw) {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

init();
