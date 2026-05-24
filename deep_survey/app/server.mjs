import { spawn, execFile } from "node:child_process";
import { createServer } from "node:http";
import { readFile, readdir, stat } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CodexAppServerClient } from "./codexAppServerClient.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "public");
const workspaceRoot = path.resolve(process.env.CODEX_DLW_WORKSPACE_ROOT || path.resolve(__dirname, ".."));
const dlwScript = path.join(workspaceRoot, "plugins/deep-literature-workflow/scripts/dlw.py");
const statePath = path.join(workspaceRoot, ".deep-literature-workflow/state.json");
const rootProjectStatePath = path.join(workspaceRoot, "PROJECT_STATE.md");
const runs = new Map();
const appServerEvents = [];
const appServerClients = new Set();
const appServerThreadStatus = new Map();
const appServerApprovalRequests = new Map();
const codexModel = process.env.CODEX_DLW_MODEL || "gpt-5.5";
const codexBinary = "/Applications/Codex.app/Contents/Resources/codex";
const commandPath = [
  "/Applications/Codex.app/Contents/Resources",
  "/opt/homebrew/bin",
  "/usr/local/bin",
  "/usr/bin",
  "/bin",
  "/usr/sbin",
  "/sbin",
  process.env.PATH || ""
].join(":");
const childEnv = {
  ...process.env,
  PATH: commandPath,
  LANG: process.env.LANG || "en_US.UTF-8",
  LC_ALL: process.env.LC_ALL || "en_US.UTF-8",
  PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8"
};
const codexAppServer = new CodexAppServerClient({
  codexPath: codexBinary,
  cwd: workspaceRoot,
  env: childEnv,
  model: codexModel
});
const allowedModels = new Set(["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"]);
const allowedReasoningEfforts = new Set(["low", "medium", "high", "xhigh"]);
const dlwPluginMention = {
  type: "mention",
  path: "plugin://deep-literature-workflow@deep-research-local",
  name: "Deep Literature Workflow"
};
const stage3DownloadProcessMarkers = [
  "/chrome-literature-downloader/scripts/download_literature_chrome.py",
  "/chrome-literature-downloader/scripts/batch_download_literature_chrome.py",
  "download_literature_chrome.py",
  "batch_download_literature_chrome.py",
  "stage3_fetch_pdfs_and_upgrade_notes.py",
  "stage2_deep_reading_queue",
  "08_stage3_pdf_inventory",
  "09_manual_pdf_download_queue"
];

const stages = [
  ["stage_1_discovery", "Stage 1 Discovery"],
  ["stage_2_screening", "Stage 2 Screening"],
  ["stage_3_pdf_acquisition", "Stage 3 PDF Acquisition"],
  ["stage_4_paper_deep_reading", "Stage 4 Deep Reading"],
  ["stage_5a_concept_notes", "Stage 5A Concepts"],
  ["stage_5b_review_synthesis", "Stage 5B Review"]
];

function json(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(data)
  });
  res.end(data);
}

function notFound(res) {
  json(res, 404, { error: "Not found" });
}

function badRequest(res, message) {
  json(res, 400, { error: message });
}

function normalizeModel(model) {
  return allowedModels.has(model) ? model : codexModel;
}

function normalizeReasoningEffort(effort) {
  return allowedReasoningEfforts.has(effort) ? effort : "medium";
}

function forbidden(res, message) {
  json(res, 403, { error: message });
}

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error("Request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

async function readJsonIfExists(filePath) {
  try {
    const raw = await readFile(filePath, "utf8");
    return JSON.parse(raw);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

function execFileText(command, args, options = {}) {
  return new Promise((resolve) => {
    execFile(command, args, { ...options, env: { ...childEnv, ...(options.env || {}) } }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        code: error?.code ?? 0,
        stdout: stdout?.toString() ?? "",
        stderr: stderr?.toString() ?? "",
        error: error?.message ?? null
      });
    });
  });
}

function isStage3DownloadCommand(command) {
  return stage3DownloadProcessMarkers.some((marker) => command.includes(marker));
}

async function listStage3DownloadProcesses() {
  const result = await execFileText("ps", ["-axo", "pid=,command="], { cwd: workspaceRoot });
  if (!result.ok) return [];
  return result.stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(.+)$/);
      if (!match) return null;
      return { pid: Number(match[1]), command: match[2] };
    })
    .filter((item) => item && item.pid !== process.pid && isStage3DownloadCommand(item.command));
}

async function cancelStage3DownloadProcesses() {
  const processes = await listStage3DownloadProcesses();
  const killed = [];
  const failed = [];
  for (const item of processes) {
    try {
      process.kill(item.pid, "SIGTERM");
      killed.push(item);
    } catch (error) {
      if (error.code !== "ESRCH") {
        failed.push({ ...item, error: error.message || String(error) });
      }
    }
  }
  return { killed, failed, count: killed.length };
}

function runLooksLikeStage3(run) {
  const text = `${run?.title || ""}\n${run?.prompt || ""}`.toLowerCase();
  return (
    text.includes("stage 3") ||
    text.includes("pdf acquisition") ||
    text.includes("pdf 获取") ||
    text.includes("导入当前选中课题中手动下载的 pdf")
  );
}

async function getStatus() {
  const [codexVersion, nodeVersion, dlwStatus] = await Promise.all([
    execFileText("codex", ["--version"], { cwd: workspaceRoot }),
    Promise.resolve({ ok: true, stdout: process.version }),
    existsSync(dlwScript)
      ? execFileText("python3", [dlwScript, "status"], { cwd: workspaceRoot })
      : Promise.resolve({ ok: false, stdout: "", stderr: "dlw.py not found" })
  ]);

  let workflowState = await readJsonIfExists(statePath);
  if (!workflowState && dlwStatus.ok) {
    try {
      workflowState = JSON.parse(dlwStatus.stdout);
    } catch {
      workflowState = null;
    }
  }

  const vaultRoot = workflowState?.vault_root
    ? resolveVaultRoot(workflowState.vault_root)
    : null;
  const topicHandoff = vaultRoot
    ? path.join(vaultRoot, "08_Project_Workflow/PROJECT_STATE.md")
    : null;
  const manualQueuePath = vaultRoot
    ? path.join(vaultRoot, "04_Evidence_Tables/09_manual_pdf_download_queue.md")
    : null;

  const fileChecks = await Promise.all(
    [
      ["workspace", workspaceRoot],
      ["dlwScript", dlwScript],
      ["rootProjectState", rootProjectStatePath],
      ["vaultRoot", vaultRoot],
      ["topicHandoff", topicHandoff],
      ["manualQueue", manualQueuePath]
    ].map(async ([key, filePath]) => {
      if (!filePath) return [key, false];
      try {
        await stat(filePath);
        return [key, true];
      } catch {
        return [key, false];
      }
    })
  );
  const topics = await readTopicIndex(workflowState);

  const dlwOk = Boolean(existsSync(dlwScript));

  return {
    workspaceRoot,
    codex: {
      ok: codexVersion.ok,
      version: codexVersion.stdout.trim(),
      error: codexVersion.stderr.trim() || codexVersion.error,
      model: codexModel
    },
    node: nodeVersion.stdout,
    dlw: {
      ok: dlwOk,
      error: dlwOk ? null : dlwStatus.stderr.trim() || dlwStatus.error
    },
    state: workflowState,
    topics,
    stages: stages.map(([id, label]) => {
      const rawStatus = workflowState?.stage_status?.[id] ?? "pending";
      const isActive = workflowState?.current_stage === id && rawStatus !== "done";
      return {
        id,
        label,
        status: rawStatus,
        rawStatus,
        isActive
      };
    }),
    paths: Object.fromEntries(fileChecks),
    artifactPaths: {
      vaultRoot,
      topicHandoff,
      manualQueue: manualQueuePath
    },
    manualPdfCount: workflowState?.manual_pdf_queue?.length ?? 0,
    nextStage: inferNextStage(workflowState?.stage_status)
  };
}

function resolveVaultRoot(vault) {
  if (!vault || vault.includes("\0")) return null;
  if (!path.isAbsolute(vault) && vault.includes("..")) return null;
  const resolved = path.isAbsolute(vault) ? path.resolve(vault) : path.resolve(workspaceRoot, vault);
  if (!path.isAbsolute(vault) && !resolved.startsWith(`${workspaceRoot}${path.sep}`)) return null;
  return resolved;
}

function buildSelectedTopic(activeState, topics, vault) {
  const selected =
    (vault && topics.find((topic) => topic.vault === vault)) ||
    topics.find((topic) => topic.active) ||
    topics[0] ||
    null;
  const selectedState =
    selected?.active || !selected
      ? activeState
      : {
          topic: selected.topic,
          vault_root: selected.vault,
          current_stage: selected.currentStage,
          stage_status: selected.stageStatus || {},
          manual_pdf_queue: Array.from({ length: selected.manualPdfCount || 0 })
        };
  const nextStage = inferNextStage(selectedState?.stage_status);
  return {
    topic: selected?.topic || selectedState?.topic || null,
    vault: selected?.vault || selectedState?.vault_root || null,
    active: Boolean(selected?.active),
    status: selected?.status || null,
    handoff: selected?.handoff || null,
    artifactPaths: selected
      ? {
          vaultRoot: resolveVaultRoot(selected.vault),
          topicHandoff: path.isAbsolute(selected.handoff)
            ? selected.handoff
            : path.join(workspaceRoot, selected.handoff),
          manualQueue: path.join(
            resolveVaultRoot(selected.vault) || path.join(workspaceRoot, selected.vault),
            "04_Evidence_Tables/09_manual_pdf_download_queue.md"
          )
        }
      : {},
    manualPdfCount: selectedState?.manual_pdf_queue?.length ?? 0,
    nextStage,
    stages: stages.map(([id, label]) => {
      const rawStatus = selectedState?.stage_status?.[id] ?? "unknown";
      const isActive = selectedState?.current_stage === id && rawStatus !== "done";
      return {
        id,
        label,
        status: rawStatus,
        rawStatus,
        isActive
      };
    })
  };
}

function inferNextStage(stageStatus = {}) {
  for (const [stage] of stages) {
    if (stageStatus[stage] !== "done") return stage;
  }
  return "complete";
}

function safeVaultRoot(vault) {
  return resolveVaultRoot(vault);
}

async function listMarkdownFiles(root, current = root, output = []) {
  const entries = await readdir(current, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const fullPath = path.join(current, entry.name);
    if (entry.isDirectory()) {
      await listMarkdownFiles(root, fullPath, output);
    } else if (entry.isFile() && entry.name.endsWith(".md")) {
      output.push(path.relative(root, fullPath));
    }
  }
  return output.sort((a, b) => a.localeCompare(b));
}

async function readVaultMarkdown(vault, relativePath) {
  const root = safeVaultRoot(vault);
  if (!root) return { error: "Invalid vault path", status: 403 };
  if (!relativePath || relativePath.includes("..") || path.isAbsolute(relativePath)) {
    return { error: "Invalid markdown path", status: 403 };
  }
  if (!relativePath.endsWith(".md")) {
    return { error: "Only Markdown files can be read", status: 403 };
  }
  const resolved = path.resolve(root, relativePath);
  if (!resolved.startsWith(`${root}${path.sep}`)) {
    return { error: "Path escapes vault", status: 403 };
  }
  try {
    const content = await readFile(resolved, "utf8");
    return { path: relativePath, content };
  } catch (error) {
    return { error: error.message || String(error), status: 404 };
  }
}

async function readTopicIndex(workflowState) {
  let markdown = "";
  try {
    markdown = await readFile(rootProjectStatePath, "utf8");
  } catch {
    return [];
  }
  const activeVault = workflowState?.vault_root;
  const rows = [];
  for (const line of markdown.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|") || trimmed.startsWith("|---")) continue;
    const cells = trimmed
      .slice(1, -1)
      .split("|")
      .map((cell) => cell.trim().replace(/^`|`$/g, ""));
    if (cells.length < 4 || cells[0].toLowerCase() === "topic") continue;
    rows.push({
      topic: cells[0],
      vault: cells[1],
      status: cells[2],
      handoff: cells[3],
      active: cells[1] === activeVault
    });
  }
  return Promise.all(
    rows.map(async (topic) => {
      const handoffPath = path.isAbsolute(topic.handoff)
        ? topic.handoff
        : path.join(workspaceRoot, topic.handoff);
      try {
        const handoff = await readFile(handoffPath, "utf8");
        return {
          ...topic,
          currentStage: parseCurrentStage(handoff),
          stageStatus: parseStageStatus(handoff, topic.status),
          manualPdfCount: parseManualPdfCount(handoff)
        };
      } catch {
        return {
          ...topic,
          currentStage: null,
          stageStatus: inferStageStatusFromSummary(topic.status),
          manualPdfCount: null
        };
      }
    })
  );
}

function parseCurrentStage(markdown) {
  const match = markdown.match(/- Current stage:\s*`([^`]+)`/);
  return match?.[1] || null;
}

function parseStageStatus(markdown, summary = "") {
  const status = {};
  for (const match of markdown.matchAll(/- `(stage_[^`]+)`:\s*([A-Za-z_ -]+)/g)) {
    status[match[1]] = match[2].trim();
  }
  if (Object.keys(status).length) return status;
  return inferStageStatusFromSummary(`${summary}\n${markdown}`);
}

function inferStageStatusFromSummary(text = "") {
  const status = {};
  if (/Stages?\s+1-5B\s+done/i.test(text) || /Stage\s+5B/i.test(text)) {
    for (const [stage] of stages) status[stage] = "done";
    return status;
  }
  const doneCountMatch = text.match(/(\d+)\s+stage\(s\)\s+done/i);
  const doneCount = doneCountMatch ? Number(doneCountMatch[1]) : 0;
  for (const [index, [stage]] of stages.entries()) {
    status[stage] = index < doneCount ? "done" : "pending";
  }
  return status;
}

function parseManualPdfCount(markdown) {
  const match = markdown.match(/- (\d+) queued item\(s\)/);
  if (match) return Number(match[1]);
  if (markdown.includes("- empty")) return 0;
  return null;
}

function sendSse(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

function addAppServerEvent(event, data) {
  const item = { event, data, at: new Date().toISOString() };
  appServerEvents.push(item);
  if (appServerEvents.length > 300) appServerEvents.shift();
  for (const client of appServerClients) sendSse(client, event, data);
}

codexAppServer.on("notification", (message) => {
  updateAppServerThreadStatusFromNotification(message);
  addAppServerEvent("appserver", {
    method: message.method,
    params: message.params,
    summary: summarizeAppServerNotification(message)
  });
});
codexAppServer.on("serverRequest", (message) => {
  if (!String(message.method || "").includes("requestApproval")) {
    addAppServerEvent("appserver", {
      requestId: message.id,
      method: message.method,
      params: message.params,
      summary: message.method
    });
    return;
  }
  const approval = normalizeApprovalRequest(message);
  appServerApprovalRequests.set(approval.requestId, approval);
  updateAppServerThreadStatus(approval.threadId, {
    status: "waiting_approval",
    turnId: approval.turnId,
    summary: approval.summary,
    pendingApprovalRequestId: approval.requestId
  });
  addAppServerEvent("appserver", {
    requestId: approval.requestId,
    method: message.method,
    params: message.params,
    approval,
    summary: approval.summary
  });
});
codexAppServer.on("stderr", (message) => {
  const text = String(message || "").trim();
  if (text) addAppServerEvent("appserver", { method: "stderr", summary: text });
});
codexAppServer.on("exit", ({ code, signal }) => {
  addAppServerEvent("appserver", {
    method: "exit",
    summary: `app-server exited code=${code ?? ""} signal=${signal ?? ""}`
  });
});

function summarizeAppServerNotification(message) {
  const method = message.method;
  const params = message.params || {};
  if (method === "item/agentMessage/delta") return "";
  if (method === "turn/started") return `Turn started: ${params.turn?.id || ""}`;
  if (method === "turn/completed") return `Turn completed: ${params.turn?.status?.type || params.turn?.status || ""}`;
  if (method === "thread/started") return `Thread started: ${params.thread?.id || ""}`;
  if (method === "thread/status/changed") return `Thread status changed: ${params.status?.type || ""}`;
  if (method === "item/completed") return `Item completed: ${params.item?.type || params.item?.kind || ""}`;
  return method;
}

function summarizeApprovalRequest(message) {
  const method = message.method || "";
  const params = message.params || {};
  if (method.includes("commandExecution")) {
    const command = params.command || params.cmd || "";
    return command ? `Approval requested: ${command}` : "Command approval requested";
  }
  if (method.includes("fileChange")) return "File change approval requested";
  if (method.includes("permissions")) return "Permissions approval requested";
  return "Approval requested";
}

function normalizeApprovalRequest(message) {
  const params = message.params || {};
  const turnId = appServerTurnIdFromParams(params);
  const threadId = appServerThreadIdFromParams(params) || appServerThreadIdForTurn(turnId);
  const requestId = String(message.id);
  return {
    requestId,
    rawRequestId: message.id,
    method: message.method,
    threadId,
    turnId,
    itemId: params.itemId || params.item?.id || null,
    approvalId: params.approvalId || null,
    command: params.command || params.cmd || "",
    cwd: params.cwd || params.workingDirectory || "",
    reason: params.reason || params.rationale || "",
    availableDecisions: params.availableDecisions || [],
    params,
    summary: summarizeApprovalRequest(message),
    createdAt: new Date().toISOString()
  };
}

function appServerThreadIdFromParams(params = {}) {
  return params.threadId || params.thread?.id || params.turn?.threadId || params.item?.threadId || null;
}

function appServerTurnIdFromParams(params = {}) {
  return params.turnId || params.turn?.id || params.item?.turnId || null;
}

function appServerThreadIdForTurn(turnId) {
  if (!turnId) return null;
  for (const [threadId, status] of appServerThreadStatus.entries()) {
    if (status.turnId === turnId) return threadId;
  }
  return null;
}

function updateAppServerThreadStatus(threadId, patch) {
  if (!threadId) return null;
  const now = new Date().toISOString();
  const previous = appServerThreadStatus.get(threadId) || {
    threadId,
    status: "idle",
    turnId: null,
    summary: "Idle",
    updatedAt: now
  };
  const next = { ...previous, ...patch, threadId, updatedAt: now };
  appServerThreadStatus.set(threadId, next);
  return next;
}

function clearAppServerApprovalRequestsForThread(threadId, turnId = null) {
  if (!threadId && !turnId) return;
  for (const [requestId, approval] of appServerApprovalRequests.entries()) {
    if ((turnId && approval.turnId === turnId) || (threadId && approval.threadId === threadId)) {
      appServerApprovalRequests.delete(requestId);
    }
  }
}

function updateAppServerThreadStatusFromNotification(message) {
  const method = message.method;
  const params = message.params || {};
  const turnId = appServerTurnIdFromParams(params);
  const threadId = appServerThreadIdFromParams(params) || appServerThreadIdForTurn(turnId);
  if (method === "turn/started") {
    updateAppServerThreadStatus(threadId, {
      status: "running",
      turnId,
      summary: `Running turn ${turnId || ""}`.trim()
    });
  } else if (method === "turn/completed") {
    clearAppServerApprovalRequestsForThread(threadId, turnId);
    updateAppServerThreadStatus(threadId, {
      status: params.turn?.status?.type || "completed",
      turnId,
      summary: `Turn completed ${turnId || ""}`.trim()
    });
  } else if (method === "thread/status/changed") {
    if (!params.status?.activeFlags?.includes("waitingOnApproval") && ["idle", "completed", "interrupted", "failed"].includes(params.status?.type)) {
      clearAppServerApprovalRequestsForThread(threadId, turnId);
    }
    updateAppServerThreadStatus(threadId, {
      threadStatus: params.status,
      summary: `Thread status: ${params.status?.type || params.status || "changed"}`
    });
  }
}

function normalizeThread(thread = {}) {
  return {
    id: thread.id || thread.sessionId || null,
    sessionId: thread.sessionId || thread.id || null,
    name: thread.name || thread.preview || null,
    preview: thread.preview || null,
    cwd: thread.cwd || null,
    source: thread.source || null,
    status: thread.status || null,
    createdAt: thread.createdAt || null,
    updatedAt: thread.updatedAt || null,
    path: thread.path || null
  };
}

function textFromUserInput(input) {
  if (!input) return "";
  if (typeof input === "string") return input;
  if (input.type === "text") return input.text || "";
  return "";
}

function messagesFromThreadItems(items = [], turnId = null) {
  const messages = [];
  for (const item of items || []) {
    if (item?.type === "userMessage") {
      const text = (item.content || []).map(textFromUserInput).filter(Boolean).join("\n").trim();
      if (text) messages.push({ role: "user", text, turnId, itemId: item.id || null });
    } else if (item?.type === "agentMessage") {
      const text = String(item.text || "").trim();
      if (text) messages.push({ role: "assistant", text, turnId, itemId: item.id || null });
    }
  }
  return messages;
}

async function listThreadMessages(threadId) {
  const turns = await codexAppServer.listThreadTurns({ threadId, limit: 40 });
  const messages = [];
  for (const turn of turns?.data || []) {
    const turnId = turn.id || turn.turnId || null;
    let items = Array.isArray(turn.items) ? turn.items : [];
    if (!items.length && turnId) {
      try {
        const itemPage = await codexAppServer.listThreadTurnItems({ threadId, turnId, limit: 120 });
        items = itemPage?.data || [];
      } catch {
        items = [];
      }
    }
    messages.push(...messagesFromThreadItems(items, turnId));
  }
  return messages;
}

function appServerStatusSnapshot(threadId) {
  return appServerThreadStatus.get(threadId) || {
    threadId,
    status: "idle",
    turnId: null,
    summary: "Idle",
    updatedAt: null
  };
}

function approvalDecisionFor(action, approval) {
  const available = approval?.availableDecisions || [];
  if (action === "approve") {
    if (available.includes("accept")) return "accept";
    return available.find((item) => String(item).startsWith("accept")) || "accept";
  }
  if (action === "cancel") {
    return available.includes("cancel") ? "cancel" : "cancel";
  }
  return available.includes("decline") ? "decline" : "decline";
}

function addRunEvent(run, event, data) {
  const item = { event, data: { ...data, at: new Date().toISOString() } };
  run.events.push(item);
  for (const client of run.clients) {
    sendSse(client, item.event, item.data);
  }
}

function startCodexRun({ title, prompt, sandbox = "workspace-write" }) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  const run = {
    id,
    title,
    prompt,
    status: "running",
    startedAt: new Date().toISOString(),
    finishedAt: null,
    events: [],
    clients: new Set(),
    child: null,
    stdoutBuffer: "",
    stderrBuffer: ""
  };
  runs.set(id, run);

  const args = [
    "exec",
    "--json",
    "--model",
    codexModel,
    "--sandbox",
    sandbox,
    "--cd",
    workspaceRoot,
    prompt
  ];

  const child = spawn("codex", args, {
    cwd: workspaceRoot,
    env: childEnv,
    stdio: ["ignore", "pipe", "pipe"]
  });
  run.child = child;

  addRunEvent(run, "meta", {
    message: `Started: ${title}`,
    command: `codex ${args.slice(0, -1).join(" ")} <prompt>`
  });

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    run.stdoutBuffer += chunk;
    let index;
    while ((index = run.stdoutBuffer.indexOf("\n")) >= 0) {
      const line = run.stdoutBuffer.slice(0, index).trim();
      run.stdoutBuffer = run.stdoutBuffer.slice(index + 1);
      if (!line) continue;
      try {
        const parsed = JSON.parse(line);
        addRunEvent(run, "codex", { raw: parsed, summary: summarizeCodexEvent(parsed) });
      } catch {
        addRunEvent(run, "log", { stream: "stdout", message: line });
      }
    }
  });

  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    run.stderrBuffer += chunk;
    let index;
    while ((index = run.stderrBuffer.indexOf("\n")) >= 0) {
      const line = run.stderrBuffer.slice(0, index).trim();
      run.stderrBuffer = run.stderrBuffer.slice(index + 1);
      if (line) addRunEvent(run, "log", { stream: "stderr", message: line });
    }
  });

  child.on("error", (error) => {
    run.status = "failed";
    run.finishedAt = new Date().toISOString();
    addRunEvent(run, "log", { stream: "stderr", message: error.message });
    addRunEvent(run, "done", { status: run.status, error: error.message });
  });

  child.on("close", (code, signal) => {
    if (run.stdoutBuffer.trim()) {
      addRunEvent(run, "log", { stream: "stdout", message: run.stdoutBuffer.trim() });
    }
    if (run.stderrBuffer.trim()) {
      addRunEvent(run, "log", { stream: "stderr", message: run.stderrBuffer.trim() });
    }
    run.status = code === 0 ? "complete" : "failed";
    run.finishedAt = new Date().toISOString();
    run.child = null;
    addRunEvent(run, "done", { status: run.status, code, signal });
  });

  return run;
}

function summarizeCodexEvent(event) {
  const type = event.type || event.event || "event";
  const message =
    event.message ||
    event.text ||
    event.delta ||
    event.item?.text ||
    event.item?.content?.[0]?.text ||
    event.output ||
    event.status ||
    "";
  return { type, message: typeof message === "string" ? message : JSON.stringify(message) };
}

function slugifyTopic(value) {
  const slug = value
    .normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
  return slug || "literature-review";
}

function defaultVaultName(topic) {
  return `${slugifyTopic(topic)}_survay`;
}

function vaultArgForSelectedDirectory(topic, workspaceDirectory) {
  const directory = workspaceDirectory?.trim();
  if (!directory) return "";
  const resolvedDirectory = path.resolve(directory);
  const vaultPath = path.join(resolvedDirectory, defaultVaultName(topic));
  const relative = path.relative(workspaceRoot, vaultPath);
  if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) return relative;
  return vaultPath;
}

async function chooseDirectoryWithDialog() {
  const script = 'POSIX path of (choose folder with prompt "选择新课题目录")';
  const result = await execFileText("osascript", ["-e", script], { cwd: workspaceRoot });
  if (!result.ok) {
    const message = result.stderr || result.error || "";
    if (/User canceled/i.test(message)) return { cancelled: true };
    return { error: message || "Directory selection failed", status: 500 };
  }
  const selectedPath = result.stdout.trim().replace(/\/$/, "");
  return selectedPath ? { path: selectedPath } : { cancelled: true };
}

async function initTopic(topic, workspaceDirectory = "") {
  const args = [dlwScript, "init", "--topic", topic];
  const vault = vaultArgForSelectedDirectory(topic, workspaceDirectory);
  if (vault) args.push("--vault", vault);
  const result = await execFileText("python3", args, {
    cwd: workspaceRoot
  });
  if (!result.ok) {
    throw new Error(result.stderr || result.error || "Failed to initialize topic");
  }
  return JSON.parse(result.stdout);
}

function selectedTopicContext(selectedTopic, topic, options = {}) {
  const topicName = selectedTopic?.topic || topic || "current selected topic";
  const vault = selectedTopic?.vault || "current selected vault";
  const workspaceDirectory = options.workspaceDirectory || selectedTopic?.workspaceDirectory || "";
  const directoryText = workspaceDirectory
    ? `\n用户选择的新课题父目录：${workspaceDirectory}\n若本次是新建课题，请在该目录下创建/使用本课题 vault，不要覆盖父目录本身。`
    : "";
  return `当前 UI 选中课题：${topicName}
当前 UI 选中 vault：${vault}
${directoryText}

本次运行必须以 UI 选中的课题和 vault 为准。若 AGENTS.md、PROJECT_STATE.md、旧 handoff 或历史对话提到其他课题，不要切换课题。`;
}

function prompts(action, topic, selectedTopic, options = {}) {
  const common = "按 Deep Literature Workflow 插件自己的规则执行，不要使用 App 自定义的阶段写作模板。";
  const selectedContext = selectedTopicContext(selectedTopic, topic, options);
  const directoryInstruction = options.workspaceDirectory
    ? `\n新课题保存目录（父目录）：${options.workspaceDirectory}\n如果需要调用 dlw.py init，请让 --vault 指向该父目录下的新课题 vault 文件夹，而不是父目录本身。`
    : "";
  return {
    start: `${common}\n${selectedContext}${directoryInstruction}\n新建文献调研课题：${topic}\n然后按 deep-literature-workflow 插件原本流程继续，直到 Stage 3 前停止，等待用户确认。`,
    resume: `${common}\n${selectedContext}\n继续当前选中课题。若下一步是 Stage 3，停止并等待用户确认，不要开始 PDF 获取。`,
    stage3: `${common}\n${selectedContext}\n继续当前选中课题的 Stage 3。`,
    importManual: `${common}\n${selectedContext}\n导入当前选中课题中手动下载的 PDF。`
  };
}

function dlwPluginInput(text) {
  return [{ ...dlwPluginMention }, { type: "text", text }];
}

function findDeepLiteratureSkill(skillsResult) {
  const entries = skillsResult?.data || [];
  for (const entry of entries) {
    const skill = (entry.skills || []).find((item) =>
      item.name === "deep-literature-workflow:deep-literature-workflow" ||
      item.name === "deep-literature-workflow"
    );
    if (skill) return { cwd: entry.cwd || null, skill };
  }
  return null;
}

function pluginMentionProbeInput(variant) {
  const probeText =
    "Plugin Mention Spike。不要修改文件，不要运行 workflow 命令。请只回复一行：DLW_PLUGIN_MENTION_PROBE_OK。";
  if (variant === "markdown") {
    return [
      {
        type: "text",
        text: `[@deep-literature-workflow](plugin://deep-literature-workflow@deep-research-local)\n\n${probeText}`
      }
    ];
  }
  return dlwPluginInput(probeText);
}

async function handleApi(req, res, url) {
  if (req.method === "GET" && url.pathname === "/api/status") {
    const status = await getStatus();
    const selected = buildSelectedTopic(status.state, status.topics, url.searchParams.get("vault"));
    return json(res, 200, {
      ...status,
      selectedTopic: selected
    });
  }

  if (req.method === "POST" && url.pathname === "/api/directories/choose") {
    const result = await chooseDirectoryWithDialog();
    if (result.error) return json(res, result.status || 500, { error: result.error });
    return json(res, 200, result);
  }

  if (req.method === "GET" && url.pathname === "/api/vault/files") {
    const vault = url.searchParams.get("vault");
    const root = safeVaultRoot(vault);
    if (!root) return forbidden(res, "Invalid vault path");
    try {
      const files = await listMarkdownFiles(root);
      return json(res, 200, { vault, files });
    } catch (error) {
      return json(res, 500, { error: error.message || String(error) });
    }
  }

  if (req.method === "GET" && url.pathname === "/api/vault/file") {
    const result = await readVaultMarkdown(
      url.searchParams.get("vault"),
      url.searchParams.get("path")
    );
    if (result.error) return json(res, result.status || 500, { error: result.error });
    return json(res, 200, result);
  }

  if (req.method === "GET" && url.pathname === "/api/appserver/threads") {
    try {
      const result = await codexAppServer.listThreads({ limit: Number(url.searchParams.get("limit") || 20) });
      const threads = (result?.data || []).map((thread) => {
        const normalized = normalizeThread(thread);
        return { ...normalized, appStatus: appServerStatusSnapshot(normalized.id) };
      });
      return json(res, 200, {
        ok: true,
        threads,
        cursor: result?.cursor || null
      });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "GET" && url.pathname === "/api/appserver/events") {
    res.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive"
    });
    for (const item of appServerEvents) sendSse(res, item.event, item.data);
    appServerClients.add(res);
    req.on("close", () => appServerClients.delete(res));
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/appserver/approvals") {
    return json(res, 200, { ok: true, approvals: [...appServerApprovalRequests.values()] });
  }

  if (req.method === "GET" && url.pathname === "/api/appserver/skills") {
    try {
      const result = await codexAppServer.listSkills({ cwd: workspaceRoot });
      const deepLiterature = findDeepLiteratureSkill(result);
      return json(res, 200, { ok: true, deepLiterature, raw: result });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (
    req.method === "POST" &&
    (url.pathname === "/api/appserver/plugin-mention-probe" ||
      url.pathname === "/api/appserver/skill-mention-probe")
  ) {
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    const variant = body.variant === "markdown" ? "markdown" : "structured";
    const model = normalizeModel(body.model);
    const effort = normalizeReasoningEffort(body.effort || "low");
    try {
      const skillsResult = await codexAppServer.listSkills({ cwd: workspaceRoot });
      const deepLiterature = findDeepLiteratureSkill(skillsResult);
      const name = `DLW Plugin Mention Probe: ${variant}`;
      const threadResult = await codexAppServer.startThread({
        name,
        model,
        sandbox: "read-only"
      });
      const thread = normalizeThread(threadResult?.thread);
      if (!thread.name) thread.name = name;
      addAppServerEvent("appserver", {
        method: "thread/create/local",
        summary: `Created skill probe thread: ${thread.name || thread.id}`,
        thread
      });
      const input = pluginMentionProbeInput(variant);
      const turnResult = await codexAppServer.sendInputToThread({
        threadId: thread.id,
        input,
        model,
        effort,
        sandbox: "read-only"
      });
      const status = updateAppServerThreadStatus(thread.id, {
        status: "running",
        turnId: turnResult?.turn?.id || null,
        summary: `Plugin mention probe (${variant})`
      });
      addAppServerEvent("appserver", {
        method: "pluginMention/probe/start",
        summary: `Plugin mention probe started (${variant})`,
        variant,
        deepLiterature,
        threadId: thread.id,
        turnId: turnResult?.turn?.id || null,
        input,
        status
      });
      return json(res, 200, {
        ok: true,
        variant,
        deepLiterature,
        thread,
        turn: turnResult?.turn || null,
        input,
        status,
        raw: turnResult
      });
    } catch (error) {
      addAppServerEvent("appserver", {
        method: "pluginMention/probe/error",
        summary: error.message || String(error),
        variant
      });
      return json(res, 500, { ok: false, variant, error: error.message || String(error) });
    }
  }

  const appServerApprovalMatch = url.pathname.match(/^\/api\/appserver\/approvals\/([^/]+)\/respond$/);
  if (req.method === "POST" && appServerApprovalMatch) {
    const requestId = decodeURIComponent(appServerApprovalMatch[1]);
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    const approval = appServerApprovalRequests.get(requestId);
    if (!approval) return badRequest(res, "Approval request not found or already resolved.");
    const decision = approvalDecisionFor(body.action || body.decision || "decline", approval);
    try {
      await codexAppServer.respondToServerRequest(approval.rawRequestId ?? approval.requestId, { decision });
      appServerApprovalRequests.delete(requestId);
      updateAppServerThreadStatus(approval.threadId, {
        status: decision === "accept" ? "running" : "interrupted",
        turnId: approval.turnId,
        summary: `Approval ${decision}`,
        pendingApprovalRequestId: null
      });
      addAppServerEvent("appserver", {
        method: "serverRequest/resolved/local",
        requestId,
        approval,
        decision,
        summary: `Approval ${decision}: ${approval.summary}`
      });
      return json(res, 200, { ok: true, requestId, decision });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/appserver/threads") {
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    try {
      const selectedTopic = body.selectedTopic || null;
      const name =
        body.name?.trim() ||
        `DLW: ${selectedTopic?.topic || "Literature Workflow"}`;
      const result = await codexAppServer.startThread({
        name,
        model: normalizeModel(body.model),
        sandbox: body.mode === "read" ? "read-only" : "workspace-write"
      });
      const thread = normalizeThread(result?.thread);
      if (!thread.name) thread.name = name;
      addAppServerEvent("appserver", {
        method: "thread/create/local",
        summary: `Created thread: ${thread.name || thread.id}`,
        thread
      });
      return json(res, 200, { ok: true, thread, raw: result });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  const appServerStatusMatch = url.pathname.match(/^\/api\/appserver\/threads\/([^/]+)\/status$/);
  if (req.method === "GET" && appServerStatusMatch) {
    const threadId = decodeURIComponent(appServerStatusMatch[1]);
    return json(res, 200, { ok: true, status: appServerStatusSnapshot(threadId) });
  }

  const appServerMessagesMatch = url.pathname.match(/^\/api\/appserver\/threads\/([^/]+)\/messages$/);
  if (req.method === "GET" && appServerMessagesMatch) {
    const threadId = decodeURIComponent(appServerMessagesMatch[1]);
    try {
      const messages = await listThreadMessages(threadId);
      return json(res, 200, { ok: true, threadId, messages });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  const appServerSendMatch = url.pathname.match(/^\/api\/appserver\/threads\/([^/]+)\/send$/);
  if (req.method === "POST" && appServerSendMatch) {
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    const threadId = decodeURIComponent(appServerSendMatch[1]);
    try {
      const result = await codexAppServer.sendToThread({
        threadId,
        text: body.message || "",
        model: normalizeModel(body.model),
        effort: normalizeReasoningEffort(body.effort),
        sandbox: body.mode === "write" ? "workspace-write" : "read-only"
      });
      const status = updateAppServerThreadStatus(threadId, {
        status: "running",
        turnId: result?.turn?.id || null,
        summary: `Running turn ${result?.turn?.id || ""}`.trim()
      });
      addAppServerEvent("appserver", {
        method: "turn/start/local",
        summary: `Sent message to thread: ${threadId}`,
        threadId,
        turnId: result?.turn?.id || null,
        userMessage: body.message || "",
        status
      });
      return json(res, 200, { ok: true, turn: result?.turn || null, status, raw: result });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  const appServerDlwActionMatch = url.pathname.match(/^\/api\/appserver\/threads\/([^/]+)\/dlw-action$/);
  if (req.method === "POST" && appServerDlwActionMatch) {
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    const threadId = decodeURIComponent(appServerDlwActionMatch[1]);
    const action = body.action;
    const topic = body.topic?.trim();
    const workspaceDirectory = body.workspaceDirectory?.trim() || "";
    if (action === "start" && !topic) return badRequest(res, "Research topic is required.");
    const promptSet = prompts(action, topic, body.selectedTopic || null, { workspaceDirectory });
    const prompt = promptSet[action];
    if (!prompt) return badRequest(res, `Unknown DLW action: ${action}`);
    const input = dlwPluginInput(prompt);
    try {
      const result = await codexAppServer.sendInputToThread({
        threadId,
        input,
        model: normalizeModel(body.model),
        effort: normalizeReasoningEffort(body.effort),
        sandbox: body.mode === "read" ? "read-only" : "workspace-write"
      });
      const status = updateAppServerThreadStatus(threadId, {
        status: "running",
        turnId: result?.turn?.id || null,
        summary: `DLW ${action} ${result?.turn?.id || ""}`.trim()
      });
      addAppServerEvent("appserver", {
        method: "dlwAction/start",
        summary: `Started DLW action: ${action}`,
        action,
        threadId,
        turnId: result?.turn?.id || null,
        userMessage: prompt,
        input,
        status
      });
      return json(res, 200, { ok: true, action, prompt, input, turn: result?.turn || null, status, raw: result });
    } catch (error) {
      return json(res, 500, { ok: false, action, error: error.message || String(error) });
    }
  }

  const appServerInterruptMatch = url.pathname.match(/^\/api\/appserver\/threads\/([^/]+)\/interrupt$/);
  if (req.method === "POST" && appServerInterruptMatch) {
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    const threadId = decodeURIComponent(appServerInterruptMatch[1]);
    const currentStatus = appServerStatusSnapshot(threadId);
    const turnId = body.turnId || currentStatus.turnId;
    if (!turnId) return badRequest(res, "No running turn is known for this thread.");
    try {
      updateAppServerThreadStatus(threadId, {
        status: "stopping",
        turnId,
        summary: `Stopping turn ${turnId}`
      });
      const result = await codexAppServer.interruptTurn({ threadId, turnId });
      const status = updateAppServerThreadStatus(threadId, {
        status: "interrupted",
        turnId,
        summary: `Interrupted turn ${turnId}`
      });
      addAppServerEvent("appserver", {
        method: "turn/interrupt/local",
        summary: `Interrupted turn: ${turnId}`,
        threadId,
        turnId,
        status
      });
      return json(res, 200, { ok: true, status, raw: result });
    } catch (error) {
      const status = updateAppServerThreadStatus(threadId, {
        status: "interrupt_failed",
        turnId,
        summary: error.message || String(error)
      });
      return json(res, 500, { ok: false, status, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/stage3/downloads/cancel") {
    const result = await cancelStage3DownloadProcesses();
    addAppServerEvent("appserver", {
      method: "stage3/downloads/cancel",
      summary: `Cancelled ${result.count} Stage 3 downloader process(es).`,
      killed: result.killed.map((item) => ({ pid: item.pid, command: item.command })),
      failed: result.failed
    });
    return json(res, 200, { ok: true, ...result });
  }

  if (req.method === "POST" && url.pathname === "/api/runs") {
    const body = JSON.parse((await readRequestBody(req)) || "{}");
    const action = body.action;
    let topic = body.topic?.trim();
    const customPrompt = body.prompt?.trim();
    const mode = body.mode === "write" ? "write" : "read";
    const workspaceDirectory = body.workspaceDirectory?.trim() || "";

    if (action === "start") {
      if (!topic) return badRequest(res, "Research topic is required.");
      await initTopic(topic, workspaceDirectory);
    }

    const selectedTopic = body.selectedTopic;
    const promptSet = prompts(action, topic, selectedTopic, { workspaceDirectory });
    const prompt =
      action === "custom"
        ? buildCustomPrompt(customPrompt, body.selectedTopic)
        : promptSet[action];
    if (!prompt) return badRequest(res, `Unknown action: ${action}`);

    const titles = {
      start: "Start Topic: Stage 1-2",
      resume: "Resume Automatic Workflow",
      stage3: "Confirm and Run Stage 3",
      importManual: "Import Manual PDFs",
      custom: mode === "write" ? "Codex Instruction: Write" : "Codex Instruction: Read-only"
    };
    const sandbox = action === "custom" && mode === "read"
      ? "read-only"
      : "workspace-write";
    const run = startCodexRun({ title: titles[action] || action, prompt, sandbox });
    return json(res, 200, { id: run.id, status: run.status, title: run.title });
  }

  const runEventsMatch = url.pathname.match(/^\/api\/runs\/([^/]+)\/events$/);
  if (req.method === "GET" && runEventsMatch) {
    const run = runs.get(runEventsMatch[1]);
    if (!run) return notFound(res);
    res.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive"
    });
    for (const item of run.events) sendSse(res, item.event, item.data);
    run.clients.add(res);
    req.on("close", () => run.clients.delete(res));
    return;
  }

  const cancelMatch = url.pathname.match(/^\/api\/runs\/([^/]+)\/cancel$/);
  if (req.method === "POST" && cancelMatch) {
    const run = runs.get(cancelMatch[1]);
    if (!run) return notFound(res);
    if (run.child) {
      run.child.kill("SIGTERM");
      addRunEvent(run, "meta", { message: "Cancellation requested." });
    }
    let stage3Downloads = null;
    if (runLooksLikeStage3(run)) {
      stage3Downloads = await cancelStage3DownloadProcesses();
      addRunEvent(run, "meta", {
        message: `Stage 3 downloader cleanup killed ${stage3Downloads.count} process(es).`,
        killed: stage3Downloads.killed.map((item) => item.pid),
        failed: stage3Downloads.failed
      });
    }
    return json(res, 200, { ok: true, stage3Downloads });
  }

  return notFound(res);
}

function buildCustomPrompt(userPrompt, selectedTopic) {
  if (!userPrompt) return null;
  const context = selectedTopicContext(selectedTopic);
  return `Use the deep-literature-workflow plugin when relevant.
Follow AGENTS.md and the plugin rules.
${context}
Do not use unauthorized PDF sources.
Do not inspect browser credentials, cookies, passwords, or session stores.

Interpret the user instruction as referring to the selected topic and vault unless it explicitly says otherwise.
If the instruction mentions "5A", "concept", "concept notes", "原来的结构", "这个结构", or "模板", treat it as referring to the selected topic's Stage 5A concept-note outputs.

User instruction:
${userPrompt}`;
}

async function serveStatic(req, res, url) {
  const pathname = url.pathname === "/" ? "/index.html" : url.pathname;
  const filePath = path.normalize(path.join(publicDir, pathname));
  if (!filePath.startsWith(publicDir)) return notFound(res);
  try {
    await stat(filePath);
  } catch {
    return notFound(res);
  }
  const ext = path.extname(filePath);
  const contentTypes = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8"
  };
  res.writeHead(200, {
    "content-type": contentTypes[ext] || "application/octet-stream",
    "cache-control": "no-store"
  });
  createReadStream(filePath).pipe(res);
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname.startsWith("/api/")) {
      await handleApi(req, res, url);
    } else {
      await serveStatic(req, res, url);
    }
  } catch (error) {
    json(res, 500, { error: error.message || String(error) });
  }
});

const port = Number(process.env.PORT || process.env.CODEX_DLW_APP_PORT || 8787);
server.listen(port, "127.0.0.1", () => {
  console.log(`Codex Deep Literature App: http://127.0.0.1:${port}`);
});
