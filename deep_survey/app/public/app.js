const state = {
  currentRunId: null,
  eventSource: null,
  appServerEventSource: null,
  status: null,
  selectedVault: null,
  isCreatingTopic: false,
  localRunningStage: null,
  progressPollTimer: null,
  statusRefreshTimer: null,
  autoPipeline: false,
  lastRunAction: null,
  appThreads: [],
  appThreadsLoaded: false,
  appThreadStatus: {},
  appThreadRunningStages: {},
  appThreadChats: {},
  appThreadAssistantBuffers: {},
  loadedThreadMessages: {},
  topicThreadBindings: {},
  activeDlwThreadId: null,
  dlwStartupBusy: false,
  missingThreadNotices: new Set(),
  pendingApprovals: [],
  setupStatus: null,
  draggedTopicVault: null,
  stagePromptInFlight: false,
  pendingStageAction: null,
  dismissedStagePrompts: new Set(),
  topicContextMenu: null,
  topicRenameDialog: null,
  confirmDialog: null,
  topicPointerDrag: null,
  topicDragGhost: null,
  suppressTopicClick: false,
  topicOrder: [],
  topicOrderSaveTimer: null,
  selectedVaultSaveTimer: null,
  stage3DownloadCount: 0
};

const els = {
  topicInput: document.querySelector("#topicInput"),
  topicDirectoryInput: document.querySelector("#topicDirectoryInput"),
  chooseDirectoryBtn: document.querySelector("#chooseDirectoryBtn"),
  newTopicBtn: document.querySelector("#newTopicBtn"),
  importVaultBtn: document.querySelector("#importVaultBtn"),
  newTopicPanel: document.querySelector("#newTopicPanel"),
  startBtn: document.querySelector("#startBtn"),
  resumeBtn: document.querySelector("#resumeBtn"),
  stage3Btn: document.querySelector("#stage3Btn"),
  manualBtn: document.querySelector("#manualBtn"),
  cancelBtn: document.querySelector("#cancelBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  runTabBtn: document.querySelector("#runTabBtn"),
  vaultTabBtn: document.querySelector("#vaultTabBtn"),
  runTab: document.querySelector("#runTab"),
  vaultTab: document.querySelector("#vaultTab"),
  vaultSearch: document.querySelector("#vaultSearch"),
  vaultFiles: document.querySelector("#vaultFiles"),
  vaultPreview: document.querySelector("#vaultPreview"),
  appServerState: document.querySelector("#appServerState"),
  threadSelect: document.querySelector("#threadSelect"),
  threadDisplay: document.querySelector("#threadHeaderTitle"),
  threadWorkspace: document.querySelector(".thread-workspace"),
  setupPanel: document.querySelector("#setupPanel"),
  setupTitle: document.querySelector("#setupTitle"),
  setupText: document.querySelector("#setupText"),
  setupChecks: document.querySelector("#setupChecks"),
  setupRetryBtn: document.querySelector("#setupRetryBtn"),
  setupInstallBtn: document.querySelector("#setupInstallBtn"),
  threadModelSelect: document.querySelector("#threadModelSelect"),
  threadEffortSelect: document.querySelector("#threadEffortSelect"),
  threadModelMenuBtn: document.querySelector("#threadModelMenuBtn"),
  threadModelMenuLabel: document.querySelector("#threadModelMenuLabel"),
  threadModelMenu: document.querySelector("#threadModelMenu"),
  threadModeSelect: document.querySelector("#threadModeSelect"),
  threadModeMenuBtn: document.querySelector("#threadModeMenuBtn"),
  threadModeMenuLabel: document.querySelector("#threadModeMenuLabel"),
  threadModeMenu: document.querySelector("#threadModeMenu"),
  threadMessage: document.querySelector("#threadMessage"),
  sendThreadBtn: document.querySelector("#sendThreadBtn"),
  stopThreadBtn: document.querySelector("#stopThreadBtn"),
  approvalPanel: document.querySelector("#approvalPanel"),
  approvalMeta: document.querySelector("#approvalMeta"),
  approvalCommand: document.querySelector("#approvalCommand"),
  approvalApproveBtn: document.querySelector("#approvalApproveBtn"),
  approvalDenyBtn: document.querySelector("#approvalDenyBtn"),
  approvalCancelBtn: document.querySelector("#approvalCancelBtn"),
  stageConfirmPanel: document.querySelector("#stageConfirmPanel"),
  stageConfirmTitle: document.querySelector("#stageConfirmTitle"),
  stageConfirmText: document.querySelector("#stageConfirmText"),
  stageConfirmBtn: document.querySelector("#stageConfirmBtn"),
  threadStatusText: document.querySelector("#threadStatusText"),
  threadChat: document.querySelector("#threadChat"),
  threadChatState: document.querySelector("#threadChatState"),
  topicTitle: document.querySelector("#topicTitle"),
  topicList: document.querySelector("#topicList"),
  workspacePath: document.querySelector("#workspacePath"),
  codexPill: document.querySelector("#codexPill"),
  stagePill: document.querySelector("#stagePill"),
  manualPill: document.querySelector("#manualPill"),
  timeline: document.querySelector("#timeline"),
  log: document.querySelector("#log"),
  runState: document.querySelector("#runState")
};
let vaultFiles = [];
let visibleVaultFiles = [];
let selectedVaultFile = null;
const collapsedFolders = new Set();
const threadPreferenceKeys = {
  mode: "dlw.thread.mode.v2",
  model: "dlw.thread.model",
  effort: "dlw.thread.effort",
  bindings: "dlw.topic.thread.bindings",
  topicOrder: "dlw.topic.order"
};
const modelLabels = {
  "gpt-5.5": "GPT-5.5",
  "gpt-5.4": "GPT-5.4",
  "gpt-5.4-mini": "GPT-5.4 Mini",
  "gpt-5.3-codex": "GPT-5.3 Codex"
};
const effortLabels = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "XHigh"
};
const modeLabels = {
  read: "Read Only",
  write: "Allow Edits"
};

function restoreThreadPreferences() {
  const mode = localStorage.getItem(threadPreferenceKeys.mode);
  if (mode && els.threadModeSelect && [...els.threadModeSelect.options].some((option) => option.value === mode)) {
    els.threadModeSelect.value = mode;
  } else {
    const modeInput = mode ? document.querySelector(`input[name="threadMode"][value="${mode}"]`) : null;
    if (modeInput) modeInput.checked = true;
  }

  const model = localStorage.getItem(threadPreferenceKeys.model);
  if (model && [...els.threadModelSelect.options].some((option) => option.value === model)) {
    els.threadModelSelect.value = model;
  }

  const effort = localStorage.getItem(threadPreferenceKeys.effort);
  if (effort && els.threadEffortSelect && [...els.threadEffortSelect.options].some((option) => option.value === effort)) {
    els.threadEffortSelect.value = effort;
  } else {
    const effortInput = effort ? document.querySelector(`input[name="reasoningEffort"][value="${effort}"]`) : null;
    if (effortInput) effortInput.checked = true;
  }

  try {
    state.topicThreadBindings = JSON.parse(localStorage.getItem(threadPreferenceKeys.bindings) || "{}");
  } catch {
    state.topicThreadBindings = {};
  }
  updateModelMenu();
  updateThreadModeMenu();
}

function saveThreadPreferences() {
  localStorage.setItem(threadPreferenceKeys.mode, selectedThreadMode());
  localStorage.setItem(threadPreferenceKeys.model, selectedThreadModel());
  localStorage.setItem(threadPreferenceKeys.effort, selectedReasoningEffort());
  updateModelMenu();
  updateThreadModeMenu();
}

function updateModelMenu() {
  if (!els.threadModelMenuLabel) return;
  const model = selectedThreadModel();
  const effort = selectedReasoningEffort();
  els.threadModelMenuLabel.textContent = `${modelLabels[model] || model || "Model"} ${effortLabels[effort] || effort}`;
  els.threadModelMenuBtn.title = `Model: ${modelLabels[model] || model}, Reasoning: ${effortLabels[effort] || effort}`;
  document.querySelectorAll(".model-option").forEach((button) => {
    button.classList.toggle("selected", button.dataset.model === model);
  });
  document.querySelectorAll(".effort-option").forEach((button) => {
    button.classList.toggle("selected", button.dataset.effort === effort);
  });
}

function setModelMenuOpen(open) {
  if (!els.threadModelMenu || !els.threadModelMenuBtn) return;
  els.threadModelMenu.classList.toggle("hidden", !open);
  els.threadModelMenuBtn.setAttribute("aria-expanded", String(open));
}

function updateThreadModeMenu() {
  if (!els.threadModeMenuLabel) return;
  const mode = selectedThreadMode();
  els.threadModeMenuLabel.textContent = modeLabels[mode] || mode || "Read Only";
  els.threadModeMenuBtn.title = `Mode: ${modeLabels[mode] || mode}`;
  document.querySelectorAll(".permission-option").forEach((button) => {
    button.classList.toggle("selected", button.dataset.mode === mode);
  });
}

function setThreadModeMenuOpen(open) {
  if (!els.threadModeMenu || !els.threadModeMenuBtn) return;
  els.threadModeMenu.classList.toggle("hidden", !open);
  els.threadModeMenuBtn.setAttribute("aria-expanded", String(open));
}

function selectThreadModel(model) {
  if (!model || !els.threadModelSelect) return;
  els.threadModelSelect.value = model;
  saveThreadPreferences();
}

function selectReasoningEffort(effort) {
  if (!effort || !els.threadEffortSelect) return;
  els.threadEffortSelect.value = effort;
  saveThreadPreferences();
}

function setSelectedThreadMode(mode) {
  if (els.threadModeSelect) els.threadModeSelect.value = mode;
  const input = document.querySelector(`input[name="threadMode"][value="${mode}"]`);
  if (input) input.checked = true;
  saveThreadPreferences();
  renderThreadStatus();
}

function saveTopicThreadBindings() {
  localStorage.setItem(threadPreferenceKeys.bindings, JSON.stringify(state.topicThreadBindings));
}

function loadLocalTopicOrder() {
  try {
    const order = JSON.parse(localStorage.getItem(threadPreferenceKeys.topicOrder) || "[]");
    return Array.isArray(order) ? order : [];
  } catch {
    return [];
  }
}

function loadTopicOrder() {
  return state.topicOrder.length ? state.topicOrder : loadLocalTopicOrder();
}

function persistTopicOrderToServer(order) {
  if (state.topicOrderSaveTimer) clearTimeout(state.topicOrderSaveTimer);
  state.topicOrderSaveTimer = setTimeout(() => {
    state.topicOrderSaveTimer = null;
    api("/api/preferences/topic-order", {
      method: "POST",
      body: JSON.stringify({ topicOrder: order })
    }).catch(showError);
  }, 150);
}

function saveTopicOrder(order, options = {}) {
  state.topicOrder = order;
  localStorage.setItem(threadPreferenceKeys.topicOrder, JSON.stringify(order));
  if (options.persist !== false) persistTopicOrderToServer(order);
}

function persistSelectedVaultToServer(vault) {
  if (state.selectedVaultSaveTimer) clearTimeout(state.selectedVaultSaveTimer);
  state.selectedVaultSaveTimer = setTimeout(() => {
    state.selectedVaultSaveTimer = null;
    api("/api/preferences/selected-vault", {
      method: "POST",
      body: JSON.stringify({ selectedVault: vault || "" })
    }).catch(showError);
  }, 150);
}

function orderedTopics(topics) {
  const order = loadTopicOrder();
  if (!order.length) return topics;
  const index = new Map(order.map((vault, position) => [vault, position]));
  return [...topics].sort((a, b) => {
    const aIndex = index.has(a.vault) ? index.get(a.vault) : Number.MAX_SAFE_INTEGER;
    const bIndex = index.has(b.vault) ? index.get(b.vault) : Number.MAX_SAFE_INTEGER;
    return aIndex - bIndex;
  });
}

function topicThreadKey(topic = state.status?.selectedTopic, fallbackTopic = "") {
  if (topic?.vault) return `vault:${topic.vault}`;
  const name = (topic?.topic || fallbackTopic || "").trim();
  return name ? `topic:${name.toLowerCase()}` : "";
}

function boundThreadIdForTopic(topic = state.status?.selectedTopic, fallbackTopic = "") {
  const key = topicThreadKey(topic, fallbackTopic);
  return key ? state.topicThreadBindings[key] || "" : "";
}

function bindThreadToTopic(threadId, topic = state.status?.selectedTopic, fallbackTopic = "") {
  const key = topicThreadKey(topic, fallbackTopic);
  if (!threadId || !key) return;
  state.topicThreadBindings[key] = threadId;
  saveTopicThreadBindings();
}

function forgetThreadBinding(topic = state.status?.selectedTopic, fallbackTopic = "") {
  const key = topicThreadKey(topic, fallbackTopic);
  if (!key) return;
  delete state.topicThreadBindings[key];
  saveTopicThreadBindings();
}

function reconcileTopicThreadBinding(topic = state.status?.selectedTopic) {
  if (!topic?.topic || !topic?.vault) return;
  const vaultKey = topicThreadKey(topic);
  const topicKey = topicThreadKey(null, topic.topic);
  if (vaultKey && topicKey && vaultKey !== topicKey && state.topicThreadBindings[topicKey]) {
    if (state.topicThreadBindings[vaultKey] === state.topicThreadBindings[topicKey]) {
      delete state.topicThreadBindings[vaultKey];
    }
    delete state.topicThreadBindings[topicKey];
    saveTopicThreadBindings();
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

async function refreshStatus() {
  const query = state.selectedVault ? `?vault=${encodeURIComponent(state.selectedVault)}` : "";
  const status = await api(`/api/status${query}`);
  state.status = status;
  state.selectedVault = status.selectedTopic?.vault || status.selectedVault || state.selectedVault;
  state.stage3DownloadCount = status.stage3Downloads?.count ?? 0;
  const serverTopicOrder = Array.isArray(status.topicOrder) ? status.topicOrder : [];
  if (serverTopicOrder.length) {
    saveTopicOrder(serverTopicOrder, { persist: false });
  } else {
    const localTopicOrder = loadLocalTopicOrder();
    state.topicOrder = localTopicOrder;
    if (localTopicOrder.length) saveTopicOrder(localTopicOrder);
  }
  if (!state.selectedVault && !(status.topics || []).length) state.isCreatingTopic = true;
  renderStatus(status);
}

function scheduleStatusRefresh(delay = 700) {
  if (state.statusRefreshTimer) clearTimeout(state.statusRefreshTimer);
  state.statusRefreshTimer = setTimeout(async () => {
    state.statusRefreshTimer = null;
    try {
      await refreshStatus();
    } catch (error) {
      showError(error);
    }
  }, delay);
}

function renderStatus(status) {
  const selectedTopic = state.isCreatingTopic ? newTopicSelection() : status.selectedTopic || {};
  reconcileTopicThreadBinding(selectedTopic);
  const displayTopic = withLocalRunningStage(selectedTopic);
  const topic = selectedTopic.topic || status.state?.topic || "No active topic";
  const showActiveBadge = topicHasIncompleteProgress(displayTopic);
  els.topicTitle.innerHTML = showActiveBadge
    ? `${escapeHtml(topic)} <span class="topic-title-badge">active</span>`
    : escapeHtml(topic);
  const workspacePath = displayVaultPath(status.workspaceRoot, selectedTopic.vault);
  els.workspacePath.textContent = workspacePath;
  els.workspacePath.title = workspacePath;
  els.newTopicBtn.classList.toggle("selected", state.isCreatingTopic);

  renderCodexPill();
  setPill(els.stagePill, `Next: ${labelStage(displayTopic.nextStage)}`, displayTopic.nextStage === "stage_3_pdf_acquisition" ? "warn" : "ok");
  setPill(els.manualPill, `Manual PDFs: ${displayTopic.manualPdfCount ?? 0}`, (displayTopic.manualPdfCount ?? 0) > 0 ? "warn" : "ok");

  els.newTopicPanel.classList.toggle("hidden", !state.isCreatingTopic);
  if (state.isCreatingTopic && els.topicDirectoryInput && !els.topicDirectoryInput.value) {
    els.topicDirectoryInput.value = status.workspaceRoot || "";
  }
  const stage3Ready = Boolean(displayTopic.vault) && displayTopic.nextStage === "stage_3_pdf_acquisition" && !state.currentRunId;
  if (els.stage3Btn) {
    els.stage3Btn.disabled = !stage3Ready;
    els.stage3Btn.classList.toggle("stage3-ready", stage3Ready);
  }
  if (els.manualBtn) els.manualBtn.disabled = !selectedTopic.vault || Boolean(state.currentRunId);
  els.resumeBtn.disabled = !selectedTopic.vault || !topicHasIncompleteProgress(displayTopic) || hasRunningProcess();
  els.startBtn.disabled = Boolean(state.currentRunId || state.dlwStartupBusy);
  els.startBtn.textContent = state.dlwStartupBusy ? "Starting..." : "Start";
  els.cancelBtn.disabled = !hasRunningProcess();
  maybePromptStageAction(displayTopic);

  els.timeline.replaceChildren(...(displayTopic.stages || []).map((stage) => renderStageRow(stage, displayTopic.nextStage)));
  renderTopics(status);
  let boundThreadId = state.appThreadsLoaded ? boundThreadIdForTopic(selectedTopic) : "";
  if (state.appThreadsLoaded && boundThreadId && !threadLooksLikeDlwWorkThread(boundThreadId, selectedTopic)) {
    forgetThreadBinding(selectedTopic);
    boundThreadId = "";
  }
  const matchingThreadId = state.appThreadsLoaded ? matchingThreadIdByTopicName(state.appThreads, selectedTopic) : "";
  const selectedThreadForTopic = boundThreadId || matchingThreadId || null;
  if (selectedThreadForTopic && matchingThreadId && !boundThreadId) {
    bindThreadToTopic(matchingThreadId, selectedTopic);
  }
  if (selectedThreadForTopic) {
    ensureThreadInList(selectedThreadForTopic, `DLW: ${selectedTopic.topic || selectedThreadForTopic}`);
  }
  if (state.appThreads.length || selectedThreadForTopic || selectedThreadId()) {
    renderThreadOptions(state.appThreads, selectedThreadForTopic);
  }
  ensureBoundThreadForExistingTopic(selectedTopic);
}

function displayVaultPath(workspaceRoot, vault) {
  if (!vault) return workspaceRoot;
  if (vault.startsWith("/")) return vault;
  return `${workspaceRoot}/${vault}`;
}

function ensureBoundThreadForExistingTopic(topicInfo) {
  if (!state.appThreadsLoaded || state.isCreatingTopic || state.dlwStartupBusy || state.currentRunId) return;
  if (!topicInfo?.active || !topicInfo.topic || !topicInfo.vault) return;
  if (boundThreadIdForTopic(topicInfo)) return;
  const key = topicThreadKey(topicInfo);
  if (!key) return;
  const matchingThreadId = matchingThreadIdByTopicName(state.appThreads, topicInfo);
  if (matchingThreadId) {
    bindThreadToTopic(matchingThreadId, topicInfo);
    ensureThreadInList(matchingThreadId, `DLW: ${topicInfo.topic || matchingThreadId}`);
    renderThreadOptions(state.appThreads, matchingThreadId);
    state.missingThreadNotices.delete(key);
    return;
  }
  if (!state.missingThreadNotices.has(key)) {
    state.missingThreadNotices.add(key);
    appendLog("meta", `No existing DLW thread matched ${topicInfo.topic}; no new thread was created.`);
  }
}

function withLocalRunningStage(selectedTopic) {
  const running = runningStageForTopic(selectedTopic);
  if (!running.stage || !selectedTopic?.stages) return selectedTopic;
  return {
    ...selectedTopic,
    stages: selectedTopic.stages.map((stage) => {
      if (stage.id !== running.stage || stage.status === "done") return stage;
      return {
        ...stage,
        status: "in_progress",
        isActive: true,
        isLocalRunning: true,
        isWaitingApproval: running.status === "waiting_approval",
        isStopping: running.status === "stopping"
      };
    })
  };
}

function isActiveAppThreadStatus(status) {
  return ["running", "waiting_approval", "stopping"].includes(status?.status);
}

function inferredRunningStageFromTopic(topic) {
  return (
    topic?.nextStage ||
    topic?.stages?.find((stage) => stage.status === "in_progress" || stage.isActive || stage.status === "pending")?.id ||
    null
  );
}

function runningStageForTopic(topic) {
  if (state.currentRunId && state.localRunningStage) {
    return { stage: state.localRunningStage, status: "running" };
  }
  let threadId = boundThreadIdForTopic(topic);
  if (!threadId && state.isCreatingTopic) threadId = state.activeDlwThreadId || selectedThreadId();
  const status = state.appThreadStatus[threadId];
  if (!isActiveAppThreadStatus(status)) return { stage: null, status: null };
  const isBoundDlwThread = threadId && boundThreadIdForTopic(topic) === threadId && threadLooksLikeDlwWorkThread(threadId, topic);
  const stage =
    state.appThreadRunningStages[threadId] ||
    (state.activeDlwThreadId === threadId || isBoundDlwThread ? inferredRunningStageFromTopic(topic) : null);
  return {
    stage,
    status: status.status
  };
}

function setPill(el, text, kind) {
  el.textContent = text;
  el.className = `pill ${kind || ""}`;
}

function setupIssueDetails(setup = state.setupStatus) {
  if (!setup) return "";
  const issues = [];
  if (!setup.codex?.ok) issues.push(`Codex app: ${setup.codex?.error || "missing"}`);
  if (!setup.workspacePlugin?.ok) issues.push("Workspace plugin missing");
  if (!setup.codexPlugin?.ok) issues.push("Codex plugin cache missing");
  if (!setup.skills?.deepLiterature) issues.push(`DLW skill: ${setup.skills?.error || "not visible"}`);
  return issues.join("; ");
}

function renderCodexPill() {
  if (!els.codexPill) return;
  const setup = state.setupStatus;
  const status = state.status;
  els.codexPill.classList.remove("actionable");
  els.codexPill.title = "";
  if (status?.codex && !status.codex.ok) {
    setPill(els.codexPill, "Codex missing", "warn");
    els.codexPill.classList.add("actionable");
    els.codexPill.title = "Click to check Codex setup.";
    return;
  }
  if (setup && !setup.ok) {
    setPill(els.codexPill, "Codex setup issue", "warn");
    els.codexPill.classList.add("actionable");
    els.codexPill.title = `${setupIssueDetails(setup)}. Click to repair setup.`;
    return;
  }
  setPill(els.codexPill, "Codex ready", "ok");
}

function renderStageRow(stage, nextStage) {
  const row = document.createElement("div");
  const classes = ["stage-row"];
  if (stage.status === "done") classes.push("done");
  if (stage.isLocalRunning) classes.push("running");
  else if (stage.status === "in_progress") classes.push("paused");
  if (stage.id === nextStage || stage.isActive) classes.push("active");
  if (stage.id === "stage_3_pdf_acquisition" && stage.id === nextStage) classes.push("pending-stage3");
  if (stage.status === "blocked") classes.push("blocked");
  row.className = classes.join(" ");
  row.innerHTML = `
    <span class="stage-dot"></span>
    <span class="stage-label">${stage.label}</span>
    <span class="stage-status">${stageStatusText(stage)}</span>
  `;
  return row;
}

function stageStatusText(stage) {
  if (stage.isLocalRunning && stage.id === "stage_4_paper_deep_reading") return "deep reading";
  if (stage.isWaitingApproval) return "waiting approval";
  if (stage.isStopping) return "stopping";
  if (stage.isLocalRunning) return "running";
  if (stage.status === "in_progress") return "paused";
  if (stage.isActive) return "next";
  return stage.status;
}

function topicHasIncompleteProgress(topic) {
  const stageList = topic?.stages?.length
    ? topic.stages
    : Object.entries(topic?.stageStatus || {}).map(([id, status]) => ({ id, status }));
  const visibleStages = stageList.filter((stage) => stage.id !== "stage_5c_evidence_matrices");
  if (!visibleStages.length) {
    const text = `${topic?.status || ""} ${topic?.nextStage || ""}`.toLowerCase();
    return !text.includes("all stages complete") && !text.includes("complete");
  }
  return visibleStages.some((stage) => (stage.rawStatus || stage.status) !== "done");
}

function renderTopics(status) {
  const topics = orderedTopics(status.topics || []);
  if (!topics.length) {
    const empty = document.createElement("div");
    empty.className = "topic-meta";
    empty.textContent = "No topics yet";
    els.topicList.replaceChildren(empty);
    return;
  }
  els.topicList.replaceChildren(
    ...topics.map((topic) => {
      const showActive = topicHasIncompleteProgress(topic);
      const item = document.createElement("div");
      item.className = `topic-item ${showActive ? "active" : ""} ${!state.isCreatingTopic && topic.vault === state.selectedVault ? "selected" : ""}`;
      item.setAttribute("role", "button");
      item.setAttribute("draggable", "false");
      item.dataset.vault = topic.vault;
      item.tabIndex = 0;
      item.innerHTML = `
        <span class="topic-name">${escapeHtml(topic.topic)}</span>
        ${showActive ? '<span class="active-badge">active</span>' : ""}
      `;
      item.addEventListener("click", (event) => {
        if (state.suppressTopicClick) {
          event.preventDefault();
          state.suppressTopicClick = false;
          return;
        }
        selectTopic(topic.vault);
      });
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          startTopicRename(topic, item);
        } else if (event.key === " ") {
          event.preventDefault();
          selectTopic(topic.vault);
        }
      });
      item.addEventListener("contextmenu", (event) => showTopicContextMenu(event, topic, item));
      addTopicPointerDragHandlers(item, topic, status);
      return item;
    })
  );
}

function reorderTopics(fromVault, toVault, status) {
  const nextOrder = orderedTopics(status.topics || []).map((entry) => entry.vault);
  const fromIndex = nextOrder.indexOf(fromVault);
  const toIndex = nextOrder.indexOf(toVault);
  if (fromIndex < 0 || toIndex < 0) return;
  const [moved] = nextOrder.splice(fromIndex, 1);
  const targetIndex = nextOrder.indexOf(toVault);
  nextOrder.splice(targetIndex < 0 ? nextOrder.length : targetIndex, 0, moved);
  saveTopicOrder(nextOrder);
  renderTopics(status);
}

function clearTopicDragOver() {
  document.querySelectorAll(".topic-item.drag-over").forEach((item) => item.classList.remove("drag-over"));
}

function topicItemAtPoint(x, y, fromVault) {
  const items = [...document.querySelectorAll(".topic-item")].filter((item) => item.dataset.vault !== fromVault);
  if (!items.length) return null;
  const direct = document.elementFromPoint(x, y)?.closest(".topic-item");
  if (direct?.dataset.vault && direct.dataset.vault !== fromVault) return direct;
  return items
    .map((item) => {
      const rect = item.getBoundingClientRect();
      const centerY = rect.top + rect.height / 2;
      return { item, distance: Math.abs(y - centerY) };
    })
    .sort((a, b) => a.distance - b.distance)[0]?.item || null;
}

function updateTopicPointerDrag(event) {
  const drag = state.topicPointerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
  if (!drag.dragging && distance < 4) return;
  if (!drag.dragging) {
    drag.dragging = true;
    state.suppressTopicClick = true;
    drag.item.classList.add("dragging");
    createTopicDragGhost(drag);
  }
  event.preventDefault();
  moveTopicDragGhost(event.clientX, event.clientY);
  const targetItem = topicItemAtPoint(event.clientX, event.clientY, drag.fromVault);
  clearTopicDragOver();
  if (targetItem?.dataset.vault) {
    targetItem.classList.add("drag-over");
    drag.overVault = targetItem.dataset.vault;
  } else {
    drag.overVault = "";
  }
}

function finishTopicPointerDrag(event) {
  const drag = state.topicPointerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  document.removeEventListener("pointermove", updateTopicPointerDrag);
  document.removeEventListener("pointerup", finishTopicPointerDrag);
  document.removeEventListener("pointercancel", finishTopicPointerDrag);
  clearTopicDragOver();
  drag.item.classList.remove("dragging");
  removeTopicDragGhost();
  state.topicPointerDrag = null;
  if (!drag.dragging) return;
  state.suppressTopicClick = true;
  const targetItem = topicItemAtPoint(event.clientX, event.clientY, drag.fromVault);
  const toVault = drag.overVault || targetItem?.dataset.vault || "";
  if (toVault) reorderTopics(drag.fromVault, toVault, drag.status);
  setTimeout(() => {
    state.suppressTopicClick = false;
  }, 0);
}

function createTopicDragGhost(drag) {
  removeTopicDragGhost();
  const rect = drag.item.getBoundingClientRect();
  const ghost = drag.item.cloneNode(true);
  ghost.classList.add("topic-drag-ghost");
  ghost.style.width = `${rect.width}px`;
  document.body.append(ghost);
  state.topicDragGhost = ghost;
  moveTopicDragGhost(drag.startX, drag.startY);
}

function moveTopicDragGhost(x, y) {
  if (!state.topicDragGhost) return;
  state.topicDragGhost.style.transform = `translate(${x + 10}px, ${y + 10}px)`;
}

function removeTopicDragGhost() {
  if (!state.topicDragGhost) return;
  state.topicDragGhost.remove();
  state.topicDragGhost = null;
}

function addTopicPointerDragHandlers(item, topic, status) {
  item.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || state.topicRenameDialog || event.target.closest("input, button")) return;
    state.topicPointerDrag = {
      pointerId: event.pointerId,
      fromVault: topic.vault,
      startX: event.clientX,
      startY: event.clientY,
      overVault: "",
      item,
      status,
      dragging: false
    };
    document.addEventListener("pointermove", updateTopicPointerDrag);
    document.addEventListener("pointerup", finishTopicPointerDrag);
    document.addEventListener("pointercancel", finishTopicPointerDrag);
    event.preventDefault();
  });
}

function startTopicRename(topic, item) {
  openTopicRenameDialog(topic);
}

function closeTopicContextMenu() {
  if (!state.topicContextMenu) return;
  state.topicContextMenu.remove();
  state.topicContextMenu = null;
}

function showTopicContextMenu(event, topic, item) {
  event.preventDefault();
  closeTopicContextMenu();
  const menu = document.createElement("div");
  menu.className = "topic-context-menu";
  menu.innerHTML = `
    <button type="button" data-action="rename">Rename</button>
    <button type="button" data-action="remove">Remove from App</button>
  `;
  document.body.append(menu);
  const left = Math.min(event.clientX, window.innerWidth - 190);
  const top = Math.min(event.clientY, window.innerHeight - 86);
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
  state.topicContextMenu = menu;
  menu.addEventListener("pointerdown", (clickEvent) => {
    clickEvent.preventDefault();
    clickEvent.stopPropagation();
    const action = clickEvent.target.closest("button")?.dataset.action;
    if (!action) return;
    closeTopicContextMenu();
    if (action === "rename") {
      startTopicRename(topic, item);
      return;
    }
    if (action === "remove") removeTopicFromApp(topic).catch(showError);
  });
  setTimeout(() => {
    document.addEventListener("pointerdown", closeTopicContextMenu, { once: true });
  }, 0);
}

function closeTopicRenameDialog() {
  if (!state.topicRenameDialog) return;
  state.topicRenameDialog.remove();
  state.topicRenameDialog = null;
}

function closeConfirmDialog() {
  if (!state.confirmDialog) return;
  state.confirmDialog.remove();
  state.confirmDialog = null;
}

function openConfirmDialog({ title, message, confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false } = {}) {
  closeConfirmDialog();
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "topic-rename-overlay";

    const dialog = document.createElement("div");
    dialog.className = "topic-rename-dialog confirm-dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", title || "Confirm action");

    const titleEl = document.createElement("div");
    titleEl.className = "topic-rename-title";
    titleEl.textContent = title || "Confirm Action";

    const messageEl = document.createElement("div");
    messageEl.className = "confirm-dialog-text";
    messageEl.textContent = message || "Continue?";

    const actions = document.createElement("div");
    actions.className = "topic-rename-actions";

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = cancelLabel;

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.dataset.action = "confirm";
    confirmButton.textContent = confirmLabel;
    if (danger) confirmButton.classList.add("danger-action");

    actions.append(cancelButton, confirmButton);
    dialog.append(titleEl, messageEl, actions);
    overlay.append(dialog);
    document.body.append(overlay);
    state.confirmDialog = overlay;

    let finished = false;
    const finish = (value) => {
      if (finished) return;
      finished = true;
      closeConfirmDialog();
      resolve(value);
    };

    overlay.addEventListener("pointerdown", (event) => {
      if (event.target === overlay) finish(false);
    });
    cancelButton.addEventListener("click", () => finish(false));
    confirmButton.addEventListener("click", () => finish(true));
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      }
    });
    requestAnimationFrame(() => {
      confirmButton.focus();
    });
  });
}

function openTopicRenameDialog(topic) {
  if (!topic?.vault) return;
  closeTopicRenameDialog();
  const overlay = document.createElement("div");
  overlay.className = "topic-rename-overlay";
  overlay.innerHTML = `
    <div class="topic-rename-dialog" role="dialog" aria-modal="true" aria-label="Rename topic">
      <div class="topic-rename-title">Rename Topic</div>
      <input class="topic-rename-dialog-input" type="text" value="${escapeHtml(topic.topic || "")}" aria-label="Topic name" />
      <div class="topic-rename-actions">
        <button type="button" data-action="cancel">Cancel</button>
        <button type="button" data-action="save">Save</button>
      </div>
    </div>
  `;
  document.body.append(overlay);
  state.topicRenameDialog = overlay;
  const input = overlay.querySelector(".topic-rename-dialog-input");
  const saveButton = overlay.querySelector('[data-action="save"]');
  const cancelButton = overlay.querySelector('[data-action="cancel"]');
  let finished = false;

  const cancel = () => {
    if (finished) return;
    finished = true;
    closeTopicRenameDialog();
  };
  const save = async () => {
    if (finished) return;
    const nextTopic = input.value.trim();
    if (!nextTopic || nextTopic === topic.topic) {
      cancel();
      return;
    }
    finished = true;
    input.disabled = true;
    saveButton.disabled = true;
    cancelButton.disabled = true;
    try {
      await api("/api/topics/rename", {
        method: "POST",
        body: JSON.stringify({ vault: topic.vault, topic: nextTopic })
      });
      closeTopicRenameDialog();
      await refreshStatus();
      appendLog("meta", `Renamed topic: ${topic.topic} → ${nextTopic}`);
    } catch (error) {
      finished = false;
      input.disabled = false;
      saveButton.disabled = false;
      cancelButton.disabled = false;
      showError(error);
      input.focus();
    }
  };

  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === overlay) cancel();
  });
  cancelButton.addEventListener("click", cancel);
  saveButton.addEventListener("click", save);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      save();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  });
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

async function removeTopicFromApp(topic) {
  if (!topic?.vault) return;
  const confirmed = await openConfirmDialog({
    title: "Remove Topic",
    message: `Remove "${topic.topic}" from Deep Survey?\n\nThis only removes it from the app topic list. The original vault folder and files will not be deleted.`,
    confirmLabel: "Remove",
    danger: true
  });
  if (!confirmed) return;
  await api("/api/topics/remove", {
    method: "POST",
    body: JSON.stringify({ vault: topic.vault })
  });
  forgetThreadBinding(topic);
  state.selectedVault = null;
  persistSelectedVaultToServer("");
  state.isCreatingTopic = false;
  await refreshStatus();
  appendLog("meta", `Removed topic from app only: ${topic.topic}`);
}

async function selectTopic(vault) {
  state.selectedVault = vault;
  persistSelectedVaultToServer(vault);
  state.isCreatingTopic = false;
  vaultFiles = [];
  selectedVaultFile = null;
  collapsedFolders.clear();
  await refreshStatus();
  if (els.vaultTab.classList.contains("active")) loadVaultFiles().catch(showError);
}

function newTopicSelection() {
  return {
    topic: "New Topic",
    active: false,
    manualPdfCount: 0,
    nextStage: "stage_1_discovery",
    stages: [
      { id: "stage_1_discovery", label: "Stage 1 Discovery", status: "pending" },
      { id: "stage_2_screening", label: "Stage 2 Screening", status: "pending" },
      { id: "stage_3_pdf_acquisition", label: "Stage 3 PDF Acquisition", status: "pending" },
      { id: "stage_4_paper_deep_reading", label: "Stage 4 Deep Reading", status: "pending" },
      { id: "stage_5a_concept_notes", label: "Stage 5A Concepts", status: "pending" },
      { id: "stage_5b_review_synthesis", label: "Stage 5B Review", status: "pending" }
    ],
    artifactPaths: {}
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setActiveTab(tab) {
  const isVault = tab === "vault";
  els.runTabBtn.classList.toggle("active", !isVault);
  els.vaultTabBtn.classList.toggle("active", isVault);
  els.runTab.classList.toggle("active", !isVault);
  els.vaultTab.classList.toggle("active", isVault);
  if (isVault) loadVaultFiles().catch(showError);
}

async function loadVaultFiles() {
  const vault = state.isCreatingTopic ? null : state.status?.selectedTopic?.vault;
  if (!vault) {
    vaultFiles = [];
    renderVaultFiles();
    els.vaultPreview.textContent = "Select an existing topic.";
    return;
  }
  const data = await api(`/api/vault/files?vault=${encodeURIComponent(vault)}`);
  vaultFiles = data.files || [];
  renderVaultFiles();
  if (!selectedVaultFile && vaultFiles[0]) {
    await loadVaultFile(vaultFiles[0]);
  }
}

function renderVaultFiles() {
  const query = els.vaultSearch.value.trim().toLowerCase();
  const files = vaultFiles.filter((file) => file.toLowerCase().includes(query));
  visibleVaultFiles = [];
  if (!files.length) {
    const empty = document.createElement("div");
    empty.className = "topic-meta";
    empty.textContent = "No Markdown files";
    els.vaultFiles.replaceChildren(empty);
    return;
  }
  const nodes = [];
  let currentFolder = null;
  for (const file of files) {
    const parts = file.split("/");
    const folder = parts.length > 1 ? parts.slice(0, -1).join("/") : "";
    const name = parts.at(-1);
    if (folder !== currentFolder) {
      currentFolder = folder;
      if (folder) {
        const folderNode = document.createElement("button");
        folderNode.type = "button";
        folderNode.className = "vault-folder";
        folderNode.textContent = `${collapsedFolders.has(folder) ? "▸" : "▾"} ${folder}`;
        folderNode.addEventListener("click", () => {
          if (collapsedFolders.has(folder)) {
            collapsedFolders.delete(folder);
          } else {
            collapsedFolders.add(folder);
          }
          renderVaultFiles();
        });
        nodes.push(folderNode);
      }
    }
    if (folder && collapsedFolders.has(folder)) continue;
    visibleVaultFiles.push(file);
    const button = document.createElement("button");
    button.type = "button";
    button.className = [
      "vault-file",
      file === selectedVaultFile ? "selected" : "",
      folder ? "nested-file" : "root-file"
    ].join(" ");
    button.textContent = folder ? name : file;
    button.title = file;
    button.addEventListener("click", () => loadVaultFile(file).catch(showError));
    nodes.push(button);
  }
  els.vaultFiles.replaceChildren(...nodes);
}

function moveVaultSelection(delta) {
  if (!visibleVaultFiles.length) return;
  const currentIndex = Math.max(0, visibleVaultFiles.indexOf(selectedVaultFile));
  const nextIndex = Math.min(visibleVaultFiles.length - 1, Math.max(0, currentIndex + delta));
  const nextFile = visibleVaultFiles[nextIndex];
  if (nextFile) loadVaultFile(nextFile, { reveal: true }).catch(showError);
}

function scrollSelectedVaultFileIntoView() {
  const selected = els.vaultFiles.querySelector(".vault-file.selected");
  if (!selected) return;
  selected.scrollIntoView({ block: "nearest" });
}

function handleVaultFileKeydown(event) {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveVaultSelection(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    moveVaultSelection(-1);
  } else if (event.key === "Enter" && selectedVaultFile) {
    event.preventDefault();
    loadVaultFile(selectedVaultFile).catch(showError);
  }
}

async function loadVaultFile(file, options = {}) {
  const vault = state.status?.selectedTopic?.vault;
  if (!vault) return;
  selectedVaultFile = file;
  renderVaultFiles();
  if (options.reveal) scrollSelectedVaultFileIntoView();
  els.vaultPreview.textContent = "Loading...";
  const data = await api(
    `/api/vault/file?vault=${encodeURIComponent(vault)}&path=${encodeURIComponent(file)}`
  );
  els.vaultPreview.innerHTML = renderMarkdown(data.content);
}

function normalizeVaultLink(href, currentFile = selectedVaultFile) {
  const clean = decodeURIComponent(String(href || "").split("#")[0]).trim();
  if (!clean) return "";
  if (clean.startsWith("/")) return clean.replace(/^\/+/, "");
  const baseParts = currentFile?.includes("/") ? currentFile.split("/").slice(0, -1) : [];
  for (const part of clean.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") baseParts.pop();
    else baseParts.push(part);
  }
  return baseParts.join("/");
}

function markdownLinkTargetExists(href) {
  const normalized = normalizeVaultLink(href);
  if (!normalized) return "";
  const candidates = [normalized, normalized.endsWith(".md") ? normalized : `${normalized}.md`];
  const exact = candidates.find((candidate) => vaultFiles.includes(candidate));
  if (exact) return exact;
  if (!normalized.includes("/")) {
    const basename = normalized.endsWith(".md") ? normalized : `${normalized}.md`;
    return vaultFiles.find((file) => file.split("/").at(-1) === basename) || "";
  }
  return "";
}

async function openMarkdownLink(href) {
  const target = String(href || "").trim();
  if (!target) return;
  if (/^(https?:|mailto:)/i.test(target)) {
    await api("/api/open-url", {
      method: "POST",
      body: JSON.stringify({ url: target })
    });
    appendLog("meta", `Opened link: ${target}`);
    return;
  }
  const vaultTarget = markdownLinkTargetExists(target);
  if (vaultTarget) {
    await loadVaultFile(vaultTarget, { reveal: true });
    return;
  }
  const vault = state.status?.selectedTopic?.vault;
  const vaultPath = normalizeVaultLink(target);
  if (vault && vaultPath) {
    try {
      await api("/api/vault/open-path", {
        method: "POST",
        body: JSON.stringify({ vault, path: vaultPath })
      });
      appendLog("meta", `Opened output file link: ${vaultPath}`);
      return;
    } catch {
      // Fall through to the visible not-found message below.
    }
  }
  appendLog("meta", `Link target not found in output files: ${target}`);
}

function renderMarkdown(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let inCode = false;
  let inMathBlock = false;
  let codeLines = [];
  let mathLines = [];
  let listType = null;
  let tableRows = [];

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };
  const closeTable = () => {
    if (!tableRows.length) return;
    html.push(renderTable(tableRows));
    tableRows = [];
  };

  for (const line of lines) {
    if (line.trim() === "$$") {
      if (inMathBlock) {
        html.push(renderLatex(mathLines.join("\n"), true));
        mathLines = [];
        inMathBlock = false;
      } else {
        closeList();
        closeTable();
        inMathBlock = true;
      }
      continue;
    }
    if (inMathBlock) {
      mathLines.push(line);
      continue;
    }

    if (line.startsWith("```")) {
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        closeList();
        closeTable();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (isTableLine(line)) {
      closeList();
      tableRows.push(line);
      continue;
    }
    closeTable();

    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      closeList();
      html.push(`<blockquote>${inlineMarkdown(trimmed.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        html.push("<ul>");
      }
      html.push(`<li>${inlineMarkdown(unordered[1])}</li>`);
      continue;
    }

    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        html.push("<ol>");
      }
      html.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
      continue;
    }

    closeList();
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  }
  closeList();
  closeTable();
  if (inCode) html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  if (inMathBlock) html.push(renderLatex(mathLines.join("\n"), true));
  return html.join("\n");
}

function inlineMarkdown(text) {
  const mathTokens = [];
  const protectedText = text.replace(/\$([^$\n]+)\$/g, (_, formula) => {
    const token = `@@MATH${mathTokens.length}@@`;
    mathTokens.push(renderLatex(formula, false));
    return token;
  });
  let html = escapeHtml(protectedText)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[\[([^\]]+)\]\]/g, (_, target) => {
      const href = target.split("|")[0].trim();
      const label = target.includes("|") ? target.split("|").slice(1).join("|").trim() : target.trim();
      return `<a class="md-link" href="${escapeHtml(href)}" data-md-href="${escapeHtml(href)}">[[${escapeHtml(label)}]]</a>`;
    })
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
      const cleanHref = href.trim();
      return `<a class="md-link" href="${escapeHtml(cleanHref)}" data-md-href="${escapeHtml(cleanHref)}">${label}</a>`;
    })
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (_, prefix, url) => {
      return `${prefix}<a class="md-link" href="${escapeHtml(url)}" data-md-href="${escapeHtml(url)}">${escapeHtml(url)}</a>`;
    });
  mathTokens.forEach((value, index) => {
    html = html.replace(`@@MATH${index}@@`, value);
  });
  return html;
}

function renderLatex(formula, displayMode) {
  if (window.katex) {
    try {
      return window.katex.renderToString(formula, {
        displayMode,
        throwOnError: false,
        strict: false,
        trust: false
      });
    } catch {
      // Fall through to the safe plain-text rendering below.
    }
  }
  const escaped = escapeHtml(formula);
  return displayMode
    ? `<div class="math-block">${escaped}</div>`
    : `<span class="math-inline">$${escaped}$</span>`;
}

function isTableLine(line) {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.includes("|");
}

function renderTable(rows) {
  const cleaned = rows.filter((row) => !/^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|$/.test(row.trim()));
  if (!cleaned.length) return "";
  const tableRows = cleaned.map((row, index) => {
    const cells = row
      .trim()
      .slice(1, -1)
      .split("|")
      .map((cell) => inlineMarkdown(cell.trim()));
    const tag = index === 0 ? "th" : "td";
    return `<tr>${cells.map((cell) => `<${tag}>${cell}</${tag}>`).join("")}</tr>`;
  });
  return `<table>${tableRows.join("")}</table>`;
}

function labelStage(stage) {
  const found = state.status?.stages?.find((item) => item.id === stage);
  const selectedFound = state.status?.selectedTopic?.stages?.find((item) => item.id === stage);
  return selectedFound?.label || found?.label || stage || "unknown";
}

function selectedThreadMode() {
  return els.threadModeSelect?.value || document.querySelector('input[name="threadMode"]:checked')?.value || "write";
}

function selectedThreadModel() {
  return els.threadModelSelect.value || "gpt-5.5";
}

function selectedReasoningEffort() {
  return els.threadEffortSelect?.value || document.querySelector('input[name="reasoningEffort"]:checked')?.value || "medium";
}

function selectedThreadId() {
  return els.threadSelect.value || "";
}

function topicOwnsThread(topicInfo, threadId) {
  if (!topicInfo?.topic || !threadId) return false;
  const bound = boundThreadIdForTopic(topicInfo);
  if (bound && bound === threadId) return true;
  return threadLooksLikeDlwWorkThread(threadId, topicInfo);
}

function selectedTopicOwnsThread(threadId) {
  return topicOwnsThread(state.status?.selectedTopic, threadId);
}

function pendingApprovalForThread(threadId = selectedThreadId()) {
  if (!threadId || !selectedTopicOwnsThread(threadId)) return null;
  const exact = state.pendingApprovals.find((approval) => approval.threadId && approval.threadId === threadId);
  if (exact) return exact;
  const status = state.appThreadStatus[threadId];
  if (!status?.turnId) return null;
  return state.pendingApprovals.find((approval) => !approval.threadId && approval.turnId === status.turnId) || null;
}

function upsertPendingApproval(approval) {
  if (!approval?.requestId) return;
  const index = state.pendingApprovals.findIndex((item) => item.requestId === approval.requestId);
  if (index >= 0) state.pendingApprovals[index] = approval;
  else state.pendingApprovals.push(approval);
}

function removePendingApproval(requestId) {
  state.pendingApprovals = state.pendingApprovals.filter((approval) => approval.requestId !== requestId);
}

function clearPendingApprovalsForThread(threadId, turnId = null) {
  if (!threadId && !turnId) return;
  state.pendingApprovals = state.pendingApprovals.filter((approval) => {
    if (turnId && approval.turnId === turnId) return false;
    if (threadId && approval.threadId === threadId) return false;
    return true;
  });
}

function setApprovalButtonsDisabled(disabled) {
  els.approvalApproveBtn.disabled = disabled;
  els.approvalDenyBtn.disabled = disabled;
  els.approvalCancelBtn.disabled = disabled;
}

function renderApprovalPanel() {
  const threadId = selectedThreadId();
  const approval = pendingApprovalForThread();
  if (!approval) {
    const status = state.appThreadStatus[threadId];
    if (status?.status === "waiting_approval" && selectedTopicOwnsThread(threadId)) {
      els.approvalPanel.classList.remove("hidden");
      els.approvalPanel.dataset.requestId = "";
      els.approvalMeta.textContent = status.turnId ? `turn ${status.turnId.slice(0, 8)} · requestId not captured` : "requestId not captured";
      els.approvalCommand.textContent =
        "The current thread is waiting for approval, but app-server did not return an actionable approval request. Refresh the state; if it is still stuck, stop it and send again.";
      setApprovalButtonsDisabled(true);
      return;
    }
    els.approvalPanel.classList.add("hidden");
    els.approvalPanel.dataset.requestId = "";
    setApprovalButtonsDisabled(false);
    return;
  }
  els.approvalPanel.classList.remove("hidden");
  els.approvalPanel.dataset.requestId = approval.requestId;
  setApprovalButtonsDisabled(false);
  const turnText = approval.turnId ? `turn ${approval.turnId.slice(0, 8)}` : "current turn";
  const typeText = approval.method?.includes("fileChange") ? "File Change" : "Command Execution";
  els.approvalMeta.textContent = `${typeText} · ${turnText}`;
  els.approvalCommand.textContent =
    approval.command ||
    approval.reason ||
    approval.summary ||
    JSON.stringify(approval.params || {}, null, 2);
}

function mergeAppThreadStatus(threadId, patch) {
  if (!threadId) return;
  state.appThreadStatus[threadId] = {
    threadId,
    status: "idle",
    summary: "Idle",
    turnId: null,
    ...(state.appThreadStatus[threadId] || {}),
    ...patch
  };
  if (!isActiveAppThreadStatus(state.appThreadStatus[threadId])) {
    delete state.appThreadRunningStages[threadId];
    if (state.activeDlwThreadId === threadId) state.activeDlwThreadId = null;
    if (!state.currentRunId) state.localRunningStage = null;
    delete state.appThreadStatus[threadId].dlwAction;
    delete state.appThreadStatus[threadId].runningStage;
  }
  renderThreadStatus();
  if (state.status) renderStatus(state.status);
}

function chatForThread(threadId) {
  if (!threadId) return [];
  if (!state.appThreadChats[threadId]) state.appThreadChats[threadId] = [];
  return state.appThreadChats[threadId];
}

function bufferKey(threadId, turnId) {
  return `${threadId || "unknown"}:${turnId || "pending"}`;
}

function renderThreadChat() {
  const threadId = selectedThreadId();
  const messages = chatForThread(threadId);
  const previousScrollTop = els.threadChat.scrollTop;
  const wasAtBottom = els.threadChat.scrollHeight - els.threadChat.scrollTop - els.threadChat.clientHeight < 24;
  const hasPendingAssistant = Object.entries(state.appThreadAssistantBuffers).some(
    ([key, value]) => key.startsWith(`${threadId}:`) && value.text.trim()
  );
  if (!threadId) {
    els.threadChat.replaceChildren(emptyChatNode("Select or create a thread."));
    els.threadChatState.textContent = "Idle";
    return;
  }
  const nodes = messages.map(renderChatMessage);
  if (hasPendingAssistant) nodes.push(renderChatMessage({ role: "assistant", text: "Codex is replying...", pending: true }));
  if (!nodes.length) nodes.push(emptyChatNode("Send a message and the full reply will appear here."));
  els.threadChat.replaceChildren(...nodes);
  els.threadChat.scrollTop = wasAtBottom ? els.threadChat.scrollHeight : previousScrollTop;
  const status = state.appThreadStatus[threadId];
  els.threadChatState.textContent = status?.status === "running" ? "Codex is replying..." : threadStatusLabel(status);
}

function emptyChatNode(text) {
  const node = document.createElement("div");
  node.className = "chat-empty";
  node.textContent = text;
  return node;
}

function setupStatusLabel(ok, pending = false) {
  if (pending) return "checking";
  return ok ? "ready" : "needs attention";
}

function setupCheckNode(label, ok, detail = "") {
  const node = document.createElement("div");
  node.className = `setup-check ${ok ? "ok" : "warn"}`;
  const dot = document.createElement("span");
  dot.className = "setup-dot";
  const text = document.createElement("span");
  text.textContent = label;
  const meta = document.createElement("span");
  meta.className = "setup-check-meta";
  meta.textContent = detail || setupStatusLabel(ok);
  node.append(dot, text, meta);
  return node;
}

function renderSetupPanel(setup = state.setupStatus) {
  if (!els.setupPanel) return;
  els.setupPanel.classList.add("hidden");
  renderCodexPill();
  if (!setup) {
    els.setupPanel.classList.remove("ready", "warn");
    els.setupTitle.textContent = "Checking Codex Setup";
    els.setupText.textContent = "On startup, Deep Survey connects to Codex and installs the bundled Deep Literature Workflow plugin if needed.";
    els.setupChecks.replaceChildren(
      setupCheckNode("Codex app", false, "checking"),
      setupCheckNode("Workspace plugin", false, "checking"),
      setupCheckNode("Codex plugin cache", false, "checking"),
      setupCheckNode("DLW skill visible to Codex", false, "checking")
    );
    els.setupInstallBtn.classList.add("hidden");
    return;
  }
  const codexOk = Boolean(setup.codex?.ok);
  const workspaceOk = Boolean(setup.workspacePlugin?.ok);
  const cacheOk = Boolean(setup.codexPlugin?.ok);
  const skillOk = Boolean(setup.skills?.deepLiterature);
  const allOk = Boolean(setup.ok);
  els.setupPanel.classList.toggle("ready", allOk);
  els.setupPanel.classList.toggle("warn", !allOk);
  els.setupTitle.textContent = allOk ? "Codex Setup Ready" : "Codex Setup Needs Attention";
  els.setupText.textContent = allOk
    ? "Codex is connected and Deep Literature Workflow is available for structured plugin calls."
    : "Deep Survey will keep trying to prepare Codex. If a check stays unresolved, use Repair Setup, then reopen the app.";
  els.setupChecks.replaceChildren(
    setupCheckNode("Codex app", codexOk, setup.codex?.version || setup.codex?.error || setup.codex?.path || ""),
    setupCheckNode("Workspace plugin", workspaceOk, workspaceOk ? "installed" : "missing"),
    setupCheckNode("Codex plugin cache", cacheOk, cacheOk ? "installed" : "missing"),
    setupCheckNode("DLW skill visible to Codex", skillOk, skillOk ? "available" : setup.skills?.error || "not visible yet")
  );
  els.setupInstallBtn.classList.toggle("hidden", allOk);
  renderCodexPill();
}

async function runSetupCheck({ install = false } = {}) {
  if (!els.setupPanel) return null;
  els.setupRetryBtn.disabled = true;
  els.setupInstallBtn.disabled = true;
  if (!state.setupStatus) renderSetupPanel(null);
  try {
    const setup = await api(`/api/setup?install=${install ? "1" : "0"}`);
    state.setupStatus = setup;
    renderSetupPanel(setup);
    if (setup.installation?.workspace?.installed || setup.installation?.cache?.installed) {
      appendLog("meta", "Deep Survey installed the bundled DLW plugin template for this local Codex setup.");
    }
    return setup;
  } finally {
    els.setupRetryBtn.disabled = false;
    els.setupInstallBtn.disabled = false;
  }
}

function renderChatMessage(message) {
  const item = document.createElement("div");
  item.className = `chat-message ${message.role}${message.pending ? " pending" : ""}`;
  const body = document.createElement("div");
  body.className = "chat-body";
  body.textContent = message.text;
  item.append(body);
  return item;
}

function appendThreadChatMessage(threadId, role, text, options = {}) {
  const trimmed = String(text || "").trim();
  if (!threadId || !trimmed) return;
  const messages = chatForThread(threadId);
  const duplicate = messages.some((message) => {
    if (message.role !== role || message.text !== trimmed) return false;
    if (options.turnId && message.turnId && message.turnId !== options.turnId) return false;
    return true;
  });
  if (duplicate) {
    renderThreadChat();
    return;
  }
  messages.push({
    role,
    text: trimmed,
    at: new Date().toISOString(),
    ...options
  });
  renderThreadChat();
}

function applyAppServerChatEvent(data) {
  const method = data.method;
  const threadId = threadIdFromAppServerEvent(data);
  const turnId = turnIdFromAppServerEvent(data);
  if (!threadId) return;
  if (method === "turn/start/local" || method === "dlwAction/start") {
    if (data.userMessage) appendThreadChatMessage(threadId, "user", data.userMessage, { turnId });
    renderThreadChat();
    return;
  }
  if (method === "item/agentMessage/delta") {
    const delta = data.params?.delta || "";
    if (!delta) return;
    const key = bufferKey(threadId, turnId);
    const previous = state.appThreadAssistantBuffers[key] || { threadId, turnId, text: "", at: new Date().toISOString() };
    state.appThreadAssistantBuffers[key] = { ...previous, text: `${previous.text}${delta}` };
    renderThreadChat();
    return;
  }
  if (method === "item/completed") {
    const type = data.params?.item?.type || data.params?.item?.kind || "";
    if (type !== "agentMessage") return;
    flushAssistantBuffer(threadId, turnId);
    return;
  }
  if (method === "turn/completed") {
    flushAssistantBuffer(threadId, turnId);
    renderThreadChat();
  }
}

function flushAssistantBuffer(threadId, turnId) {
  const exactKey = bufferKey(threadId, turnId);
  const keys = state.appThreadAssistantBuffers[exactKey]
    ? [exactKey]
    : Object.keys(state.appThreadAssistantBuffers).filter((key) => key.startsWith(`${threadId}:`));
  for (const key of keys) {
    const buffer = state.appThreadAssistantBuffers[key];
    if (buffer?.text?.trim()) {
      chatForThread(threadId).push({
        role: "assistant",
        text: buffer.text.trim(),
        at: new Date().toISOString(),
        turnId: buffer.turnId || turnId || null
      });
    }
    delete state.appThreadAssistantBuffers[key];
  }
  renderThreadChat();
}

function threadIdForTurn(turnId) {
  if (!turnId) return "";
  return Object.entries(state.appThreadStatus).find(([, status]) => status.turnId === turnId)?.[0] || "";
}

function threadIdFromAppServerEvent(data) {
  const params = data.params || {};
  const turnId = data.turnId || params.turnId || params.turn?.id || params.item?.turnId || "";
  return (
    data.threadId ||
    params.threadId ||
    params.thread?.id ||
    params.turn?.threadId ||
    params.item?.threadId ||
    threadIdForTurn(turnId) ||
    ""
  );
}

function turnIdFromAppServerEvent(data) {
  const params = data.params || {};
  return data.turnId || params.turnId || params.turn?.id || params.item?.turnId || null;
}

function applyAppServerEventStatus(data) {
  const method = data.method;
  if (data.approval) {
    upsertPendingApproval(data.approval);
  }
  if (method === "serverRequest/resolved/local" && data.requestId) {
    removePendingApproval(data.requestId);
  }
  const threadId = threadIdFromAppServerEvent(data);
  const turnId = turnIdFromAppServerEvent(data);
  const threadStatus = data.params?.thread?.status || data.params?.status || data.status?.threadStatus;
  const activeFlags = threadStatus?.activeFlags || data.status?.threadStatus?.activeFlags || [];
  if (method === "dlwAction/start" && data.action) {
    const runningStage = inferRunningStageForAction(data.action);
    state.activeDlwThreadId = threadId;
    state.localRunningStage = runningStage;
    if (runningStage) state.appThreadRunningStages[threadId] = runningStage;
  }
  if (String(method || "").includes("requestApproval")) {
    mergeAppThreadStatus(threadId, {
      status: "waiting_approval",
      turnId,
      summary: data.summary || "Waiting for approval",
      pendingApprovalRequestId: data.requestId || data.approval?.requestId || null
    });
  } else if (method === "turn/start/local" || method === "turn/started") {
    mergeAppThreadStatus(threadId, {
      status: "running",
      turnId,
      summary: `Running${turnId ? ` · ${turnId.slice(0, 8)}` : ""}`
    });
  } else if (method === "turn/completed") {
    clearPendingApprovalsForThread(threadId, turnId);
    mergeAppThreadStatus(threadId, {
      status: data.params?.turn?.status?.type || "completed",
      turnId,
      summary: `Completed${turnId ? ` · ${turnId.slice(0, 8)}` : ""}`
    });
    scheduleStatusRefresh();
  } else if (method === "turn/interrupt/local") {
    clearPendingApprovalsForThread(threadId, turnId);
    mergeAppThreadStatus(threadId, {
      status: "interrupted",
      turnId,
      summary: `Interrupted${turnId ? ` · ${turnId.slice(0, 8)}` : ""}`
    });
    scheduleStatusRefresh();
  } else if (method === "exit") {
    mergeAppThreadStatus(selectedThreadId(), {
      status: "disconnected",
      summary: "app-server disconnected"
    });
  } else if (activeFlags.includes("waitingOnApproval")) {
    mergeAppThreadStatus(threadId, {
      status: "waiting_approval",
      turnId,
      summary: "Waiting for approval",
      threadStatus
    });
  } else if (method === "thread/status/changed" && threadStatus?.type) {
    const status = threadStatus.type === "active" ? "running" : threadStatus.type;
    if (!activeFlags.includes("waitingOnApproval") && ["idle", "completed", "interrupted", "failed"].includes(status)) {
      clearPendingApprovalsForThread(threadId, turnId);
    }
    mergeAppThreadStatus(threadId, {
      status,
      turnId,
      summary: `Thread ${status}`,
      threadStatus
    });
    if (["idle", "completed", "interrupted", "failed"].includes(status)) scheduleStatusRefresh();
  } else if (data.status?.threadId) {
    if (!data.status.threadStatus?.activeFlags?.includes("waitingOnApproval") && ["idle", "completed", "interrupted", "failed"].includes(data.status.status)) {
      clearPendingApprovalsForThread(data.status.threadId, data.status.turnId);
    }
    mergeAppThreadStatus(data.status.threadId, data.status);
    if (["idle", "completed", "interrupted", "failed"].includes(data.status.status)) scheduleStatusRefresh();
  }
}

function threadStatusLabel(status) {
  const value = status?.status || "idle";
  const labels = {
    idle: "Idle",
    running: "Running",
    stopping: "Stopping",
    interrupted: "Stopped",
    completed: "Completed",
    failed: "Failed",
    disconnected: "Disconnected",
    interrupt_failed: "Stop Failed",
    waiting_approval: "Waiting For Approval"
  };
  return labels[value] || value;
}

function renderThreadStatus() {
  const threadId = selectedThreadId();
  const status = state.appThreadStatus[threadId];
  const thread = state.appThreads.find((item) => item.id === threadId);
  const name = thread?.name || thread?.preview || (threadId ? threadId.slice(0, 8) : "None selected");
  const statusText = state.dlwStartupBusy && !threadId ? "Preparing" : status ? threadStatusLabel(status) : "Unknown";
  const turnText = status?.turnId ? ` · turn ${status.turnId.slice(0, 8)}` : "";
  const modeText = selectedThreadMode() === "write" ? "Allow Edits" : "Read Only";
  els.threadStatusText.textContent = `Thread: ${name} · ${statusText}${turnText} · ${modeText}`;
  const canStop = composerCanStopThread(threadId, status);
  const busyWithoutComposerStop = Boolean(selectedThreadIsBusy() && !canStop);
  els.stopThreadBtn.disabled = true;
  els.stopThreadBtn.classList.add("hidden");
  els.sendThreadBtn.disabled = busyWithoutComposerStop;
  els.sendThreadBtn.classList.toggle("running", Boolean(canStop));
  els.sendThreadBtn.textContent = canStop ? "■" : "↑";
  els.sendThreadBtn.title = canStop ? "Stop" : busyWithoutComposerStop ? "Running" : "Send";
  els.sendThreadBtn.setAttribute("aria-label", canStop ? "Stop" : busyWithoutComposerStop ? "Running" : "Send");
  if (!state.currentRunId) {
    const threadToInterrupt = interruptibleThreadId();
    els.cancelBtn.disabled = !threadToInterrupt && !state.dlwStartupBusy;
  }
  renderApprovalPanel();
  renderThreadChat();
}

function connectAppServerEvents() {
  if (state.appServerEventSource) return;
  const source = new EventSource("/api/appserver/events");
  state.appServerEventSource = source;
  source.addEventListener("appserver", (event) => {
    const data = JSON.parse(event.data);
    applyAppServerEventStatus(data);
    applyAppServerChatEvent(data);
    const summary = String(data.summary || "").trim();
    if (!summary) return;
    if (data.method === "item/agentMessage/delta") return;
    const kind = data.method === "stderr" || data.method === "exit" ? "stderr" : "codex";
    appendLog(kind, `[app-server:${data.method}] ${summary}`);
  });
  source.onerror = () => {
    els.appServerState.textContent = "Disconnected";
    state.appServerEventSource = null;
    source.close();
  };
}

function renderThreadOptions(threads, selectedId) {
  const visibleThreads = selectedId
    ? threads.filter((thread) => thread.id === selectedId)
    : [];
  if (selectedId && !threads.some((thread) => thread.id === selectedId)) {
    const boundThread = { id: selectedId, sessionId: selectedId, name: `DLW bound thread ${selectedId.slice(0, 8)}` };
    state.appThreads = [boundThread, ...threads];
    visibleThreads.push(boundThread);
  }
  if (!visibleThreads.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No thread bound to this topic";
    els.threadSelect.replaceChildren(option);
    els.threadDisplay.textContent = "Chat: no thread bound to this topic";
    renderThreadStatus();
    return;
  }
  els.threadSelect.replaceChildren(
    ...visibleThreads.map((thread) => {
      const option = document.createElement("option");
      option.value = thread.id;
      option.textContent = `${thread.name || thread.preview || thread.id} · ${thread.id.slice(0, 8)}`;
      option.selected = selectedId ? thread.id === selectedId : false;
      return option;
    })
  );
  const selectedThread = visibleThreads.find((thread) => thread.id === selectedId) || visibleThreads[0];
  els.threadDisplay.textContent = `Chat: ${selectedThread.name || selectedThread.preview || selectedThread.id} · ${selectedThread.id.slice(0, 8)}`;
  renderThreadStatus();
}

function ensureThreadInList(threadId, label = "Bound DLW thread") {
  if (!threadId || state.appThreads.some((thread) => thread.id === threadId)) return;
  state.appThreads.unshift({
    id: threadId,
    sessionId: threadId,
    name: label,
    preview: null
  });
}

async function loadThreadMessages(threadId, { force = false } = {}) {
  if (!threadId || (!force && state.loadedThreadMessages[threadId])) {
    renderThreadChat();
    return;
  }
  const result = await api(`/api/appserver/threads/${encodeURIComponent(threadId)}/messages`);
  const messages = (result.messages || []).map((message) => ({
    role: message.role === "user" ? "user" : "assistant",
    text: String(message.text || ""),
    turnId: message.turnId || null,
    itemId: message.itemId || null,
    at: new Date().toISOString()
  })).filter((message) => message.text.trim());
  if (messages.length) state.appThreadChats[threadId] = messages;
  state.loadedThreadMessages[threadId] = true;
  renderThreadChat();
}

async function loadPendingApprovals() {
  const result = await api("/api/appserver/approvals");
  state.pendingApprovals = result.approvals || [];
  renderThreadStatus();
}

function preferredThreadId(threads, topicInfo = state.status?.selectedTopic) {
  const bound = boundThreadIdForTopic(topicInfo);
  if (bound && threadLooksLikeDlwWorkThread(bound, topicInfo)) return bound;
  if (bound) forgetThreadBinding(topicInfo);
  return matchingThreadIdByTopicName(threads, topicInfo) || null;
}

function matchingThreadIdForTopic(threads, topicInfo = state.status?.selectedTopic) {
  if (topicInfo?.vault) return "";
  return matchingThreadIdByTopicName(threads, topicInfo);
}

function matchingThreadIdByTopicName(threads, topicInfo = state.status?.selectedTopic, fallbackTopic = "") {
  const match = threads.find((thread) => threadLooksLikeDlwWorkThread(thread.id, topicInfo, fallbackTopic));
  return match?.id || null;
}

function threadLooksLikeDlwWorkThread(threadId, topicInfo = state.status?.selectedTopic, fallbackTopic = "") {
  if (!threadId) return false;
  const thread = state.appThreads.find((item) => item.id === threadId);
  if (!thread) return state.appThreads.length === 0;
  const text = `${thread.name || ""}\n${thread.preview || ""}`.toLowerCase();
  if (text.includes("probe") || text.includes("mention spike")) return false;
  const looksDlw = text.includes("dlw") || text.includes("deep literature workflow");
  if (!looksDlw) return false;
  const topic = (topicInfo?.topic || fallbackTopic || "").toLowerCase();
  const zhName = topic.split("/")[0]?.trim();
  const enName = topic.split("/")[1]?.trim();
  const vault = (topicInfo?.vault || "").toLowerCase();
  const vaultBase = vault.replace(/_obsidian_workflow$/i, "").replace(/_survay$/i, "").replace(/[-_]+/g, " ").trim();
  const candidates = [topic, zhName, enName, vault, vaultBase].filter(Boolean);
  if (!candidates.length) return true;
  return candidates.some((candidate) => text.includes(candidate));
}

async function listAppServerThreads(selectedId = null) {
  connectAppServerEvents();
  els.appServerState.textContent = "Listing...";
  const params = new URLSearchParams({ limit: "100" });
  if (state.status?.selectedTopic?.vault) params.set("vault", state.status.selectedTopic.vault);
  const result = await api(`/api/appserver/threads?${params}`);
  state.appThreads = result.threads || [];
  state.appThreadsLoaded = true;
  for (const thread of state.appThreads) {
    if (thread.appStatus) {
      const status = thread.appStatus.threadStatus?.activeFlags?.includes("waitingOnApproval")
        ? "waiting_approval"
        : thread.appStatus.status;
      if (["idle", "completed", "interrupted", "failed"].includes(status)) {
        clearPendingApprovalsForThread(thread.id, thread.appStatus.turnId);
      }
      state.appThreadStatus[thread.id] = {
        ...thread.appStatus,
        status
      };
    }
  }
  renderThreadOptions(state.appThreads, selectedId || preferredThreadId(state.appThreads));
  if (state.status) renderStatus(state.status);
  els.appServerState.textContent = `Connected · ${state.appThreads.length} threads`;
  appendLog("meta", `App-server listed ${state.appThreads.length} threads.`);
  loadPendingApprovals().catch(showError);
  loadThreadMessages(selectedThreadId()).catch(showError);
}

async function createBoundThreadForTopic({ mode, selectedTopic, topic }) {
  connectAppServerEvents();
  const topicInfo = selectedTopic || state.status?.selectedTopic || null;
  const topicName = topic || topicInfo?.topic;
  if (!topicName) throw new Error("Cannot create a DLW thread without a topic.");
  els.appServerState.textContent = "Creating...";
  appendLog("meta", `Creating Codex thread for ${topicName}...`);
  const result = await api("/api/appserver/threads", {
    method: "POST",
    body: JSON.stringify({
      name: `DLW: ${topicName}`,
      mode,
      model: selectedThreadModel(),
      selectedTopic: topicInfo
    })
  });
  const thread = result.thread;
  appendLog("meta", `Created bound DLW thread: ${thread?.name || thread?.id}`);
  state.appThreads = [thread, ...state.appThreads.filter((item) => item.id !== thread.id)];
  if (thread?.id) bindThreadToTopic(thread.id, topicInfo, topicName);
  if (thread?.id) mergeAppThreadStatus(thread.id, { status: "idle", summary: "Idle", turnId: null });
  renderThreadOptions(state.appThreads, thread?.id);
  els.appServerState.textContent = `Connected · ${state.appThreads.length} threads`;
  return thread;
}

function dlwActionRequiresWrite(action) {
  return ["start", "resume", "stage3", "importManual"].includes(action);
}

async function ensureAppServerThreadForDlw(mode, topicInfo, fallbackTopic, options = {}) {
  if (options.forceNew) {
    const thread = await createBoundThreadForTopic({ mode, selectedTopic: topicInfo, topic: fallbackTopic });
    const threadId = thread?.id || selectedThreadId();
    if (!threadId) throw new Error("Failed to create app-server thread.");
    return threadId;
  }

  let threadId = boundThreadIdForTopic(topicInfo, fallbackTopic);
  if (threadId) {
    if (!threadLooksLikeDlwWorkThread(threadId, topicInfo, fallbackTopic)) {
      forgetThreadBinding(topicInfo, fallbackTopic);
      threadId = "";
    } else {
      ensureThreadInList(threadId, `DLW: ${topicInfo?.topic || fallbackTopic || threadId}`);
      renderThreadOptions(state.appThreads, threadId);
      return threadId;
    }
  }

  if (!state.appThreads.length) {
    await listAppServerThreads();
  }

  threadId = matchingThreadIdByTopicName(state.appThreads, topicInfo, fallbackTopic);
  if (threadId) {
    bindThreadToTopic(threadId, topicInfo, fallbackTopic);
    renderThreadOptions(state.appThreads, threadId);
    return threadId;
  }

  if (options.createIfMissing) {
    const thread = await createBoundThreadForTopic({ mode, selectedTopic: topicInfo, topic: fallbackTopic });
    threadId = thread?.id || selectedThreadId();
    if (!threadId) throw new Error("Failed to create app-server thread.");
    return threadId;
  }

  throw new Error("No existing DLW thread matches this topic.");
}

async function sendDlwActionToThread(action, options = {}) {
  connectAppServerEvents();
  const topic = els.topicInput.value.trim();
  const workspaceDirectory = action === "start" ? els.topicDirectoryInput.value.trim() : "";
  const actionTopic = action === "start" ? { topic, vault: null, workspaceDirectory } : state.status?.selectedTopic;
  if (action === "start" && !topic) {
    appendLog("meta", "Enter a research topic.");
    return;
  }
  if (
    action === "start" &&
    state.status?.state?.topic &&
    !options.skipSwitchConfirm
  ) {
    const confirmed = await openConfirmDialog({
      title: "Switch Topic",
      message: `This will switch the active topic to:\n${topic}\n\nContinue?`,
      confirmLabel: "Continue"
    });
    if (!confirmed) return;
  }

  let mode = selectedThreadMode();
  if (dlwActionRequiresWrite(action) && mode !== "write") {
    if (options.ensureWrite) {
      setSelectedThreadMode("write");
      mode = "write";
    } else {
      const confirmed = await openConfirmDialog({
        title: "Allow Edits",
        message: 'This DLW action usually writes to the vault. Switch to "Allow Edits" and continue?',
        confirmLabel: "Allow Edits"
      });
      if (!confirmed) return;
      setSelectedThreadMode("write");
      mode = "write";
    }
  }
  state.dlwStartupBusy = true;
  const startupStage = inferRunningStageForAction(action, actionTopic);
  state.localRunningStage = startupStage;
  els.appServerState.textContent = action === "start" ? "Preparing topic..." : "Preparing DLW...";
  appendLog("meta", action === "start" ? `Preparing new topic: ${topic}` : `Preparing DLW ${action}...`);
  if (state.status) renderStatus(state.status);
  renderThreadStatus();

  try {
    const threadId = await ensureAppServerThreadForDlw(mode, actionTopic, topic, {
      forceNew: action === "start",
      createIfMissing: action !== "start"
    });
    const runningStage = inferRunningStageForAction(action, actionTopic);
    state.activeDlwThreadId = threadId;
    state.localRunningStage = runningStage;
    if (runningStage) state.appThreadRunningStages[threadId] = runningStage;
    saveThreadPreferences();
    els.appServerState.textContent = "Sending DLW...";
    appendLog("meta", "Starting Deep Literature Workflow in the bound Codex thread...");
    if (state.status) renderStatus(state.status);

    const result = await api(`/api/appserver/threads/${encodeURIComponent(threadId)}/dlw-action`, {
      method: "POST",
      body: JSON.stringify({
        action,
        topic,
        selectedTopic: actionTopic,
        mode,
        model: selectedThreadModel(),
        effort: selectedReasoningEffort(),
        workspaceDirectory
      })
    });
    const boundTopic = result.selectedTopic || actionTopic;
    if (result.status?.threadId) mergeAppThreadStatus(result.status.threadId, result.status);
    bindThreadToTopic(threadId, boundTopic, topic);
    els.appServerState.textContent = "DLW turn started";
    appendLog("meta", `DLW ${action} sent via plugin mention. turn=${result.turn?.id || ""}`);
    renderThreadStatus();
  } finally {
    state.dlwStartupBusy = false;
    if (state.status) renderStatus(state.status);
    renderThreadStatus();
  }
}

async function sendToAppServerThread() {
  connectAppServerEvents();
  const threadId = els.threadSelect.value;
  const message = els.threadMessage.value.trim();
  if (!threadId) {
    appendLog("meta", "Select or create a thread first.");
    return;
  }
  if (!message) {
    appendLog("meta", "Enter a message to send to the thread.");
    return;
  }
  if (selectedThreadIsBusy()) {
    const status = state.appThreadStatus[threadId];
    const label = status?.dlwAction || state.appThreadRunningStages[threadId] ? "The workflow is running. Use Cancel Run before sending another message." : "The thread is running. Stop it before sending another message.";
    appendLog("meta", label);
    return;
  }
  delete state.appThreadRunningStages[threadId];
  if (state.appThreadStatus[threadId]) {
    delete state.appThreadStatus[threadId].dlwAction;
    delete state.appThreadStatus[threadId].runningStage;
  }
  const mode = selectedThreadMode();
  saveThreadPreferences();
  els.appServerState.textContent = "Sending...";
  const previousMessage = els.threadMessage.value;
  els.threadMessage.value = "";
  resizeThreadMessage();
  appendThreadChatMessage(threadId, "user", message);
  let result;
  try {
    result = await api(`/api/appserver/threads/${encodeURIComponent(threadId)}/send`, {
      method: "POST",
      body: JSON.stringify({
        message,
        mode,
        model: selectedThreadModel(),
        effort: selectedReasoningEffort()
      })
    });
  } catch (error) {
    els.threadMessage.value = previousMessage;
    resizeThreadMessage();
    throw error;
  }
  els.appServerState.textContent = "turn started";
  if (result.status?.threadId) mergeAppThreadStatus(result.status.threadId, result.status);
  else mergeAppThreadStatus(threadId, {
    status: "running",
    turnId: result.turn?.id || null,
    summary: `Running${result.turn?.id ? ` · ${result.turn.id.slice(0, 8)}` : ""}`
  });
  appendLog("meta", `Sent to app-server thread. turn=${result.turn?.id || ""}`);
}

async function handleComposerPrimaryAction() {
  const threadId = selectedThreadId();
  const status = state.appThreadStatus[threadId];
  if (composerCanStopThread(threadId, status)) {
    await interruptAppServerThread(threadId);
    return;
  }
  await sendToAppServerThread();
}

async function interruptAppServerThread(threadId = selectedThreadId(), options = {}) {
  const status = state.appThreadStatus[threadId];
  if (!threadId || !status?.turnId) {
    appendLog("meta", "The current thread has no turn to stop.");
    return;
  }
  if (!options.skipConfirm) {
    const confirmed = await openConfirmDialog({
      title: "Stop Codex Turn",
      message: `Stop the current Codex turn?\nthread: ${threadId}\nturn: ${status.turnId}`,
      confirmLabel: "Stop",
      danger: true
    });
    if (!confirmed) return;
  }
  setCancellationStatus("Cancelling Codex turn...");
  mergeAppThreadStatus(threadId, {
    status: "stopping",
    summary: `Stopping · ${status.turnId.slice(0, 8)}`
  });
  els.appServerState.textContent = "Stopping...";
  const result = await api(`/api/appserver/threads/${encodeURIComponent(threadId)}/interrupt`, {
    method: "POST",
    body: JSON.stringify({
      turnId: status.turnId,
      cancelStage3Downloads: isStage3CancellationContext(threadId)
    })
  });
  if (result.stage3Downloads) {
    state.stage3DownloadCount = result.stage3Downloads.remaining?.length ?? 0;
    logStage3CancellationResult(result.stage3Downloads);
  }
  if (result.status?.threadId) mergeAppThreadStatus(result.status.threadId, result.status);
  els.appServerState.textContent = "turn stopped";
  setCancellationStatus("Cancelled");
  appendLog("meta", `Interrupted app-server turn. turn=${status.turnId}`);
}

async function respondToApproval(action) {
  const requestId = els.approvalPanel.dataset.requestId;
  if (!requestId) return;
  els.approvalApproveBtn.disabled = true;
  els.approvalDenyBtn.disabled = true;
  els.approvalCancelBtn.disabled = true;
  try {
    await api(`/api/appserver/approvals/${encodeURIComponent(requestId)}/respond`, {
      method: "POST",
      body: JSON.stringify({ action })
    });
    removePendingApproval(requestId);
    await loadPendingApprovals().catch(() => {});
  } finally {
    els.approvalApproveBtn.disabled = false;
    els.approvalDenyBtn.disabled = false;
    els.approvalCancelBtn.disabled = false;
    renderThreadStatus();
  }
}

function handleThreadMessageKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  if (selectedThreadIsBusy()) return;
  sendToAppServerThread().catch(showError);
}

function selectedThreadIsBusy() {
  const threadId = selectedThreadId();
  const status = state.appThreadStatus[threadId];
  return Boolean(threadId && status?.turnId && ["running", "stopping", "waiting_approval"].includes(status.status));
}

function composerCanStopThread(threadId = selectedThreadId(), status = state.appThreadStatus[threadId]) {
  if (!threadId || !status?.turnId || !["running", "stopping", "waiting_approval"].includes(status.status)) return false;
  return !status.dlwAction && !state.appThreadRunningStages[threadId];
}

function canInterruptThread(threadId) {
  const status = state.appThreadStatus[threadId];
  return Boolean(threadId && status?.turnId && ["running", "stopping", "waiting_approval"].includes(status.status));
}

function hasRunningProcess() {
  return Boolean(state.currentRunId || state.dlwStartupBusy || interruptibleThreadId() || state.stage3DownloadCount > 0);
}

function interruptibleThreadId(topicInfo = state.status?.selectedTopic) {
  const candidates = [
    state.activeDlwThreadId,
    selectedThreadId(),
    boundThreadIdForTopic(topicInfo)
  ].filter(Boolean);
  return candidates.find((threadId, index) => candidates.indexOf(threadId) === index && canInterruptThread(threadId)) || "";
}

function topicStagePromptKey(topicInfo, action) {
  const topic = topicInfo?.topic || "unknown-topic";
  const vault = topicInfo?.vault || "unknown-vault";
  const nextStage = topicInfo?.nextStage || "unknown-stage";
  const manualCount = topicInfo?.manualPdfCount ?? 0;
  return `${vault}|${topic}|${nextStage}|manual:${manualCount}|${action}`;
}

function stageActionInfo(topicInfo) {
  if (!topicInfo?.vault || !topicInfo.nextStage || topicInfo.nextStage === "complete") return null;
  if (interruptibleThreadId(topicInfo) || state.currentRunId || state.isCreatingTopic || state.stagePromptInFlight) return null;
  const action = topicInfo.nextStage === "stage_3_pdf_acquisition"
    ? ((topicInfo.manualPdfCount ?? 0) > 0 ? "importManual" : "stage3")
    : "resume";
  const key = topicStagePromptKey(topicInfo, action);
  if (state.dismissedStagePrompts.has(key)) return null;
  return {
    action,
    key,
    topic: topicInfo.topic || "current topic",
    manualCount: topicInfo.manualPdfCount ?? 0,
    nextStage: topicInfo.nextStage
  };
}

function stageConfirmTitle(info) {
  if (info.action === "importManual") return "Manual PDFs Ready To Import";
  if (info.action === "stage3") return "Stage 3 Waiting For Confirmation";
  return `${labelStage(info.nextStage)} Waiting For Confirmation`;
}

function stageConfirmText(info) {
  if (info.action === "importManual") {
    return `${info.topic} has ${info.manualCount} manual PDF queue item(s). Confirm to import them in the current thread with Allow Edits.`;
  }
  if (info.action === "stage3") {
    return `${info.topic} has reached PDF Acquisition. Confirm to start Stage 3 in the current thread with Allow Edits.`;
  }
  return `${info.topic} is ready for ${labelStage(info.nextStage)}. Confirm to continue the workflow in the current thread with Allow Edits.`;
}

function stageConfirmButtonText(info) {
  if (info.action === "importManual") return "Confirm Import";
  if (info.action === "stage3") return "Confirm Start";
  return "Confirm Resume";
}

function renderStageConfirmPanel(topicInfo) {
  if (!els.stageConfirmPanel) return;
  const info = stageActionInfo(topicInfo);
  state.pendingStageAction = info;
  if (!info) {
    els.stageConfirmPanel.classList.add("hidden");
    return;
  }
  els.stageConfirmPanel.classList.remove("hidden");
  els.stageConfirmTitle.textContent = stageConfirmTitle(info);
  els.stageConfirmText.textContent = stageConfirmText(info);
  els.stageConfirmBtn.textContent = stageConfirmButtonText(info);
}

function maybePromptStageAction(topicInfo) {
  renderStageConfirmPanel(topicInfo);
}

async function confirmPendingStageAction(action = state.pendingStageAction?.action) {
  if (!action) return;
  state.stagePromptInFlight = true;
  if (els.stageConfirmBtn) els.stageConfirmBtn.disabled = true;
  try {
    await sendDlwActionToThread(action, { ensureWrite: true, skipWriteConfirm: true });
  } finally {
    state.stagePromptInFlight = false;
    if (els.stageConfirmBtn) els.stageConfirmBtn.disabled = false;
    if (state.status) renderStatus(state.status);
  }
}

function resizeThreadMessage() {
  const maxHeight = 180;
  els.threadMessage.style.height = "auto";
  const nextHeight = Math.min(Math.max(els.threadMessage.scrollHeight, 46), maxHeight);
  els.threadMessage.style.height = `${nextHeight}px`;
  els.threadMessage.style.overflowY = els.threadMessage.scrollHeight > maxHeight ? "auto" : "hidden";
}

function handleThreadWorkspaceWheel(event) {
  const interactive = event.target.closest("textarea, select, button, input, .log, .thread-chat");
  if (interactive) return;
  if (!els.threadChat) return;
  const canScroll = els.threadChat.scrollHeight > els.threadChat.clientHeight;
  if (!canScroll) return;
  els.threadChat.scrollTop += event.deltaY;
  event.preventDefault();
}

async function startRun(action) {
  const topic = els.topicInput.value.trim();
  const workspaceDirectory = action === "start" ? els.topicDirectoryInput.value.trim() : "";
  if (action === "start" && !topic) {
    appendLog("meta", "Enter a research topic.");
    return;
  }
  if (
    action === "start" &&
    state.status?.state?.topic
  ) {
    const confirmed = await openConfirmDialog({
      title: "Switch Topic",
      message: `This will switch the active topic to:\n${topic}\n\nContinue?`,
      confirmLabel: "Continue"
    });
    if (!confirmed) return;
  }

  const run = await api("/api/runs", {
    method: "POST",
    body: JSON.stringify({ action, topic, workspaceDirectory, selectedTopic: state.status?.selectedTopic })
  });
  state.currentRunId = run.id;
  state.localRunningStage = inferRunningStageForAction(action);
  state.autoPipeline = ["start", "resume", "stage3", "importManual"].includes(action);
  state.lastRunAction = action;
  els.cancelBtn.disabled = false;
  els.runState.textContent = run.title;
  appendLog("meta", `Run ${run.id}: ${run.title}`);
  connectRun(run.id);
  startProgressPolling();
  renderStatus(state.status);
}

function inferRunningStageForAction(action, topicInfo = state.status?.selectedTopic) {
  if (action === "start") return "stage_1_discovery";
  if (action === "stage3") return "stage_3_pdf_acquisition";
  if (action === "importManual") return "stage_3_pdf_acquisition";
  return topicInfo?.nextStage || state.status?.selectedTopic?.nextStage || null;
}

function connectRun(id) {
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource(`/api/runs/${id}/events`);
  state.eventSource = source;

  source.addEventListener("meta", (event) => appendLog("meta", JSON.parse(event.data).message));
  source.addEventListener("log", (event) => {
    const data = JSON.parse(event.data);
    appendLog(data.stream === "stderr" ? "stderr" : "stdout", data.message);
  });
  source.addEventListener("codex", (event) => {
    const data = JSON.parse(event.data);
    const summary = data.summary;
    const type = summary?.type || "event";
    const message = String(summary?.message || "").trim();
    if (!message && (type === "item.started" || type === "item.completed")) return;
    appendLog("codex", message ? `[${type}] ${message}` : `[${type}]`);
  });
  source.addEventListener("done", async (event) => {
    const data = JSON.parse(event.data);
    const completedStage = state.localRunningStage;
    const shouldContinuePipeline = state.autoPipeline && data.status === "complete";
    const completedAction = state.lastRunAction;
    appendLog(data.status === "complete" ? "done" : "failed", `Run ${data.status}. code=${data.code ?? ""}`);
    source.close();
    state.currentRunId = null;
    state.localRunningStage = null;
    state.eventSource = null;
    stopProgressPolling();
    els.cancelBtn.disabled = true;
    els.runState.textContent = "Idle";
    await refreshStatus();
    maybeContinuePipeline(shouldContinuePipeline, completedStage);
  });
  source.onerror = () => {
    appendLog("stderr", "Event stream disconnected.");
  };
}

function maybeContinuePipeline(shouldContinue, completedStage) {
  if (!shouldContinue) {
    state.autoPipeline = false;
    return;
  }
  const nextStage = state.status?.selectedTopic?.nextStage;
  const active = state.status?.selectedTopic?.active;
  if (!active || !nextStage || nextStage === "complete") {
    state.autoPipeline = false;
    return;
  }
  if (nextStage === "stage_3_pdf_acquisition") {
    state.autoPipeline = false;
    appendLog("meta", "Paused before Stage 3. Please confirm Stage 3 before PDF acquisition.");
    return;
  }
  if (completedStage && nextStage === completedStage) {
    state.autoPipeline = false;
    appendLog("meta", `Stopped because workflow state still reports ${nextStage}.`);
    return;
  }
  appendLog("meta", `Auto continuing next stage: ${labelStage(nextStage)}`);
  setTimeout(() => startRun("resume").catch(showError), 900);
}

function startProgressPolling() {
  stopProgressPolling();
  state.progressPollTimer = setInterval(async () => {
    if (!state.currentRunId) return;
    try {
      await refreshStatus();
    } catch (error) {
      showError(error);
    }
  }, 8000);
}

function stopProgressPolling() {
  if (!state.progressPollTimer) return;
  clearInterval(state.progressPollTimer);
  state.progressPollTimer = null;
}

function appendLog(kind, message) {
  const entry = document.createElement("div");
  entry.className = `log-entry ${kind}`;
  const time = new Date().toLocaleTimeString();
  entry.textContent = `[${time}] ${message}`;
  els.log.append(entry);
  els.log.scrollTop = els.log.scrollHeight;
}

function setCancellationStatus(message) {
  if (els.runState) els.runState.textContent = message;
  appendLog("meta", message);
}

function logStage3CancellationResult(result = {}) {
  const termCount = result.killed?.length ?? 0;
  const forceCount = result.forceKilled?.length ?? 0;
  const remainingCount = result.remaining?.length ?? 0;
  appendLog("meta", `Stage 3 downloader cleanup: SIGTERM ${termCount}, SIGKILL ${forceCount}, remaining ${remainingCount}.`);
  if (remainingCount > 0) {
    const pids = result.remaining.map((item) => item.pid).join(", ");
    appendLog("stderr", `Stage 3 downloader still running after cancel: ${pids}`);
  }
}

function logProcessTreeCancellationResult(result = {}) {
  const termCount = result.killed?.length ?? 0;
  const forceCount = result.forceKilled?.length ?? 0;
  const remainingCount = result.remaining?.length ?? 0;
  appendLog("meta", `Run process cleanup: SIGTERM ${termCount}, SIGKILL ${forceCount}, remaining ${remainingCount}.`);
  if (remainingCount > 0) {
    const pids = result.remaining.map((item) => item.pid).join(", ");
    appendLog("stderr", `Run process still alive after cancel: ${pids}`);
  }
}

async function cancelRun() {
  if (!state.currentRunId) return;
  setCancellationStatus("Cancelling current run...");
  const result = await api(`/api/runs/${state.currentRunId}/cancel`, { method: "POST", body: "{}" });
  if (result.processTree) logProcessTreeCancellationResult(result.processTree);
  if (result.stage3Downloads) {
    state.stage3DownloadCount = result.stage3Downloads.remaining?.length ?? 0;
    logStage3CancellationResult(result.stage3Downloads);
  }
  await refreshStatus().catch(() => {});
  const processRemaining = result.processTree?.remaining?.length ?? 0;
  setCancellationStatus(
    state.stage3DownloadCount > 0 || processRemaining > 0
      ? "Cancel requested; processes still running"
      : "Cancelled"
  );
}

function isStage3CancellationContext(threadId = interruptibleThreadId()) {
  return (
    state.localRunningStage === "stage_3_pdf_acquisition" ||
    state.appThreadRunningStages[threadId] === "stage_3_pdf_acquisition" ||
    state.stage3DownloadCount > 0 ||
    state.status?.selectedTopic?.nextStage === "stage_3_pdf_acquisition" ||
    state.status?.selectedTopic?.currentStage === "stage_3_pdf_acquisition"
  );
}

async function cancelStage3DownloadsIfNeeded(threadId = interruptibleThreadId()) {
  if (!isStage3CancellationContext(threadId)) return null;
  setCancellationStatus("Cancelling Stage 3 downloaders...");
  const result = await api("/api/stage3/downloads/cancel", { method: "POST", body: "{}" });
  state.stage3DownloadCount = result.remaining?.length ?? 0;
  logStage3CancellationResult(result);
  await refreshStatus().catch(() => {});
  setCancellationStatus(state.stage3DownloadCount > 0 ? "Cancel requested; downloaders still running" : "Cancelled");
  return result;
}

async function chooseTopicDirectory() {
  const previousLabel = els.chooseDirectoryBtn.textContent;
  els.chooseDirectoryBtn.disabled = true;
  els.chooseDirectoryBtn.textContent = "...";
  try {
    const result = await api("/api/directories/choose", { method: "POST", body: "{}" });
    if (result.path) els.topicDirectoryInput.value = result.path;
  } finally {
    els.chooseDirectoryBtn.disabled = false;
    els.chooseDirectoryBtn.textContent = previousLabel;
  }
}

async function bindSelectedTopicToExistingThread(topicInfo = state.status?.selectedTopic) {
  if (!topicInfo?.topic) return "";
  if (!state.appThreadsLoaded) await listAppServerThreads();
  const existing = boundThreadIdForTopic(topicInfo);
  if (existing && threadLooksLikeDlwWorkThread(existing, topicInfo)) {
    renderThreadOptions(state.appThreads, existing);
    loadThreadMessages(existing, { force: true }).catch(showError);
    return existing;
  }
  if (existing) forgetThreadBinding(topicInfo);
  const threadId = matchingThreadIdByTopicName(state.appThreads, topicInfo);
  const key = topicThreadKey(topicInfo);
  if (!threadId) {
    if (key && !state.missingThreadNotices.has(key)) {
      state.missingThreadNotices.add(key);
      appendLog("meta", `No existing DLW thread matched ${topicInfo.topic}; no new thread was created.`);
    }
    renderThreadOptions(state.appThreads, null);
    renderThreadStatus();
    return "";
  }
  bindThreadToTopic(threadId, topicInfo);
  state.missingThreadNotices.delete(key);
  renderThreadOptions(state.appThreads, threadId);
  loadThreadMessages(threadId, { force: true }).catch(showError);
  appendLog("meta", `Bound existing Codex thread for ${topicInfo.topic}: ${threadId.slice(0, 8)}`);
  return threadId;
}

async function importExistingVault() {
  const previousLabel = els.importVaultBtn.textContent;
  els.importVaultBtn.disabled = true;
  els.importVaultBtn.textContent = "Importing...";
  state.dlwStartupBusy = true;
  els.appServerState.textContent = "Importing vault...";
  appendLog("meta", "Choose an existing Deep Survey vault to import.");
  try {
    const result = await api("/api/vaults/import", { method: "POST", body: "{}" });
    if (result.cancelled) {
      appendLog("meta", "Import cancelled.");
      return;
    }
    state.isCreatingTopic = false;
    state.selectedVault = result.topic?.vault || result.state?.vault_root || state.selectedVault;
    await refreshStatus();
    await bindSelectedTopicToExistingThread(state.status?.selectedTopic || result.topic);
    appendLog("meta", `Imported vault: ${state.status?.selectedTopic?.topic || result.state?.topic || "existing topic"}`);
  } finally {
    state.dlwStartupBusy = false;
    els.importVaultBtn.disabled = false;
    els.importVaultBtn.textContent = previousLabel;
    if (state.status) renderStatus(state.status);
  }
}

els.startBtn.addEventListener("click", () => {
  sendDlwActionToThread("start", {
    ensureWrite: true,
    skipSwitchConfirm: true,
    skipWriteConfirm: true
  }).catch(showError);
});
els.chooseDirectoryBtn.addEventListener("click", () => chooseTopicDirectory().catch(showError));
els.importVaultBtn.addEventListener("click", () => importExistingVault().catch(showError));
els.newTopicBtn.addEventListener("click", () => {
  state.isCreatingTopic = true;
  els.topicInput.value = "";
  els.topicDirectoryInput.value = state.status?.workspaceRoot || "";
  if (state.status) renderStatus(state.status);
  els.topicInput.focus();
});
els.resumeBtn.addEventListener("click", () => {
  if (state.pendingStageAction) {
    confirmPendingStageAction(state.pendingStageAction.action).catch(showError);
    return;
  }
  sendDlwActionToThread("resume", { ensureWrite: true }).catch(showError);
});
if (els.stage3Btn) {
  els.stage3Btn.addEventListener("click", () => confirmPendingStageAction("stage3").catch(showError));
}
if (els.stageConfirmBtn) {
  els.stageConfirmBtn.addEventListener("click", () => confirmPendingStageAction().catch(showError));
}
if (els.manualBtn) {
  els.manualBtn.addEventListener("click", () => confirmPendingStageAction("importManual").catch(showError));
}
async function handleCancelRunClick() {
  if (state.currentRunId) {
    const confirmed = await openConfirmDialog({
      title: "Cancel Current Run",
      message: "Cancel the currently running Codex task? Files already written will not be rolled back automatically.",
      confirmLabel: "Cancel Run",
      danger: true
    });
    if (!confirmed) return;
    const previousLabel = els.cancelBtn.textContent;
    els.cancelBtn.disabled = true;
    els.cancelBtn.textContent = "Cancelling...";
    try {
      await cancelRun();
    } finally {
      els.cancelBtn.textContent = previousLabel;
      if (state.status) renderStatus(state.status);
    }
    return;
  }
  const threadId = interruptibleThreadId();
  const cleanupText = isStage3CancellationContext(threadId)
    ? "\n\nThis is a Stage 3 context, so Chrome PDF download scripts will also be stopped."
    : "";
  const confirmed = await openConfirmDialog({
    title: "Cancel Current Run",
    message: `Cancel the currently running Codex task? Files already written will not be rolled back automatically.${cleanupText}`,
    confirmLabel: "Cancel Run",
    danger: true
  });
  if (!confirmed) return;
  const previousLabel = els.cancelBtn.textContent;
  els.cancelBtn.disabled = true;
  els.cancelBtn.textContent = "Cancelling...";
  try {
    if (!threadId) {
      await cancelStage3DownloadsIfNeeded(threadId);
      return;
    }
    await interruptAppServerThread(threadId, { skipConfirm: true });
  } finally {
    els.cancelBtn.textContent = previousLabel;
    if (state.status) renderStatus(state.status);
  }
}

els.cancelBtn.addEventListener("click", () => handleCancelRunClick().catch(showError));
els.refreshBtn.addEventListener("click", async () => {
  const previousText = els.refreshBtn.textContent;
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = "...";
  try {
    await refreshStatus();
  } catch (error) {
    showError(error);
  } finally {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = previousText;
  }
});
els.runTabBtn.addEventListener("click", () => setActiveTab("run"));
els.vaultTabBtn.addEventListener("click", () => setActiveTab("vault"));
els.vaultSearch.addEventListener("input", renderVaultFiles);
els.vaultFiles.tabIndex = 0;
els.vaultFiles.addEventListener("keydown", handleVaultFileKeydown);
els.vaultPreview.addEventListener("click", (event) => {
  const link = event.target.closest?.("a[data-md-href]");
  if (!link) return;
  event.preventDefault();
  openMarkdownLink(link.dataset.mdHref || link.getAttribute("href") || "").catch(showError);
});
els.setupRetryBtn.addEventListener("click", () => runSetupCheck({ install: false }).catch(showError));
els.setupInstallBtn.addEventListener("click", () => runSetupCheck({ install: true }).catch(showError));
els.codexPill.addEventListener("click", () => {
  if (els.codexPill.classList.contains("actionable")) {
    runSetupCheck({ install: true }).catch(showError);
  }
});
els.sendThreadBtn.addEventListener("click", () => handleComposerPrimaryAction().catch(showError));
els.stopThreadBtn.addEventListener("click", () => interruptAppServerThread().catch(showError));
els.approvalApproveBtn.addEventListener("click", () => respondToApproval("approve").catch(showError));
els.approvalDenyBtn.addEventListener("click", () => respondToApproval("decline").catch(showError));
els.approvalCancelBtn.addEventListener("click", () => respondToApproval("cancel").catch(showError));
document.querySelectorAll('input[name="threadMode"], input[name="reasoningEffort"]').forEach((input) => {
  input.addEventListener("change", () => {
    saveThreadPreferences();
    renderThreadStatus();
  });
});
els.threadModeSelect.addEventListener("change", () => {
  saveThreadPreferences();
  renderThreadStatus();
});
els.threadModelMenuBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  updateModelMenu();
  setModelMenuOpen(els.threadModelMenu.classList.contains("hidden"));
  setThreadModeMenuOpen(false);
});
els.threadModeMenuBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  updateThreadModeMenu();
  setThreadModeMenuOpen(els.threadModeMenu.classList.contains("hidden"));
  setModelMenuOpen(false);
});
document.querySelectorAll(".model-option").forEach((button) => {
  button.addEventListener("click", () => {
    selectThreadModel(button.dataset.model);
    updateModelMenu();
  });
});
document.querySelectorAll(".effort-option").forEach((button) => {
  button.addEventListener("click", () => {
    selectReasoningEffort(button.dataset.effort);
    updateModelMenu();
  });
});
document.querySelectorAll(".permission-option").forEach((button) => {
  button.addEventListener("click", () => {
    setSelectedThreadMode(button.dataset.mode);
    setThreadModeMenuOpen(false);
  });
});
document.addEventListener("click", (event) => {
  if (els.threadModelMenu && !els.threadModelMenu.classList.contains("hidden")) {
    if (!els.threadModelMenu.contains(event.target) && !els.threadModelMenuBtn.contains(event.target)) {
      setModelMenuOpen(false);
    }
  }
  if (els.threadModeMenu && !els.threadModeMenu.classList.contains("hidden")) {
    if (!els.threadModeMenu.contains(event.target) && !els.threadModeMenuBtn.contains(event.target)) {
      setThreadModeMenuOpen(false);
    }
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setModelMenuOpen(false);
    setThreadModeMenuOpen(false);
  }
});
els.threadSelect.addEventListener("change", () => {
  bindThreadToTopic(selectedThreadId());
  renderThreadStatus();
  loadThreadMessages(selectedThreadId(), { force: true }).catch(showError);
});
els.threadMessage.addEventListener("keydown", handleThreadMessageKeydown);
els.threadMessage.addEventListener("input", resizeThreadMessage);
els.threadWorkspace.addEventListener("wheel", handleThreadWorkspaceWheel, { passive: false });

function showError(error) {
  appendLog("stderr", error.message || String(error));
}

restoreThreadPreferences();
resizeThreadMessage();
renderSetupPanel(null);

refreshStatus()
  .then(() => runSetupCheck({ install: true }).catch(showError))
  .then(() => listAppServerThreads().catch(showError))
  .catch(showError);
