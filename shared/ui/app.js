const sectionNames = {
  0: "Section 0 - LLM Core",
  1: "Section 1 - Workflow Routing",
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
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

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
      enabled: false,
      mode: "rule",
      routes: [],
    },
    tool: {
      enabled: false,
      tools: [],
      mode: "auto",
    },
    webhook: {
      enabled: false,
      workflows: [],
      endpoints_json: '{"notify":"","task":"","query":""}',
    },
    code_execution: {
      enabled: false,
      mode: "safe",
      libraries: [],
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
};

const sectionSelect = document.getElementById("current-section");
const sectionBadge = document.getElementById("chat-section-badge");
const controlsRoot = document.getElementById("controls-root");
const configPreview = document.getElementById("config-preview");
const chatHistory = document.getElementById("chat-history");
const chatInput = document.getElementById("chat-input");
const chatImageInput = document.getElementById("chat-image");
const sendBtn = document.getElementById("send-btn");
const sectionTemplate = document.getElementById("section-card-template");
const conversationList = document.getElementById("conversation-list");
const newChatBtn = document.getElementById("new-chat-btn");
const currentChatTitle = document.getElementById("current-chat-title");
const taskListEl = document.getElementById("task-list");
const taskInputEl = document.getElementById("task-input");
const addTaskBtn = document.getElementById("add-task-btn");
const runtimeFoldEl = document.getElementById("runtime-fold");
const taskFoldEl = document.getElementById("task-fold");

let pendingImageDataUrl = "";
let saveTimer = null;

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
    scheduleSaveState();
    render();
  });

  sendBtn.addEventListener("click", sendMessage);
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
      return;
    }
    if (!ALLOWED_IMAGE_MIME.has(file.type)) {
      pendingImageDataUrl = "";
      chatImageInput.value = "";
      alert("目前只支援 PNG / JPEG / WebP。請先轉檔再上傳。");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      pendingImageDataUrl = "";
      chatImageInput.value = "";
      alert("圖片太大，請上傳 8MB 以下圖片。");
      return;
    }
    pendingImageDataUrl = await fileToDataUrl(file);
  });

  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  // Accordion behavior: Runtime Config and Task Panel only one open at a time.
  runtimeFoldEl.addEventListener("toggle", () => {
    if (runtimeFoldEl.open) taskFoldEl.open = false;
  });
  taskFoldEl.addEventListener("toggle", () => {
    if (taskFoldEl.open) runtimeFoldEl.open = false;
  });

  render();
  loadConversationsFromBackend();
  loadTasksFromBackend();
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
      state.config.webhook = { ...state.config.webhook, ...(saved.config.webhook || {}) };
      state.config.code_execution = { ...state.config.code_execution, ...(saved.config.code_execution || {}) };
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

function sendMessage() {
  const text = chatInput.value.trim();
  if (!text && !pendingImageDataUrl) return;

  const conversation = getCurrentConversation();
  if (!conversation) return;

  const userDisplayText = pendingImageDataUrl ? `${text || "(未輸入文字)"}\n[已附加圖片]` : text;
  conversation.messages.push({ role: "user", text: userDisplayText });
  bumpConversation(conversation.id);
  scheduleSaveState();

  chatInput.value = "";
  chatImageInput.value = "";
  render();

  maybeGenerateConversationTitle(conversation.id, text || "圖片分析");

  if (!hasBackend) {
    runMockThinkingReply(text || "（圖片訊息）", conversation.id);
    pendingImageDataUrl = "";
    return;
  }

  runBackendThinkingReply(text || "請描述這張圖", pendingImageDataUrl, conversation.id);
  pendingImageDataUrl = "";
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

async function runBackendThinkingReply(userText, imageDataUrl, conversationId) {
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
    replaceThinkingWithFinal(conversationId, thinkingId, data.reply || "後端未回傳內容。");
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
  renderTaskPanel();
}

function renderIfCurrent(conversationId) {
  if (state.currentConversationId === conversationId) {
    renderChat();
    renderCurrentConversationTitle();
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
      scheduleSaveState();
      render();
    });

    const top = document.createElement("div");
    top.className = "conversation-top";

    const title = document.createElement("div");
    title.className = "conversation-title";
    title.textContent = conversation.titleGenerating ? `${conversation.title}...` : conversation.title;

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "edit-title-btn";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      const next = prompt("編輯聊天室標題", conversation.title);
      if (!next) return;
      conversation.title = next.trim() || conversation.title;
      conversation.titleManual = true;
      scheduleSaveState();
      renderConversations();
      renderCurrentConversationTitle();
    });

    top.appendChild(title);
    top.appendChild(editBtn);

    const preview = document.createElement("div");
    preview.className = "conversation-preview";
    const last = getLastVisibleMessage(conversation);
    preview.textContent = last ? last.text.replace(/\n/g, " ") : "尚無訊息";

    item.appendChild(top);
    item.appendChild(preview);
    conversationList.appendChild(item);
  });
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
  controlsRoot.appendChild(renderSectionCard(1, "Workflow Routing", renderWorkflowControls));
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
  const lockedByFreshMode = unlockSection === 0 && !hasBackend;
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
    state.config.llm.memory = value;
    renderConfigPreview();
    renderControls();
  }, locked));

  container.appendChild(createSelect(
    "Memory Rounds (1~10)",
    Array.from({ length: 10 }, (_, i) => [String(i + 1), String(i + 1)]),
    String(state.config.llm.memory_rounds),
    (value) => {
      state.config.llm.memory_rounds = Number(value);
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
  container.appendChild(createCheckbox("Enable Routing", state.config.workflow.enabled, (value) => {
    state.config.workflow.enabled = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createRadioGroup("Routing Strategy", "workflow_mode", [
    ["rule", "Rule-based"],
    ["llm", "LLM-based (advanced)"],
  ], state.config.workflow.mode, (value) => {
    state.config.workflow.mode = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckboxList("Available Routes", [
    ["faq", "FAQ"],
    ["task", "Task Creation"],
    ["notify", "Notification"],
  ], state.config.workflow.routes, (arr) => {
    state.config.workflow.routes = arr;
    renderConfigPreview();
  }, locked));
}

function renderToolControls(container, locked) {
  container.appendChild(createCheckbox("Enable Tool Calling", state.config.tool.enabled, (value) => {
    state.config.tool.enabled = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckboxList("Available Tools", [
    ["create_task", "Create Task"],
    ["send_email", "Send Email"],
    ["query_schedule", "Query Schedule"],
  ], state.config.tool.tools, (arr) => {
    state.config.tool.tools = arr;
    renderConfigPreview();
  }, locked));

  container.appendChild(createRadioGroup("Tool Mode", "tool_mode", [
    ["auto", "Auto (LLM decides)"],
    ["manual", "Manual (debug)"],
  ], state.config.tool.mode, (value) => {
    state.config.tool.mode = value;
    renderConfigPreview();
  }, locked));
}

function renderWebhookControls(container, locked) {
  container.appendChild(createCheckbox("Enable Webhook Mode", state.config.webhook.enabled, (value) => {
    state.config.webhook.enabled = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckboxList("Available Workflows", [
    ["notify", "Notify Team (n8n)"],
    ["task", "Create Task (n8n)"],
    ["query", "Query Data (n8n)"],
  ], state.config.webhook.workflows, (arr) => {
    state.config.webhook.workflows = arr;
    renderConfigPreview();
  }, locked));

  container.appendChild(createTextarea("Endpoint Config (JSON)", state.config.webhook.endpoints_json, (value) => {
    state.config.webhook.endpoints_json = value;
    renderConfigPreview();
  }, locked));
}

function renderCodeExecutionControls(container, locked) {
  container.appendChild(createCheckbox("Enable Code Execution", state.config.code_execution.enabled, (value) => {
    state.config.code_execution.enabled = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createRadioGroup("Execution Mode", "code_mode", [
    ["safe", "Safe Mode (limited)"],
    ["full", "Full Mode (dangerous)"],
  ], state.config.code_execution.mode, (value) => {
    state.config.code_execution.mode = value;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckboxList("Allow Libraries", [
    ["pandas", "pandas"],
    ["matplotlib", "matplotlib"],
    ["numpy", "numpy"],
  ], state.config.code_execution.libraries, (arr) => {
    state.config.code_execution.libraries = arr;
    renderConfigPreview();
  }, locked));

  container.appendChild(createCheckbox("Execute Automatically", state.config.code_execution.auto_run, (value) => {
    state.config.code_execution.auto_run = value;
    renderConfigPreview();
  }, locked));
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
      enabled: state.currentSection >= 1 ? state.config.workflow.enabled : false,
      mode: state.config.workflow.mode,
      routes: state.config.workflow.routes,
    },
    tool: {
      enabled: state.currentSection >= 2 ? state.config.tool.enabled : false,
      tools: state.config.tool.tools,
      mode: state.config.tool.mode,
    },
    webhook: {
      enabled: state.currentSection >= 3 ? state.config.webhook.enabled : false,
      workflows: state.config.webhook.workflows,
      endpoints: safeParseJson(state.config.webhook.endpoints_json),
    },
    code_execution: {
      enabled: state.currentSection >= 4 ? state.config.code_execution.enabled : false,
      mode: state.config.code_execution.mode,
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
    const row = document.createElement("label");
    row.className = "task-item";
    if (task.status === "done") {
      row.classList.add("done");
    }

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = task.status === "done";
    checkbox.addEventListener("change", () => handleToggleTask(task.id));

    const title = document.createElement("span");
    title.className = "task-title";
    title.textContent = task.title || "(untitled task)";

    const source = document.createElement("span");
    source.className = "task-source";
    source.textContent = task.source || "manual";

    row.appendChild(checkbox);
    row.appendChild(title);
    row.appendChild(source);
    taskListEl.appendChild(row);
  });
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
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text);
  const fencedRe = /```([\s\S]*?)```/g;
  const codeBlocks = [];
  let withCodeTokens = escaped.replace(fencedRe, (_m, code) => {
    const token = `@@CODEBLOCK_${codeBlocks.length}@@`;
    codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
    return token;
  });

  withCodeTokens = withCodeTokens
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");

  const lines = withCodeTokens.split("\n");
  const html = [];
  let inUl = false;
  let inOl = false;

  lines.forEach((line) => {
    const ulMatch = line.match(/^\s*[-*]\s+(.+)$/);
    const olMatch = line.match(/^\s*\d+\.\s+(.+)$/);

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

function escapeHtml(raw) {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

init();
