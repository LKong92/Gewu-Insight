import { spawn, execFile } from "node:child_process";
import { createServer } from "node:http";
import { copyFile, cp, mkdir, readFile, readdir, rename, stat, unlink, writeFile } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CodexAppServerClient } from "./codexAppServerClient.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "public");
const workspaceRoot = path.resolve(process.env.CODEX_DLW_WORKSPACE_ROOT || path.resolve(__dirname, ".."));
const bundledDlwPluginDir = path.resolve(__dirname, "../workspace-template/plugins/deep-literature-workflow");
const bundledCodexSkillsDir = path.resolve(__dirname, "../codex-skills");
const workspaceDlwPluginDir = path.join(workspaceRoot, "plugins/deep-literature-workflow");
const codexHome = path.resolve(process.env.CODEX_HOME || path.join(os.homedir(), ".codex"));
const codexDlwPluginCacheDir = path.join(codexHome, "plugins/cache/deep-research-local/deep-literature-workflow/0.1.0");
const codexSkillsDir = path.join(codexHome, "skills");
const codexConfigPath = path.join(codexHome, "config.toml");
const deepResearchMarketplaceName = "deep-research-local";
const deepResearchMarketplaceFile = path.join(workspaceRoot, ".agents/plugins/marketplace.json");
const dlwScript = path.join(workspaceRoot, "plugins/deep-literature-workflow/scripts/dlw.py");
const statePath = path.join(workspaceRoot, ".deep-literature-workflow/state.json");
const appPreferencesPath = path.join(workspaceRoot, ".deep-literature-workflow/app-preferences.json");
const rootProjectStatePath = path.join(workspaceRoot, "PROJECT_STATE.md");
const runs = new Map();
const appServerEvents = [];
const appServerClients = new Set();
const appServerThreadStatus = new Map();
const appServerApprovalRequests = new Map();
const codexModel = process.env.CODEX_DLW_MODEL || "gpt-5.5";
const codexSandbox = process.env.CODEX_DLW_SANDBOX || "danger-full-access";
const codexApprovalPolicy = process.env.CODEX_DLW_APPROVAL_POLICY || "never";
const codexBinary = "/Applications/Codex.app/Contents/Resources/codex";
const pythonBinary = process.env.CODEX_DLW_PYTHON || "/usr/bin/python3";
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
childEnv.PYTHONDONTWRITEBYTECODE = process.env.PYTHONDONTWRITEBYTECODE || "1";
const codexAppServer = new CodexAppServerClient({
  codexPath: codexBinary,
  cwd: workspaceRoot,
  env: childEnv,
  model: codexModel,
  sandbox: codexSandbox,
  approvalPolicy: codexApprovalPolicy
});
const allowedModels = new Set(["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"]);
const allowedReasoningEfforts = new Set(["low", "medium", "high", "xhigh"]);
const dlwPluginMention = {
  type: "mention",
  path: "plugin://deep-literature-workflow@deep-research-local",
  name: "Deep Literature Workflow"
};
const stage3DownloadProcessMarkers = [
  "chrome-literature-downloader",
  "/chrome-literature-downloader/scripts/download_literature_chrome.py",
  "/chrome-literature-downloader/scripts/batch_download_literature_chrome.py",
  "download_literature_chrome",
  "batch_download_literature_chrome",
  "download_literature_chrome.py",
  "batch_download_literature_chrome.py",
  "stage3_fetch",
  "stage3_fetch_pdfs_and_upgrade_notes.py",
  "stage2_deep_reading_queue",
  "08_stage3_pdf_inventory",
  "09_manual_pdf_download_queue"
];
const requiredCodexSkillNames = [
  "literature-downloader",
  "chrome-literature-downloader",
  "paper-broad-reading-analysis"
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

function sandboxForMode(mode) {
  return mode === "read" ? "read-only" : codexSandbox;
}

function externalUrlAllowed(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:", "mailto:"].includes(parsed.protocol);
  } catch {
    return false;
  }
}

async function openExternalUrl(url) {
  if (!externalUrlAllowed(url)) {
    return { ok: false, error: "Only http, https, and mailto links can be opened." };
  }
  const result = await execFileText("open", [url], { cwd: workspaceRoot });
  return { ok: result.ok, url, error: result.stderr.trim() || result.error };
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

function escapeHtml(value = "") {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAppleScriptString(value = "") {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
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

async function readAppPreferences() {
  const preferences = await readJsonIfExists(appPreferencesPath);
  return preferences && typeof preferences === "object" ? preferences : {};
}

async function writeAppPreferences(patch) {
  const current = await readAppPreferences();
  const next = { ...current, ...patch };
  await mkdir(path.dirname(appPreferencesPath), { recursive: true });
  await writeFile(appPreferencesPath, JSON.stringify(next, null, 2) + "\n", "utf8");
  return next;
}

async function pathExists(filePath) {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function pluginDirStatus(pluginDir) {
  const pluginJson = path.join(pluginDir, ".codex-plugin/plugin.json");
  const skillFile = path.join(pluginDir, "skills/deep-literature-workflow/SKILL.md");
  const scriptFile = path.join(pluginDir, "scripts/dlw.py");
  const [root, manifest, skill, script] = await Promise.all([
    pathExists(pluginDir),
    pathExists(pluginJson),
    pathExists(skillFile),
    pathExists(scriptFile)
  ]);
  return {
    path: pluginDir,
    ok: root && manifest && skill && script,
    root,
    manifest,
    skill,
    script
  };
}

async function skillDirStatus(skillName) {
  const skillDir = path.join(codexSkillsDir, skillName);
  const skillFile = path.join(skillDir, "SKILL.md");
  const [root, skill] = await Promise.all([
    pathExists(skillDir),
    pathExists(skillFile)
  ]);
  return {
    name: skillName,
    path: skillDir,
    ok: root && skill,
    root,
    skill
  };
}

async function pluginDirsEquivalent(sourceDir, targetDir) {
  const relativeFiles = [
    ".codex-plugin/plugin.json",
    "README.md",
    "scripts/dlw.py",
    "skills/deep-literature-workflow/SKILL.md"
  ];
  for (const relPath of relativeFiles) {
    const [source, target] = await Promise.all([
      safeReadText(path.join(sourceDir, relPath)),
      safeReadText(path.join(targetDir, relPath))
    ]);
    if (!source || source !== target) return false;
  }
  return true;
}

async function copyBundledPluginIfMissing(targetDir) {
  if (!(await pathExists(bundledDlwPluginDir))) {
    return { ok: false, installed: false, error: "Bundled Deep Literature Workflow plugin template is missing." };
  }
  const before = await pluginDirStatus(targetDir);
  if (before.ok && await pluginDirsEquivalent(bundledDlwPluginDir, targetDir)) {
    return { ok: true, installed: false, changed: false, status: before };
  }
  await mkdir(path.dirname(targetDir), { recursive: true });
  await cp(bundledDlwPluginDir, targetDir, { recursive: true, force: true, errorOnExist: false });
  const after = await pluginDirStatus(targetDir);
  return {
    ok: after.ok,
    installed: !before.ok,
    changed: before.ok,
    status: after,
    error: after.ok ? null : "Plugin copy finished, but required files are still missing."
  };
}

async function copyBundledSkillIfMissing(skillName) {
  const sourceDir = path.join(bundledCodexSkillsDir, skillName);
  if (!(await pathExists(sourceDir))) {
    return { ok: false, installed: false, name: skillName, error: `Bundled Codex skill is missing: ${skillName}` };
  }
  const before = await skillDirStatus(skillName);
  if (before.ok) return { ok: true, installed: false, status: before };
  await mkdir(codexSkillsDir, { recursive: true });
  await cp(sourceDir, before.path, { recursive: true, force: false, errorOnExist: false });
  const after = await skillDirStatus(skillName);
  return { ok: after.ok, installed: true, status: after, error: after.ok ? null : `Skill copy finished, but ${skillName}/SKILL.md is still missing.` };
}

async function ensureBundledDlwPluginInstalled() {
  const workspace = await copyBundledPluginIfMissing(workspaceDlwPluginDir);
  const cache = await copyBundledPluginIfMissing(codexDlwPluginCacheDir);
  const bundledSkills = {};
  for (const skillName of requiredCodexSkillNames) {
    bundledSkills[skillName] = await copyBundledSkillIfMissing(skillName);
  }
  const marketplace = await ensureDeepResearchMarketplace();
  const config = await ensureCodexDeepResearchPluginEnabled();
  if (workspace.installed || workspace.changed || cache.installed || cache.changed || Object.values(bundledSkills).some((item) => item.installed) || marketplace.changed || config.changed) {
    codexAppServer.stop();
  }
  return { workspace, cache, bundledSkills, marketplace, config };
}

async function ensureDeepResearchMarketplace() {
  const marketplace = {
    name: deepResearchMarketplaceName,
    interface: {
      displayName: "Deep Research Local"
    },
    plugins: [
      {
        name: "deep-literature-workflow",
        source: {
          source: "local",
          path: "./plugins/deep-literature-workflow"
        },
        policy: {
          installation: "AVAILABLE",
          authentication: "ON_INSTALL"
        },
        category: "Research"
      }
    ]
  };
  const next = `${JSON.stringify(marketplace, null, 2)}\n`;
  let current = "";
  try {
    current = await readFile(deepResearchMarketplaceFile, "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (current === next) {
    return { ok: true, changed: false, path: deepResearchMarketplaceFile };
  }
  await mkdir(path.dirname(deepResearchMarketplaceFile), { recursive: true });
  await writeFile(deepResearchMarketplaceFile, next, "utf8");
  return { ok: true, changed: true, path: deepResearchMarketplaceFile };
}

function replaceTomlSection(text, header, body) {
  const escaped = header.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const section = `${header}\n${body.trimEnd()}\n`;
  const pattern = new RegExp(`(?:^|\\n)${escaped}\\n[\\s\\S]*?(?=\\n\\[|$)`);
  if (pattern.test(text)) {
    return text.replace(pattern, (match) => `${match.startsWith("\n") ? "\n" : ""}${section.trimEnd()}`);
  }
  const prefix = text.trimEnd() ? `${text.trimEnd()}\n\n` : "";
  return `${prefix}${section}`;
}

async function ensureCodexDeepResearchPluginEnabled() {
  let current = "";
  try {
    current = await readFile(codexConfigPath, "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  let next = replaceTomlSection(
    current,
    `[marketplaces.${deepResearchMarketplaceName}]`,
    `source_type = "local"\nsource = ${JSON.stringify(workspaceRoot)}`
  );
  next = replaceTomlSection(
    next,
    `[plugins."deep-literature-workflow@${deepResearchMarketplaceName}"]`,
    "enabled = true"
  );
  if (next === current) {
    return { ok: true, changed: false, path: codexConfigPath };
  }
  await mkdir(path.dirname(codexConfigPath), { recursive: true });
  await writeFile(codexConfigPath, next.endsWith("\n") ? next : `${next}\n`, "utf8");
  return { ok: true, changed: true, path: codexConfigPath };
}

async function getSetupStatus({ install = false } = {}) {
  const installation = install ? await ensureBundledDlwPluginInstalled() : null;
  const [codexVersion, workspacePlugin, cachePlugin, bundledSkills] = await Promise.all([
    execFileText(codexBinary, ["--version"], { cwd: workspaceRoot }),
    pluginDirStatus(workspaceDlwPluginDir),
    pluginDirStatus(codexDlwPluginCacheDir),
    Promise.all(requiredCodexSkillNames.map((skillName) => skillDirStatus(skillName)))
  ]);
  let skills = { ok: false, deepLiterature: null, error: null };
  try {
    const skillsResult = await codexAppServer.listSkills({ cwd: workspaceRoot });
    skills = {
      ok: true,
      deepLiterature: findDeepLiteratureSkill(skillsResult),
      error: null
    };
  } catch (error) {
    skills = { ok: false, deepLiterature: null, error: error.message || String(error) };
  }
  return {
    ok: Boolean(codexVersion.ok && workspacePlugin.ok && cachePlugin.ok && bundledSkills.every((skill) => skill.ok) && skills.deepLiterature),
    codex: {
      ok: codexVersion.ok,
      path: codexBinary,
      version: codexVersion.stdout.trim(),
      error: codexVersion.stderr.trim() || codexVersion.error
    },
    workspacePlugin,
    codexPlugin: cachePlugin,
    bundledSkills,
    skills,
    installation,
    notes: [
      "The app auto-copies its bundled Deep Literature Workflow plugin into the Deep Survey workspace.",
      "It also tries to place a local Codex plugin cache copy so structured plugin mentions can resolve.",
      "It installs bundled Codex skills into ~/.codex/skills when they are missing.",
      "If Codex is missing, install Codex.app first, then reopen this app."
    ]
  };
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

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function runningStageForDlwAction(action, selectedTopic = null) {
  if (action === "start") return "stage_1_discovery";
  if (action === "stage3" || action === "importManual") return "stage_3_pdf_acquisition";
  return selectedTopic?.nextStage || selectedTopic?.currentStage || null;
}

function statusLooksLikeStage3(status = {}) {
  return (
    status.runningStage === "stage_3_pdf_acquisition" ||
    status.dlwAction === "stage3" ||
    status.dlwAction === "importManual"
  );
}

async function listSystemProcessTree() {
  const result = await execFileText("ps", ["-axo", "pid=,ppid=,command="], { cwd: workspaceRoot });
  if (!result.ok) return [];
  return result.stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(\d+)\s+(.+)$/);
      if (!match) return null;
      return { pid: Number(match[1]), ppid: Number(match[2]), command: match[3] };
    })
    .filter((item) => item && item.pid !== process.pid);
}

async function listStage3DownloadProcesses() {
  const processes = await listSystemProcessTree();
  const byParent = new Map();
  for (const item of processes) {
    const siblings = byParent.get(item.ppid) || [];
    siblings.push(item);
    byParent.set(item.ppid, siblings);
  }
  const selected = new Map();
  const addTree = (item, reason) => {
    if (!item || selected.has(item.pid)) return;
    selected.set(item.pid, { ...item, reason });
    for (const child of byParent.get(item.pid) || []) {
      addTree(child, reason === "matched" ? "child" : reason);
    }
  };
  for (const item of processes) {
    if (isStage3DownloadCommand(item.command)) addTree(item, "matched");
  }
  return [...selected.values()].sort((a, b) => a.pid - b.pid);
}

async function cancelStage3DownloadProcesses() {
  const processes = await listStage3DownloadProcesses();
  const killed = [];
  const forceKilled = [];
  const failed = [];
  const signalProcesses = (items, signal, target) => {
    for (const item of items) {
      try {
        process.kill(item.pid, signal);
        target.push(item);
      } catch (error) {
        if (error.code !== "ESRCH") {
          failed.push({ ...item, signal, error: error.message || String(error) });
        }
      }
    }
  };
  signalProcesses(processes, "SIGTERM", killed);
  if (processes.length) await wait(1200);
  const remaining = await listStage3DownloadProcesses();
  const remainingKilledByTerm = remaining.filter((item) => killed.some((killedItem) => killedItem.pid === item.pid));
  if (remainingKilledByTerm.length) {
    signalProcesses(remainingKilledByTerm, "SIGKILL", forceKilled);
    if (remainingKilledByTerm.length) await wait(300);
  }
  const stillRunning = await listStage3DownloadProcesses();
  return { killed, forceKilled, failed, remaining: stillRunning, count: killed.length + forceKilled.length };
}

async function processTreeForPid(rootPid) {
  if (!rootPid) return [];
  const processes = await listSystemProcessTree();
  const byParent = new Map();
  for (const item of processes) {
    const siblings = byParent.get(item.ppid) || [];
    siblings.push(item);
    byParent.set(item.ppid, siblings);
  }
  const selected = new Map();
  const addTree = (item, depth = 0) => {
    if (!item || selected.has(item.pid)) return;
    selected.set(item.pid, { ...item, depth });
    for (const child of byParent.get(item.pid) || []) addTree(child, depth + 1);
  };
  addTree(processes.find((item) => item.pid === rootPid) || { pid: rootPid, ppid: 0, command: "run process" });
  return [...selected.values()].sort((a, b) => b.depth - a.depth || b.pid - a.pid);
}

function processIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function cancelRunProcessTree(run) {
  const rootPid = run?.child?.pid;
  if (!rootPid) return { killed: [], forceKilled: [], failed: [], remaining: [], count: 0 };
  const processes = await processTreeForPid(rootPid);
  const killed = [];
  const forceKilled = [];
  const failed = [];
  const signalProcesses = (items, signal, target) => {
    for (const item of items) {
      try {
        process.kill(item.pid, signal);
        target.push(item);
      } catch (error) {
        if (error.code !== "ESRCH") {
          failed.push({ ...item, signal, error: error.message || String(error) });
        }
      }
    }
  };
  signalProcesses(processes, "SIGTERM", killed);
  if (processes.length) await wait(1200);
  const remainingAfterTerm = processes.filter((item) => processIsAlive(item.pid));
  if (remainingAfterTerm.length) {
    signalProcesses(remainingAfterTerm, "SIGKILL", forceKilled);
    await wait(300);
  }
  const remaining = processes.filter((item) => processIsAlive(item.pid));
  return { killed, forceKilled, failed, remaining, count: killed.length + forceKilled.length };
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
  const [codexVersion, nodeVersion, dlwStatus, stage3DownloadProcesses] = await Promise.all([
    execFileText("codex", ["--version"], { cwd: workspaceRoot }),
    Promise.resolve({ ok: true, stdout: process.version }),
    existsSync(dlwScript)
      ? execFileText(pythonBinary, [dlwScript, "status"], { cwd: workspaceRoot })
      : Promise.resolve({ ok: false, stdout: "", stderr: "dlw.py not found" }),
    listStage3DownloadProcesses()
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
  const [topics, appPreferences] = await Promise.all([
    readTopicIndex(workflowState),
    readAppPreferences()
  ]);
  const activeTopic = topics.find((topic) => topic.active);
  const displayWorkflowState = activeTopic
    ? {
        ...(workflowState || {}),
        topic: activeTopic.topic,
        vault_root: activeTopic.vault,
        current_stage: activeTopic.currentStage || inferNextStage(activeTopic.stageStatus || {}),
        stage_status: activeTopic.stageStatus || {},
        manual_pdf_queue: Array.from({ length: activeTopic.manualPdfCount || 0 })
      }
    : workflowState;

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
    state: displayWorkflowState,
    topics,
    topicOrder: Array.isArray(appPreferences.topicOrder) ? appPreferences.topicOrder : [],
    selectedVault: typeof appPreferences.selectedVault === "string" ? appPreferences.selectedVault : "",
    stages: stages.map(([id, label]) => {
      const rawStatus = displayWorkflowState?.stage_status?.[id] ?? "pending";
      const isActive = displayWorkflowState?.current_stage === id && rawStatus !== "done";
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
    manualPdfCount: displayWorkflowState?.manual_pdf_queue?.length ?? 0,
    stage3Downloads: {
      count: stage3DownloadProcesses.length,
      processes: stage3DownloadProcesses.map((item) => ({ pid: item.pid, command: item.command }))
    },
    nextStage: inferNextStage(displayWorkflowState?.stage_status)
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
    selected
      ? {
          topic: selected.topic,
          vault_root: selected.vault,
          current_stage: selected.currentStage,
          stage_status: selected.stageStatus || {},
          manual_pdf_queue: Array.from({ length: selected.manualPdfCount || 0 })
        }
      : activeState;
  const nextStage = inferNextStage(selectedState?.stage_status);
  return {
    topic: selected?.topic || selectedState?.topic || null,
    vault: selected?.vault || selectedState?.vault_root || null,
    active: Boolean(selected?.active),
    status: selectedState ? topicStatusSummary(selectedState) : selected?.status || null,
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
      const isActive = nextStage === id && rawStatus !== "done";
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

function stageLabel(stage) {
  if (!stage || stage === "complete") return "complete";
  return stage.replace(/_/g, " ");
}

function topicStatusSummary(state = {}) {
  const stageStatus = state.stage_status || {};
  const doneCount = stages.reduce((count, [stage]) => count + (stageStatus[stage] === "done" ? 1 : 0), 0);
  for (const [stage] of stages) {
    if (stageStatus[stage] === "blocked") return `${doneCount} stage(s) done; blocked at ${stageLabel(stage)}`;
  }
  const nextStage = inferNextStage(stageStatus);
  if (!nextStage || nextStage === "complete") return "All stages complete";
  return `${doneCount} stage(s) done; ${stageLabel(nextStage)} next`;
}

async function safeReadText(filePath) {
  try {
    return await readFile(filePath, "utf8");
  } catch {
    return "";
  }
}

async function safeReadDir(filePath) {
  try {
    return await readdir(filePath, { withFileTypes: true });
  } catch {
    return [];
  }
}

function stripMarkdownTitle(title = "") {
  return title
    .replace(/\.md$/i, "")
    .replace(/^\d+[_ -]+/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim() || "Untitled";
}

function paperNumberFromName(name = "") {
  const match = name.match(/^(\d+)/);
  return match ? Number(match[1]) : null;
}

function paperNumberPattern(number) {
  if (!Number.isFinite(number)) return null;
  return String(number).padStart(2, "0");
}

function sortPaperEntries(a, b) {
  const aNumber = paperNumberFromName(a.name);
  const bNumber = paperNumberFromName(b.name);
  const numberDiff = (aNumber ?? Number.MAX_SAFE_INTEGER) - (bNumber ?? Number.MAX_SAFE_INTEGER);
  if (numberDiff) return numberDiff;
  return a.name.localeCompare(b.name);
}

async function listPaperNotes(vaultRoot) {
  const papersDir = path.join(vaultRoot, "05_Papers");
  const entries = (await safeReadDir(papersDir))
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .sort(sortPaperEntries)
    .slice(0, 40);
  return Promise.all(
    entries.map(async (entry) => {
      const filePath = path.join(papersDir, entry.name);
      const content = await safeReadText(filePath);
      const titleMatch = content.match(/^#\s+(.+?)\s*$/m);
      return {
        name: entry.name,
        number: paperNumberFromName(entry.name),
        label: titleMatch?.[1]?.trim() || stripMarkdownTitle(entry.name),
        path: filePath,
        content
      };
    })
  );
}

async function listVaultPdfs(vaultRoot) {
  const pdfDir = path.join(vaultRoot, "06_PDFs");
  const entries = await safeReadDir(pdfDir);
  return entries
    .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".pdf"))
    .map((entry) => entry.name)
    .sort((a, b) => a.localeCompare(b));
}

function pdfExistsForPaper(note, pdfNames) {
  const number = paperNumberPattern(note.number);
  if (number && pdfNames.some((name) => name.startsWith(`${number}_`) || name.startsWith(`${number}-`) || name.startsWith(`${number} `))) {
    return true;
  }
  const normalizedTitle = stripMarkdownTitle(note.label).toLowerCase().slice(0, 26);
  return Boolean(normalizedTitle) && pdfNames.some((name) => name.toLowerCase().includes(normalizedTitle));
}

function expectedPdfNameForNote(note) {
  return note?.name ? note.name.replace(/\.md$/i, ".pdf") : "";
}

function normalizeForMatch(value = "") {
  return String(value)
    .toLowerCase()
    .replace(/10\.\d{4,9}\//g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function uniqueValues(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function normalizeDoi(value = "") {
  return String(value || "")
    .trim()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
    .replace(/^doi:\s*/i, "")
    .replace(/[)\].,;:\s]+$/g, "")
    .toLowerCase();
}

function extractDoiValues(text = "") {
  return uniqueValues((text.match(/10\.\d{4,9}\/[-._;()/:A-Z0-9]+/gi) || [])
    .map(normalizeDoi));
}

function extractUrls(text = "") {
  const urls = (text.match(/https?:\/\/[^\s<>)\]]+/gi) || [])
    .map((url) => url.replace(/[)\].,;:\s]+$/g, ""));
  return uniqueValues(urls);
}

function urlKind(url = "") {
  if (/doi\.org\/10\./i.test(url)) return "DOI";
  if (/\.pdf(\?|$)|\/pdf\b/i.test(url)) return "PDF";
  if (/openalex|semanticscholar|crossref|pubmed|arxiv/i.test(url)) return "metadata";
  return "site";
}

function linkObjectsFromText(text = "") {
  const urls = extractUrls(text).map((url) => ({ url, label: urlKind(url) }));
  for (const doi of extractDoiValues(text)) {
    const doiUrl = `https://doi.org/${doi}`;
    if (!urls.some((item) => item.url.toLowerCase() === doiUrl.toLowerCase())) {
      urls.unshift({ url: doiUrl, label: "DOI" });
    }
  }
  return urls.slice(0, 8);
}

function paperEntryFromNote(note, pdfNames = []) {
  const expectedFilename = expectedPdfNameForNote(note);
  const imported = pdfExistsForPaper(note, pdfNames);
  return {
    order: note.number || null,
    title: note.label || stripMarkdownTitle(note.name),
    expectedFilename,
    imported,
    links: linkObjectsFromText(note.content || "")
  };
}

function noteDisplayTitle(note) {
  const title = note?.label || stripMarkdownTitle(note?.name || "");
  if (/^\s*\d{1,3}\s*[.)]/.test(title)) return title;
  const order = note?.number ? String(note.number).padStart(2, "0") : "";
  return order ? `${order}. ${title}` : title;
}

function missingPdfEntry(note) {
  return {
    order: note?.number || null,
    title: noteDisplayTitle(note),
    expectedFilename: expectedPdfNameForNote(note)
  };
}

async function buildManualDownloadEntries(vaultRoot) {
  const [notes, pdfNames] = await Promise.all([listPaperNotes(vaultRoot), listVaultPdfs(vaultRoot)]);
  const entries = notes.map((note, index) => ({
    ...paperEntryFromNote(note, pdfNames),
    order: note.number || index + 1
  }));
  const queuePath = path.join(vaultRoot, "04_Evidence_Tables/09_manual_pdf_download_queue.md");
  const queueText = await safeReadText(queuePath);
  return {
    entries,
    queuePath,
    queueRelativePath: "04_Evidence_Tables/09_manual_pdf_download_queue.md",
    queueExists: Boolean(queueText),
    queueLinks: linkObjectsFromText(queueText)
  };
}

function renderManualDownloadListHtml(vaultRoot, data) {
  const pendingEntries = data.entries.filter((entry) => !entry.imported);
  const rows = pendingEntries.map((entry) => {
    const links = entry.links.length
      ? entry.links.map((link) => `<a href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer">${escapeHtml(link.label)}</a>`).join(" ")
      : `<span class="muted">No link found in note yet</span>`;
    return `<li>
      <div class="paper">
        <div class="title">${escapeHtml(entry.title)}</div>
        <div class="meta">${escapeHtml(entry.expectedFilename || "Expected PDF filename unavailable")}</div>
        <div class="links">${links}</div>
      </div>
      <div class="status">Needs PDF</div>
    </li>`;
  }).join("\n");
  const queueLinks = data.queueLinks.length
    ? `<section><h2>All Links Found In Manual Queue</h2><p>${data.queueLinks.map((link) => `<a href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer">${escapeHtml(link.url)}</a>`).join("<br>")}</p></section>`
    : "";
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Manual PDF Download List</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; color: #17202d; background: #fbfcfe; }
    h1 { margin: 0 0 6px; font-size: 24px; }
    .hint { color: #687386; margin: 0 0 22px; }
    ol { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }
    li { display: grid; grid-template-columns: minmax(0, 1fr) 96px; gap: 14px; padding: 14px 0; border-top: 1px solid #d8dee8; }
    .title { font-weight: 800; line-height: 1.35; }
    .meta, .muted { color: #687386; font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }
    .links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    a { color: #087b7c; font-weight: 700; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .status { color: #a65d12; font-weight: 800; text-align: right; }
    li.done .status { color: #218554; }
    section { margin-top: 28px; border-top: 1px dashed #d8dee8; padding-top: 18px; }
    h2 { font-size: 16px; }
  </style>
</head>
<body>
  <h1>Manual PDF Download List</h1>
  <p class="hint">${escapeHtml(vaultRoot)}<br>${pendingEntries.length} PDF(s) still need manual download. Open each legal source link, download the main article PDF, then choose the PDF files in Deep Survey.</p>
  <ol>${rows || "<li>All queued PDFs have been imported.</li>"}</ol>
  ${queueLinks}
</body>
</html>`;
}

function parsePdfInfoValue(output = "", key = "") {
  const pattern = new RegExp(`^${key}:\\s*(.*)$`, "im");
  const match = output.match(pattern);
  return match?.[1]?.trim() || "";
}

async function pdfEvidenceForPath(filePath) {
  const [info, text] = await Promise.all([
    execFileText("pdfinfo", [filePath], { cwd: workspaceRoot }),
    execFileText("pdftotext", ["-f", "1", "-l", "2", filePath, "-"], { cwd: workspaceRoot })
  ]);
  const infoText = info.ok ? info.stdout : "";
  const textSample = text.ok ? text.stdout.slice(0, 12000) : "";
  const title = parsePdfInfoValue(infoText, "Title");
  const subject = parsePdfInfoValue(infoText, "Subject");
  const keywords = parsePdfInfoValue(infoText, "Keywords");
  return {
    title,
    subject,
    keywords,
    dois: extractDoiValues([title, subject, keywords, textSample].join("\n")),
    titleHaystack: normalizeForMatch([title, subject, textSample.slice(0, 5000)].join(" "))
  };
}

function noteDoi(note) {
  return extractDoiValues(note?.content || "")[0] || "";
}

function noteTitle(note) {
  return String(note?.label || stripMarkdownTitle(note?.name || "")).replace(/^\s*\d{1,3}\s*[.)]\s*/, "");
}

function titlePrefix(value = "", tokenCount = 10) {
  return normalizeForMatch(value).split(" ").filter(Boolean).slice(0, tokenCount).join(" ");
}

function titleMatchScore(note, evidence) {
  const title = noteTitle(note);
  const normalizedTitle = normalizeForMatch(title);
  const haystack = evidence.titleHaystack || "";
  if (!normalizedTitle || !haystack) return 0;
  if (haystack.includes(normalizedTitle) || normalizedTitle.includes(normalizeForMatch(evidence.title || ""))) return 90;
  const prefix = titlePrefix(title, 10);
  if (prefix && haystack.includes(prefix)) return 84;
  const shorterPrefix = titlePrefix(title, 7);
  if (shorterPrefix && haystack.includes(shorterPrefix)) return 72;
  return 0;
}

function scorePdfEvidence(evidence, note, sourceName = "") {
  const expectedDoi = noteDoi(note);
  const pdfDois = evidence.dois || [];
  if (expectedDoi && pdfDois.length) {
    if (pdfDois.includes(expectedDoi)) return 120;
    return -100;
  }
  const titleScore = titleMatchScore(note, evidence);
  if (!titleScore) return 0;
  const noteNumber = paperNumberPattern(note.number);
  const fileNumber = paperNumberPattern(paperNumberFromName(sourceName));
  return titleScore + (noteNumber && fileNumber && noteNumber === fileNumber ? 5 : 0);
}

async function bestPdfMatch(filePath, notes) {
  const evidence = await pdfEvidenceForPath(filePath);
  const sourceName = path.basename(filePath);
  const ranked = notes
    .map((note) => ({ note, score: scorePdfEvidence(evidence, note, sourceName) }))
    .sort((a, b) => b.score - a.score);
  const best = ranked[0];
  const second = ranked[1];
  if (!best || best.score < 70 || (second && best.score - second.score < 12)) {
    return { match: null, evidence, ranked };
  }
  return { match: best, evidence, ranked };
}

async function moveFileAcrossVolumes(sourcePath, targetPath) {
  try {
    await rename(sourcePath, targetPath);
  } catch (error) {
    if (error?.code !== "EXDEV") throw error;
    await copyFile(sourcePath, targetPath);
    await unlink(sourcePath);
  }
}

async function importManualPdfPaths(vaultRoot, paths = []) {
  const sourcePaths = Array.isArray(paths)
    ? paths.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  if (!sourcePaths.length) return { ok: false, imported: [], failed: [{ error: "No PDF files were selected." }] };
  const notes = await listPaperNotes(vaultRoot);
  const pdfDir = path.join(vaultRoot, "06_PDFs");
  await mkdir(pdfDir, { recursive: true });
  const imported = [];
  const failed = [];
  for (const sourcePath of sourcePaths) {
    const filename = path.basename(sourcePath);
    try {
      const resolved = path.resolve(sourcePath);
      if (!filename.toLowerCase().endsWith(".pdf")) {
        failed.push({ filename, sourcePath, error: "Only PDF files can be imported." });
        continue;
      }
      const fileStat = await stat(resolved);
      if (!fileStat.isFile()) {
        failed.push({ filename, sourcePath, error: "Selected item is not a file." });
        continue;
      }
      const { match, evidence, ranked } = await bestPdfMatch(resolved, notes);
      if (!match) {
        const best = ranked?.[0];
        const doiText = evidence?.dois?.length ? ` DOI found: ${evidence.dois.join(", ")}.` : "";
        const bestText = best ? ` Best candidate: ${noteDisplayTitle(best.note)} (score ${best.score}).` : "";
        failed.push({ filename, sourcePath, error: `Could not confidently match this PDF by DOI/title.${doiText}${bestText}` });
        continue;
      }
      const targetName = expectedPdfNameForNote(match.note);
      const targetPath = path.join(pdfDir, targetName);
      if (await pathExists(targetPath)) {
        const existing = await bestPdfMatch(targetPath, [match.note]);
        const samePaper = Boolean(existing.match);
        failed.push({
          filename,
          sourcePath,
          match: match.note.label,
          target: targetName,
          error: samePaper
            ? "Target PDF already exists in 06_PDFs."
            : "Target filename is occupied by a PDF that does not verify against this paper."
        });
        continue;
      }
      await moveFileAcrossVolumes(resolved, targetPath);
      imported.push({ filename, sourcePath, match: match.note.label, target: targetName, score: match.score });
    } catch (error) {
      failed.push({ filename, sourcePath, error: error.message || String(error) });
    }
  }
  return { ok: imported.length > 0, imported, failed };
}

async function choosePdfFilesWithDialog(prompt = "Choose PDF files for Stage 3") {
  const safePrompt = escapeAppleScriptString(prompt);
  const script = `
set selectedFiles to choose file with prompt "${safePrompt}" of type {"com.adobe.pdf", "PDF"} with multiple selections allowed
set outputText to ""
repeat with selectedFile in selectedFiles
  set outputText to outputText & POSIX path of selectedFile & linefeed
end repeat
return outputText`;
  const result = await execFileText("osascript", ["-e", script], { cwd: workspaceRoot });
  if (!result.ok) {
    const message = result.stderr || result.error || "";
    if (/User canceled/i.test(message)) return { cancelled: true, paths: [] };
    return { error: message || "PDF selection failed", status: 500, paths: [] };
  }
  const paths = result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return paths.length ? { paths } : { cancelled: true, paths: [] };
}

async function maybeCompleteStage3AfterImport(vaultRoot) {
  const [notes, pdfNames] = await Promise.all([listPaperNotes(vaultRoot), listVaultPdfs(vaultRoot)]);
  if (!notes.length) return { complete: false, reason: "No paper notes found." };
  const missing = notes
    .filter((note) => !pdfExistsForPaper(note, pdfNames))
    .map((note) => missingPdfEntry(note));
  if (missing.length) return { complete: false, missing };
  const clear = await execFileText(pythonBinary, [
    dlwScript,
    "manual-pdf-clear",
    "--note",
    "Stage 3 complete: all manual PDFs imported."
  ], { cwd: workspaceRoot });
  const mark = await execFileText(pythonBinary, [
    dlwScript,
    "mark",
    "stage_3_pdf_acquisition",
    "done",
    "--note",
    "Stage 3 complete: all manual PDFs imported through the Deep Survey file chooser."
  ], { cwd: workspaceRoot });
  return {
    complete: mark.ok,
    mark: { ok: mark.ok, stderr: mark.stderr.trim(), error: mark.error },
    clear: { ok: clear.ok, stderr: clear.stderr.trim(), error: clear.error }
  };
}

function deepReadStatus(note) {
  const text = note.content || "";
  if (/needs_correct_main_pdf|supplementary_only|blocked/i.test(text)) {
    return { done: false, meta: "blocked" };
  }
  if (
    /read_depth:\s*(full_pdf|deep|broad)/i.test(text) ||
    /status:\s*(done|complete|deep_read)/i.test(text) ||
    /^##\s+(Deep Reading|Broad Reading|Evidence Chain|Mechanism|Key Findings)/im.test(text)
  ) {
    return { done: true, meta: "deep-read note ready" };
  }
  return { done: false, meta: "pending deep read" };
}

async function artifactDetailItems(vaultRoot, paths) {
  return Promise.all(
    paths.map(async ([label, relativePath], index) => ({
      order: index + 1,
      label,
      done: await pathExists(path.join(vaultRoot, relativePath)),
      meta: relativePath
    }))
  );
}

function progressItem(label, meta, done) {
  return {
    label,
    meta,
    done,
    showOrder: false
  };
}

async function stage2AuditExists(vaultRoot) {
  return (
    await pathExists(path.join(vaultRoot, "04_Evidence_Tables/06_stage2_screening_audit.csv")) ||
    await pathExists(path.join(vaultRoot, "04_Evidence_Tables/06_stage2_screening_audit.md"))
  );
}

async function stage2QueueExists(vaultRoot) {
  const queueExists = await pathExists(path.join(vaultRoot, "04_Evidence_Tables/07_stage2_deep_reading_queue.md"));
  if (queueExists) return true;
  const notes = await listPaperNotes(vaultRoot);
  return notes.length > 0;
}

async function numberedConceptNotesExist(vaultRoot) {
  const conceptsDir = path.join(vaultRoot, "03_Concepts");
  const entries = await safeReadDir(conceptsDir);
  return entries.some((entry) => entry.isFile() && /^0[2-9]_.*\.md$/i.test(entry.name));
}

async function buildStageDetails(selectedTopic = {}) {
  const vaultRoot = resolveVaultRoot(selectedTopic.vault);
  const stage =
    selectedTopic.nextStage ||
    selectedTopic.stages?.find((item) => item.isActive)?.id ||
    selectedTopic.stages?.find((item) => (item.rawStatus || item.status) !== "done")?.id ||
    "complete";
  if (!vaultRoot) {
    return {
      stage,
      title: "Stage Details",
      empty: "Select or import a vault to show stage details.",
      items: []
    };
  }

  if (stage === "stage_3_pdf_acquisition") {
    const data = await buildManualDownloadEntries(vaultRoot);
    const importedCount = data.entries.filter((entry) => entry.imported).length;
    const pendingCount = Math.max(data.entries.length - importedCount, 0);
    return {
      stage,
      title: "Manual PDF Download",
      empty: "",
      message: data.entries.length
        ? `${pendingCount} PDF(s) still need manual download. Open the queued literature links, download the main article PDFs, then choose the downloaded files here to move them into 06_PDFs.`
        : "Stage 3 is manual-only. After Stage 2 creates the deep-reading queue, open the download list and choose downloaded PDFs here.",
      stats: [
        { label: "Queued papers", value: data.entries.length },
        { label: "Imported PDFs", value: importedCount },
        { label: "Pending PDFs", value: pendingCount }
      ],
      actions: [
        {
          id: "openStage3DownloadList",
          label: "Open Download List",
          meta: data.queueExists
            ? "Uses 09_manual_pdf_download_queue.md plus paper-note links."
            : "Builds the list from Stage 2 paper notes."
        }
      ],
      dropZone: {
        label: "Choose PDFs",
        meta: "Select one or more PDFs in Finder. The app matches each file to the planned paper and moves it into 06_PDFs with the expected filename."
      },
      items: []
    };
  }

  if (stage === "stage_4_paper_deep_reading") {
    const [notes, pdfNames] = await Promise.all([listPaperNotes(vaultRoot), listVaultPdfs(vaultRoot)]);
    const items = notes.map((note, index) => {
      const status = deepReadStatus(note);
      const pdfMeta = pdfExistsForPaper(note, pdfNames) ? "PDF ready" : "PDF missing";
      return {
        order: note.number || index + 1,
        label: note.label,
        done: status.done,
        meta: status.done ? status.meta : `${status.meta}; ${pdfMeta}`
      };
    });
    return {
      stage,
      title: "Deep Reading Papers",
      empty: "No paper notes found yet.",
      items
    };
  }

  if (stage === "stage_1_discovery") {
    const quality = await stage1DiscoveryQuality(vaultRoot);
    return {
      stage,
      title: "Discovery",
      items: [
        progressItem(
          "Discover 200-500 candidate papers",
          quality.candidateRows
            ? `${quality.candidateRows} candidate row(s) recorded. The table should contain bibliographic metadata, abstracts when available, citation/relevance signals, recency, method centrality, and review utility scores.`
            : "No candidate rows were recorded yet. Rerun Stage 1 with available legal metadata sources before screening.",
          quality.candidateRows > 0
        ),
        progressItem(
          "Deduplicated core candidate table, ideally 40-80 papers",
          quality.coreRows
            ? `${quality.coreRows} core candidate row(s) recorded for screening.`
            : "No core candidates were recorded yet. Stage 2 should not start until this table has real candidate rows.",
          quality.coreRows > 0
        )
      ]
    };
  }

  if (stage === "stage_2_screening") {
    const auditDone = await stage2AuditExists(vaultRoot);
    const queueDone = await stage2QueueExists(vaultRoot);
    return {
      stage,
      title: "Screening",
      items: [
        progressItem(
          "Audit core candidates",
          "Review the 40-80 core candidates from Stage 1 and assign keep / background / exclude decisions.",
          auditDone
        ),
        progressItem(
          "Record exclusion and background reasons",
          "Document why broad, generic, or off-topic papers are excluded or kept only as background.",
          auditDone
        ),
        progressItem(
          "Select 15-25 deep-reading papers",
          "Choose the numbered deep-reading queue and create matching starter notes in 05_Papers with expected PDF filenames in 06_PDFs.",
          queueDone
        )
      ]
    };
  }

  if (stage === "stage_5a_concept_notes") {
    const conceptIndexDone = await pathExists(path.join(vaultRoot, "03_Concepts/01_Concept_Index.md"));
    const conceptNotesDone = await numberedConceptNotesExist(vaultRoot);
    return {
      stage,
      title: "Concept Notes",
      items: [
        progressItem(
          "Build concept index",
          "Create 03_Concepts/01_Concept_Index.md as the entry point and reading route for the concept notes.",
          conceptIndexDone
        ),
        progressItem(
          "Create numbered concept notes",
          "Write reader-ordered concept notes from Stage 4 deep-reading results, using 02_..., 03_..., etc.",
          conceptNotesDone
        ),
        progressItem(
          "Clarify concept boundaries",
          "For each concept, explain definitions, formulas, assumptions, field usage, neighboring concepts, misconceptions, and representative reading routes.",
          conceptNotesDone
        )
      ]
    };
  }

  if (stage === "stage_5b_review_synthesis") {
    const reviewDone = await pathExists(path.join(vaultRoot, "02_Review.md"));
    return {
      stage,
      title: "",
      items: [
        progressItem(
          "Write the reader-facing review",
          "Create the main domain review at 02_Review.md.",
          reviewDone
        )
      ]
    };
  }

  return {
    stage,
    title: "Workflow Complete",
    empty: "",
    items: []
  };
}

function tableCell(value = "") {
  return String(value).replace(/\|/g, "\\|").replace(/\n/g, " ").trim();
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

async function openVaultPath(vault, relativePath) {
  const root = safeVaultRoot(vault);
  if (!root) return { error: "Invalid vault path", status: 403 };
  if (!relativePath || relativePath.includes("..") || path.isAbsolute(relativePath)) {
    return { error: "Invalid file path", status: 403 };
  }
  const resolved = path.resolve(root, relativePath);
  if (!resolved.startsWith(`${root}${path.sep}`)) {
    return { error: "Path escapes vault", status: 403 };
  }
  if (!(await pathExists(resolved))) return { error: "Linked file not found", status: 404 };
  const result = await execFileText("open", [resolved], { cwd: workspaceRoot });
  return { ok: result.ok, path: resolved, error: result.stderr.trim() || result.error };
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
        const vaultRoot = resolveVaultRoot(topic.vault) || path.resolve(topic.vault);
        return {
          ...topic,
          currentStage: parseCurrentStage(handoff),
          stageStatus: await inferStageStatusFromVault(vaultRoot, handoff),
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

function cleanTopicFromFolderName(folderName = "") {
  return folderName
    .replace(/_Obsidian_Workflow$/i, "")
    .replace(/_survay$/i, "")
    .replace(/[-_]+/g, " ")
    .trim() || "Imported Topic";
}

function parseImportedTopicName(markdown = "", vaultRoot = "") {
  const managedMatch = markdown.match(/^- Topic:\s*(.+)$/m);
  if (managedMatch?.[1]?.trim()) return managedMatch[1].trim().replace(/^`|`$/g, "");
  const titleMatch = markdown.match(/^#\s+(.+?)\s*$/m);
  const projectMatch = markdown.match(/Project:\s*(?:.*?\bon\s+)?(.+?)(?:\.|\n|$)/i);
  const candidate = projectMatch?.[1] || titleMatch?.[1] || "";
  const cleaned = candidate
    .replace(/^PROJECT_STATE\.md$/i, "")
    .replace(/^Project\s+State:?/i, "")
    .replace(/\s+workflow$/i, "")
    .trim();
  if (cleaned) return cleaned;
  return cleanTopicFromFolderName(path.basename(vaultRoot));
}

async function firstExistingFile(paths) {
  for (const item of paths) {
    if (item && (await pathExists(item))) return item;
  }
  return null;
}

async function csvDataRowCount(filePath) {
  try {
    const text = await readFile(filePath, "utf8");
    const rows = text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    return Math.max(rows.length - 1, 0);
  } catch {
    return 0;
  }
}

async function stage1DiscoveryQuality(vaultRoot) {
  const candidatePaths = [
    "04_Evidence_Tables/01_stage1_candidate_papers.csv",
    "04_Evidence_Tables/03_stage1_candidates.csv"
  ].map((relPath) => path.join(vaultRoot, relPath));
  const corePaths = [
    "04_Evidence_Tables/02_stage1_core_candidates.csv",
    "04_Evidence_Tables/04_stage1_core_candidates.csv"
  ].map((relPath) => path.join(vaultRoot, relPath));
  let candidateRows = 0;
  let coreRows = 0;
  for (const filePath of candidatePaths) candidateRows = Math.max(candidateRows, await csvDataRowCount(filePath));
  for (const filePath of corePaths) coreRows = Math.max(coreRows, await csvDataRowCount(filePath));
  const hasSummary = await firstExistingFile([
    path.join(vaultRoot, "08_Project_Workflow/01_stage1_discovery_summary.md"),
    path.join(vaultRoot, "04_Evidence_Tables/05_stage1_summary.md")
  ]);
  return {
    candidateRows,
    coreRows,
    hasSummary: Boolean(hasSummary),
    done: candidateRows > 0 && coreRows > 0
  };
}

function markStagesThrough(status, stageId) {
  const next = { ...status };
  for (const [stage] of stages) {
    if (!next[stage] || next[stage] === "pending" || next[stage] === "unknown") next[stage] = "done";
    if (stage === stageId) break;
  }
  for (const [stage] of stages) {
    if (!next[stage]) next[stage] = "pending";
  }
  return next;
}

async function inferStageStatusFromVault(vaultRoot, handoffMarkdown = "") {
  const hasExplicitStageStatus = /- `(stage_[^`]+)`:\s*([A-Za-z_ -]+)/.test(handoffMarkdown);
  const fromHandoff = parseStageStatus(handoffMarkdown);
  const status = {};
  for (const [stage] of stages) status[stage] = fromHandoff[stage] || "pending";
  const stage1Quality = await stage1DiscoveryQuality(vaultRoot);

  const checks = [
    ["stage_2_screening", [
      "04_Evidence_Tables/06_stage2_summary.md",
      "04_Evidence_Tables/06_stage2_screening_audit.csv",
      "04_Evidence_Tables/07_stage2_deep_reading_queue.md"
    ]],
    ["stage_3_pdf_acquisition", [
      "04_Evidence_Tables/08_stage3_pdf_inventory.csv",
      "04_Evidence_Tables/07_stage3_summary.md"
    ]],
    ["stage_4_paper_deep_reading", [
      "04_Evidence_Tables/12_stage4_deep_reading_progress.md",
      "04_Evidence_Tables/12_claim_evidence_matrix.md"
    ]],
    ["stage_5a_concept_notes", [
      "03_Concepts/01_Concept_Index.md",
      "04_Evidence_Tables/13_stage5a_concept_notes.md"
    ]],
    ["stage_5b_review_synthesis", [
      "02_Review.md",
      "02_Review_Synthesis.md",
      "04_Evidence_Tables/14_stage5b_review.md"
    ]]
  ];

  for (const [stage, relPaths] of checks) {
    if (status[stage] === "done") continue;
    const exists = await firstExistingFile(relPaths.map((relPath) => path.join(vaultRoot, relPath)));
    if (exists) status[stage] = "done";
  }

  if (stage1Quality.done) {
    status.stage_1_discovery = "done";
  } else if (status.stage_1_discovery === "done") {
    status.stage_1_discovery = stage1Quality.candidateRows || stage1Quality.coreRows || stage1Quality.hasSummary
      ? "blocked"
      : "pending";
  }

  if (hasExplicitStageStatus) return status;
  const text = handoffMarkdown.toLowerCase();
  if (/stage\s*5b/.test(text) || /review synthesis/.test(text)) return markStagesThrough(status, "stage_5b_review_synthesis");
  if (/stage\s*5a/.test(text) || /concept notes?/.test(text)) return markStagesThrough(status, "stage_5a_concept_notes");
  if (/stage\s*4/.test(text) || /deep reading/.test(text)) return markStagesThrough(status, "stage_4_paper_deep_reading");
  if (/stage\s*3/.test(text) || /pdf acquisition|pdf import/.test(text)) return markStagesThrough(status, "stage_3_pdf_acquisition");
  if (/stage\s*2/.test(text) || /screening/.test(text)) return markStagesThrough(status, "stage_2_screening");
  if (/stage\s*1/.test(text) || /discovery/.test(text)) return markStagesThrough(status, "stage_1_discovery");
  return status;
}

async function readManualPdfQueueCount(vaultRoot, handoffMarkdown = "") {
  const handoffCount = parseManualPdfCount(handoffMarkdown);
  if (handoffCount !== null) return handoffCount;
  const queuePath = path.join(vaultRoot, "04_Evidence_Tables/09_manual_pdf_download_queue.md");
  try {
    const queue = await readFile(queuePath, "utf8");
    if (/- empty/i.test(queue)) return 0;
    const listItems = queue.split("\n").filter((line) => /^-\s+/.test(line) && !/-\s*empty/i.test(line));
    return listItems.length;
  } catch {
    return 0;
  }
}

function importedVaultReference(vaultRoot) {
  const relative = path.relative(workspaceRoot, vaultRoot);
  if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) return relative;
  return vaultRoot;
}

async function writeWorkspaceTopicIndex(activeState = {}, rowValues = []) {
  const activeTopic = activeState.topic || "No active topic";
  const activeVault = activeState.vault_root || "";
  const table = rowValues
    .map(([topic, vault, status, handoff]) =>
      `| ${tableCell(topic)} | \`${tableCell(vault)}\` | ${tableCell(status)} | \`${tableCell(handoff)}\` |`
    )
    .join("\n");

  await writeFile(
    rootProjectStatePath,
    `# PROJECT_STATE.md

## Workspace Role

- This file is a multi-topic index for the literature-review workspace.
- It should not contain a full single-topic handoff.
- Before continuing a specific topic, read the topic handoff path listed in the table below.
- Current active topic: ${activeTopic}

## Topics

| Topic | Vault | Status | Topic Handoff |
|---|---|---|---|
${table}

## Shared Rules

- Do not delete or rewrite another topic vault unless explicitly asked.
- Use legal metadata and PDF sources only; do not use Sci-Hub or unauthorized sources.
- Stage 3 is manual-download only: create linked download queues, wait for user-provided PDFs, then validate and import them.
- Do not start automatic PDF downloaders or browser download scripts unless the user explicitly asks outside the Stage 3 app workflow.
- Do not commit automatically after small edits; commit only when asked or at a meaningful milestone.

## Current Plugin State

- \`.deep-literature-workflow/state.json\` currently points to ${activeTopic}.
- If switching topics, confirm which topic is active and update/read the corresponding topic handoff.

## Current Next Step

- Continue \`${stageLabel(inferNextStage(activeState.stage_status || {}))}\` for \`${activeVault}\`.
`,
    "utf8"
  );
}

async function writeImportedWorkspaceState(state, handoffPath) {
  await mkdir(path.dirname(statePath), { recursive: true });
  await writeFile(statePath, JSON.stringify(state, null, 2) + "\n", "utf8");

  const rows = new Map();
  for (const topic of await readTopicIndex(state)) {
    if (!topic.vault) continue;
    rows.set(topic.vault, [topic.topic, topic.vault, topic.status, topic.handoff]);
  }
  const vaultRef = importedVaultReference(resolveVaultRoot(state.vault_root) || state.vault_root);
  const handoffRef = path.isAbsolute(handoffPath)
    ? importedVaultReference(handoffPath)
    : handoffPath;
  rows.set(vaultRef, [state.topic, vaultRef, topicStatusSummary(state), handoffRef]);
  const orderedRows = [...rows.values()].sort((a, b) => {
    if (a[1] === vaultRef) return -1;
    if (b[1] === vaultRef) return 1;
    return a[0].localeCompare(b[0]);
  });
  await writeWorkspaceTopicIndex(state, orderedRows);
}

async function importExistingVault(vaultPath) {
  const vaultRoot = path.resolve(vaultPath || "");
  if (!vaultRoot || !(await pathExists(vaultRoot))) {
    throw new Error("Selected vault path does not exist.");
  }
  const vaultStat = await stat(vaultRoot);
  if (!vaultStat.isDirectory()) throw new Error("Selected path is not a directory.");
  const handoffPath = await firstExistingFile([
    path.join(vaultRoot, "08_Project_Workflow/PROJECT_STATE.md"),
    path.join(vaultRoot, "09_Project_Workflow/PROJECT_STATE.md"),
    path.join(vaultRoot, "PROJECT_STATE.md")
  ]);
  const handoffMarkdown = handoffPath ? await readFile(handoffPath, "utf8") : "";
  const topic = parseImportedTopicName(handoffMarkdown, vaultRoot);
  const stageStatus = await inferStageStatusFromVault(vaultRoot, handoffMarkdown);
  const nextStage = parseCurrentStage(handoffMarkdown) || inferNextStage(stageStatus);
  const manualCount = await readManualPdfQueueCount(vaultRoot, handoffMarkdown);
  const vaultRef = importedVaultReference(vaultRoot);
  const state = {
    schema_version: 1,
    topic,
    slug: slugifyTopic(topic),
    vault_root: vaultRef,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    current_stage: nextStage === "complete" ? inferNextStage(stageStatus) : nextStage,
    stage_status: stageStatus,
    manual_pdf_queue: Array.from({ length: manualCount }, (_, index) => ({
      title: `Manual PDF ${index + 1}`,
      status: "needed"
    })),
    notes: [
      "Imported existing vault into Deep Survey. Vault files were not modified."
    ]
  };
  const topicHandoff = handoffPath || path.join(vaultRoot, "08_Project_Workflow/PROJECT_STATE.md");
  await writeImportedWorkspaceState(state, topicHandoff);
  return { ok: true, topic: buildSelectedTopic(state, await readTopicIndex(state), vaultRef), state, handoff: topicHandoff };
}

async function switchStateToTopicRow(row) {
  if (!row) {
    await writeFile(statePath, "{}\n", "utf8");
    return {};
  }
  const [, vault, , handoff] = row;
  const vaultRoot = resolveVaultRoot(vault);
  const handoffPath = path.isAbsolute(handoff) ? handoff : path.join(workspaceRoot, handoff);
  const handoffMarkdown = await readFile(handoffPath, "utf8").catch(() => "");
  const topic = row[0] || parseImportedTopicName(handoffMarkdown, vaultRoot || vault);
  const stageStatus = await inferStageStatusFromVault(vaultRoot || path.resolve(vault), handoffMarkdown);
  const manualCount = vaultRoot ? await readManualPdfQueueCount(vaultRoot, handoffMarkdown) : 0;
  const nextStage = parseCurrentStage(handoffMarkdown) || inferNextStage(stageStatus);
  const nextState = {
    schema_version: 1,
    topic,
    slug: slugifyTopic(topic),
    vault_root: vault,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    current_stage: nextStage === "complete" ? inferNextStage(stageStatus) : nextStage,
    stage_status: stageStatus,
    manual_pdf_queue: Array.from({ length: manualCount }, (_, index) => ({
      title: `Manual PDF ${index + 1}`,
      status: "needed"
    })),
    notes: ["Selected from Deep Survey topic index."]
  };
  await mkdir(path.dirname(statePath), { recursive: true });
  await writeFile(statePath, JSON.stringify(nextState, null, 2) + "\n", "utf8");
  return nextState;
}

async function activateSelectedTopicState(selectedTopic) {
  const selectedVault = typeof selectedTopic?.vault === "string" ? selectedTopic.vault.trim() : "";
  if (!selectedVault) return selectedTopic;
  const workflowState = await readJsonIfExists(statePath);
  const topics = await readTopicIndex(workflowState);
  const row = topics.find((topic) => topic.vault === selectedVault);
  if (!row) {
    throw new Error(`Selected topic vault is not in the Deep Survey index: ${selectedVault}`);
  }
  const nextState = await switchStateToTopicRow([row.topic, row.vault, row.status, row.handoff]);
  const nextTopics = await readTopicIndex(nextState);
  return buildSelectedTopic(nextState, nextTopics, selectedVault);
}

async function renameTopicInIndex(vault, nextTopic) {
  const workflowState = await readJsonIfExists(statePath);
  const topics = await readTopicIndex(workflowState);
  const rowValues = topics.map((topic) => [
    topic.vault === vault ? nextTopic : topic.topic,
    topic.vault,
    topic.status,
    topic.handoff
  ]);
  if (!rowValues.some((row) => row[1] === vault)) throw new Error("Topic vault was not found in the app index.");
  const activeState = workflowState?.vault_root === vault
    ? { ...workflowState, topic: nextTopic, updated_at: new Date().toISOString() }
    : workflowState || {};
  if (workflowState?.vault_root === vault) {
    await writeFile(statePath, JSON.stringify(activeState, null, 2) + "\n", "utf8");
  }
  await writeWorkspaceTopicIndex(activeState, rowValues);
  return { ok: true, topic: nextTopic, vault };
}

async function removeTopicFromIndex(vault) {
  const workflowState = await readJsonIfExists(statePath);
  const topics = await readTopicIndex(workflowState);
  const remaining = topics
    .filter((topic) => topic.vault !== vault)
    .map((topic) => [topic.topic, topic.vault, topic.status, topic.handoff]);
  if (remaining.length === topics.length) throw new Error("Topic vault was not found in the app index.");
  const activeState = workflowState?.vault_root === vault
    ? await switchStateToTopicRow(remaining[0] || null)
    : workflowState || {};
  await writeWorkspaceTopicIndex(activeState, remaining);
  return { ok: true, vault, removed: true, nextActiveTopic: activeState.topic || null };
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
  if (method === "error" || method === "warning") {
    return appServerDiagnosticSummary(params, method);
  }
  if (method === "turn/started") return `Turn started: ${params.turn?.id || ""}`;
  if (method === "turn/completed") return `Turn completed: ${params.turn?.status?.type || params.turn?.status || ""}`;
  if (method === "thread/started") return `Thread started: ${params.thread?.id || ""}`;
  if (method === "thread/status/changed") return `Thread status changed: ${params.status?.type || ""}`;
  if (method === "item/completed") return `Item completed: ${params.item?.type || params.item?.kind || ""}`;
  return method;
}

function appServerDiagnosticSummary(params = {}, fallback = "event") {
  const candidates = [
    params.message,
    params.error?.message,
    params.error,
    params.warning?.message,
    params.warning,
    params.reason,
    params.detail,
    params.details,
    params.status?.message
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  try {
    const text = JSON.stringify(params);
    if (text && text !== "{}") return text;
  } catch {
    // Fall through to the generic label.
  }
  return fallback;
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
      runningStage: null,
      dlwAction: null,
      summary: `Turn completed ${turnId || ""}`.trim()
    });
  } else if (method === "thread/status/changed") {
    const statusType = params.status?.type;
    const status = statusType === "active" ? "running" : statusType;
    if (!params.status?.activeFlags?.includes("waitingOnApproval") && ["idle", "completed", "interrupted", "failed"].includes(params.status?.type)) {
      clearAppServerApprovalRequestsForThread(threadId, turnId);
    }
    updateAppServerThreadStatus(threadId, {
      ...(status ? { status } : {}),
      threadStatus: params.status,
      ...(params.status?.type && ["idle", "completed", "interrupted", "failed"].includes(params.status.type)
        ? { runningStage: null, dlwAction: null }
        : {}),
      summary: `Thread status: ${params.status?.type || params.status || "changed"}`
    });
  } else if (threadId && (String(method).startsWith("item/") || method === "error" || method === "warning")) {
    const previous = appServerThreadStatus.get(threadId) || {};
    const previousStatus = previous.status || "";
    updateAppServerThreadStatus(threadId, {
      status: ["running", "waiting_approval", "stopping"].includes(previousStatus) ? previousStatus : "running",
      turnId: turnId || previous.turnId || null,
      summary: summarizeAppServerNotification(message) || previous.summary || "Running"
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
    cancelRequested: false,
    stdoutBuffer: "",
    stderrBuffer: ""
  };
  runs.set(id, run);

  const args = [
    "exec",
    "--json",
    "--model",
    codexModel
  ];
  if (codexApprovalPolicy === "never" && sandbox === codexSandbox) {
    args.push("--dangerously-bypass-approvals-and-sandbox");
  } else {
    args.push("--sandbox", sandbox);
  }
  args.push("--cd", workspaceRoot, prompt);

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
    run.status = run.cancelRequested ? "cancelled" : code === 0 ? "complete" : "failed";
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

async function chooseDirectoryWithDialog(prompt = "Choose a Deep Survey folder") {
  const safePrompt = prompt.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const script = `POSIX path of (choose folder with prompt "${safePrompt}")`;
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
  const result = await execFileText(pythonBinary, args, {
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
    start: `${common}\n${selectedContext}${directoryInstruction}\n新建文献调研课题：${topic}\n然后按 deep-literature-workflow 插件原本流程继续，完成 Stage 2 后停在 Stage 3，不要开始任何自动 PDF 下载。Stage 2 必须为 Stage 3 准备带完整 DOI/landing/OA/PDF 候选链接的手动下载列表。`,
    resume: `${common}\n${selectedContext}\n继续当前选中课题。若下一步是 Stage 3，停止在手动 PDF 下载/导入阶段，不要开始任何自动 PDF 下载或 Chrome downloader。`,
    stage3: `${common}\n${selectedContext}\n继续当前选中课题的 Stage 3：只检查手动下载列表和已导入 PDF，不要启动自动下载；如果 PDF 缺失，提示用户用 App 的下载列表按钮和 Choose PDFs 区导入。`,
    importManual: `${common}\n${selectedContext}\n导入当前选中课题中用户手动下载并放入本地的 PDF；不要启动自动 PDF 下载。`
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

async function handleApi(req, res, url) {
  if (req.method === "GET" && url.pathname === "/api/status") {
    const status = await getStatus();
    const requestedVault = url.searchParams.get("vault");
    const orderedFallbackVault = (status.topicOrder || []).find((vault) => status.topics.some((topic) => topic.vault === vault)) || "";
    const selected = buildSelectedTopic(status.state, status.topics, requestedVault || status.selectedVault || orderedFallbackVault);
    const selectedWithDetails = {
      ...selected,
      stageDetails: await buildStageDetails(selected)
    };
    return json(res, 200, {
      ...status,
      selectedVault: selectedWithDetails.vault || requestedVault || status.selectedVault || "",
      selectedTopic: selectedWithDetails
    });
  }

  if (req.method === "GET" && url.pathname === "/api/setup") {
    try {
      const install = url.searchParams.get("install") === "1";
      return json(res, 200, await getSetupStatus({ install }));
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/setup/install") {
    try {
      return json(res, 200, await getSetupStatus({ install: true }));
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/directories/choose") {
    const result = await chooseDirectoryWithDialog("Choose a parent folder for the new topic");
    if (result.error) return json(res, result.status || 500, { error: result.error });
    return json(res, 200, result);
  }

  if (req.method === "POST" && url.pathname === "/api/vaults/import") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      let vaultPath = body.path?.trim();
      if (!vaultPath) {
        const result = await chooseDirectoryWithDialog("Choose an existing Deep Survey vault folder");
        if (result.error) return json(res, result.status || 500, { error: result.error });
        if (result.cancelled) return json(res, 200, { ok: false, cancelled: true });
        vaultPath = result.path;
      }
      const imported = await importExistingVault(vaultPath);
      return json(res, 200, imported);
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/topics/rename") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const vault = body.vault?.trim();
      const topic = body.topic?.trim();
      if (!vault || !topic) return badRequest(res, "Vault and topic name are required.");
      return json(res, 200, await renameTopicInIndex(vault, topic));
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/topics/remove") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const vault = body.vault?.trim();
      if (!vault) return badRequest(res, "Vault is required.");
      return json(res, 200, await removeTopicFromIndex(vault));
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/preferences/topic-order") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const topicOrder = Array.isArray(body.topicOrder)
        ? body.topicOrder.filter((vault) => typeof vault === "string" && vault.trim()).map((vault) => vault.trim())
        : null;
      if (!topicOrder) return badRequest(res, "topicOrder must be an array.");
      const preferences = await writeAppPreferences({ topicOrder });
      return json(res, 200, { ok: true, topicOrder: preferences.topicOrder });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/preferences/selected-vault") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const selectedVault = typeof body.selectedVault === "string" ? body.selectedVault.trim() : "";
      if (selectedVault && !safeVaultRoot(selectedVault)) return badRequest(res, "selectedVault is invalid.");
      const preferences = await writeAppPreferences({ selectedVault });
      return json(res, 200, { ok: true, selectedVault: preferences.selectedVault || "" });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/open-url") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const targetUrl = typeof body.url === "string" ? body.url.trim() : "";
      const result = await openExternalUrl(targetUrl);
      if (!result.ok) return json(res, 400, { ok: false, error: result.error || "Could not open URL." });
      return json(res, 200, result);
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
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

  if (req.method === "POST" && url.pathname === "/api/vault/open-path") {
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const result = await openVaultPath(body.vault, body.path);
      if (result.error) return json(res, result.status || 500, { ok: false, error: result.error });
      return json(res, 200, result);
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "GET" && url.pathname === "/api/stage3/manual-download-list.html") {
    const vault = url.searchParams.get("vault");
    const root = safeVaultRoot(vault);
    if (!root) return forbidden(res, "Invalid vault path");
    try {
      const data = await buildManualDownloadEntries(root);
      const html = renderManualDownloadListHtml(root, data);
      res.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "content-length": Buffer.byteLength(html)
      });
      res.end(html);
      return;
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/stage3/manual-pdf/choose") {
    const vault = url.searchParams.get("vault");
    const root = safeVaultRoot(vault);
    if (!root) return forbidden(res, "Invalid vault path");
    try {
      const selection = await choosePdfFilesWithDialog("Choose one or more PDFs for this Deep Survey topic");
      if (selection.error) return json(res, selection.status || 500, { ok: false, error: selection.error });
      if (selection.cancelled) return json(res, 200, { ok: false, cancelled: true, imported: [], failed: [] });
      return json(res, 200, { ok: true, paths: selection.paths, selectedCount: selection.paths.length });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/stage3/manual-pdf/import-selected") {
    const vault = url.searchParams.get("vault");
    const root = safeVaultRoot(vault);
    if (!root) return forbidden(res, "Invalid vault path");
    try {
      const body = JSON.parse((await readRequestBody(req)) || "{}");
      const paths = Array.isArray(body.paths) ? body.paths : [];
      const result = await importManualPdfPaths(root, paths);
      result.stage3 = await maybeCompleteStage3AfterImport(root);
      return json(res, 200, { ...result, selectedCount: paths.length });
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message || String(error) });
    }
  }

  if (req.method === "GET" && url.pathname === "/api/appserver/threads") {
    try {
      const limit = Number(url.searchParams.get("limit") || 20);
      const vaultRoot = safeVaultRoot(url.searchParams.get("vault"));
      const cwdCandidates = [workspaceRoot];
      if (vaultRoot) {
        cwdCandidates.push(vaultRoot, path.dirname(vaultRoot));
      }
      const threadsById = new Map();
      let cursor = null;
      const errors = [];
      for (const cwd of [...new Set(cwdCandidates.filter(Boolean))]) {
        try {
          const result = await codexAppServer.listThreads({ limit, cwd });
          if (!cursor && result?.cursor) cursor = result.cursor;
          for (const thread of result?.data || []) {
            const normalized = normalizeThread(thread);
            if (!normalized.id || threadsById.has(normalized.id)) continue;
            threadsById.set(normalized.id, { ...normalized, appStatus: appServerStatusSnapshot(normalized.id) });
          }
        } catch (error) {
          errors.push(`${cwd}: ${error.message || String(error)}`);
        }
      }
      if (!threadsById.size && errors.length) {
        return json(res, 500, { ok: false, error: errors.join("; ") });
      }
      return json(res, 200, {
        ok: true,
        threads: [...threadsById.values()],
        cursor,
        errors
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
        sandbox: sandboxForMode(body.mode)
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
        sandbox: sandboxForMode(body.mode)
      });
      const status = updateAppServerThreadStatus(threadId, {
        status: "running",
        turnId: result?.turn?.id || null,
        runningStage: null,
        dlwAction: null,
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
    let selectedTopic = body.selectedTopic || null;
    if (action === "start") {
      try {
        const initialized = await initTopic(topic, workspaceDirectory);
        selectedTopic = {
          topic: initialized.topic || topic,
          vault: initialized.vault_root,
          active: true,
          nextStage: initialized.current_stage || "stage_1_discovery",
          stages: []
        };
      } catch (error) {
        return json(res, 500, { ok: false, action, error: error.message || String(error) });
      }
    } else {
      try {
        selectedTopic = await activateSelectedTopicState(selectedTopic);
      } catch (error) {
        return json(res, 500, { ok: false, action, error: error.message || String(error) });
      }
    }
    const promptSet = prompts(action, topic, selectedTopic, { workspaceDirectory });
    const prompt = promptSet[action];
    if (!prompt) return badRequest(res, `Unknown DLW action: ${action}`);
    const input = dlwPluginInput(prompt);
    try {
      const result = await codexAppServer.sendInputToThread({
        threadId,
        input,
        model: normalizeModel(body.model),
        effort: normalizeReasoningEffort(body.effort),
        sandbox: sandboxForMode(body.mode)
      });
      const status = updateAppServerThreadStatus(threadId, {
        status: "running",
        turnId: result?.turn?.id || null,
        runningStage: runningStageForDlwAction(action, selectedTopic),
        dlwAction: action,
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
      return json(res, 200, { ok: true, action, prompt, input, selectedTopic, turn: result?.turn || null, status, raw: result });
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
    const shouldCancelStage3Downloads = Boolean(body.cancelStage3Downloads || statusLooksLikeStage3(currentStatus));
    let stage3Downloads = null;
    try {
      updateAppServerThreadStatus(threadId, {
        status: "stopping",
        turnId,
        summary: `Stopping turn ${turnId}`
      });
      if (shouldCancelStage3Downloads) {
        stage3Downloads = await cancelStage3DownloadProcesses();
      }
      const result = await codexAppServer.interruptTurn({ threadId, turnId });
      const status = updateAppServerThreadStatus(threadId, {
        status: "interrupted",
        turnId,
        runningStage: null,
        dlwAction: null,
        summary: `Interrupted turn ${turnId}`
      });
      addAppServerEvent("appserver", {
        method: "turn/interrupt/local",
        summary: `Interrupted turn: ${turnId}`,
        threadId,
        turnId,
        status,
        stage3Downloads
      });
      return json(res, 200, { ok: true, status, stage3Downloads, raw: result });
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
      stage3: "Review Manual PDF Stage",
      importManual: "Import Manual PDFs",
      custom: mode === "write" ? "Codex Instruction: Write" : "Codex Instruction: Read-only"
    };
    const sandbox = action === "custom" && mode === "read"
      ? "read-only"
      : codexSandbox;
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
    let processTree = null;
    if (run.child) {
      run.cancelRequested = true;
      run.status = "cancelling";
      processTree = await cancelRunProcessTree(run);
      addRunEvent(run, "meta", {
        message: `Cancellation requested. Stopped ${processTree.count} process signal(s).`,
        killed: processTree.killed.map((item) => item.pid),
        forceKilled: processTree.forceKilled.map((item) => item.pid),
        failed: processTree.failed,
        remaining: processTree.remaining.map((item) => item.pid)
      });
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
    return json(res, 200, { ok: true, processTree, stage3Downloads });
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
