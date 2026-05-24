import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";

export class CodexAppServerClient extends EventEmitter {
  constructor({ codexPath, cwd, env, model }) {
    super();
    this.codexPath = codexPath;
    this.cwd = cwd;
    this.env = env;
    this.model = model;
    this.child = null;
    this.buffer = "";
    this.pending = new Map();
    this.starting = null;
    this.initialized = false;
  }

  async ensureStarted() {
    if (this.initialized && this.child && !this.child.killed) return;
    if (this.starting) return this.starting;
    this.starting = this.start();
    try {
      await this.starting;
    } finally {
      this.starting = null;
    }
  }

  async start() {
    this.child = spawn(this.codexPath, ["app-server", "--listen", "stdio://"], {
      cwd: this.cwd,
      env: this.env,
      stdio: ["pipe", "pipe", "pipe"]
    });
    this.initialized = false;
    this.buffer = "";

    this.child.stdout.on("data", (chunk) => this.handleStdout(chunk));
    this.child.stderr.on("data", (chunk) => this.emit("stderr", chunk.toString("utf8")));
    this.child.on("exit", (code, signal) => {
      this.initialized = false;
      this.emit("exit", { code, signal });
      for (const { reject, timeout } of this.pending.values()) {
        clearTimeout(timeout);
        reject(new Error(`app-server exited code=${code ?? ""} signal=${signal ?? ""}`));
      }
      this.pending.clear();
    });

    await this.request("initialize", {
      clientInfo: {
        name: "codex-deep-literature-app",
        title: "Codex Literature Workflow",
        version: "0.1.0"
      },
      capabilities: {
        experimentalApi: true
      }
    });
    this.initialized = true;
  }

  stop() {
    if (this.child && !this.child.killed) {
      this.child.kill();
    }
    this.child = null;
    this.initialized = false;
    this.starting = null;
    this.buffer = "";
  }

  handleStdout(chunk) {
    this.buffer += chunk.toString("utf8");
    let index;
    while ((index = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        this.emit("stderr", `Unparseable app-server line: ${line}`);
        continue;
      }
      const hasId = message.id !== undefined && message.id !== null;
      if (hasId && this.pending.has(message.id)) {
        const { resolve, reject, timeout } = this.pending.get(message.id);
        clearTimeout(timeout);
        this.pending.delete(message.id);
        if (message.error) {
          reject(new Error(message.error.message || JSON.stringify(message.error)));
        } else {
          resolve(message.result);
        }
        continue;
      }
      if (hasId && message.method) {
        this.emit("serverRequest", message);
        continue;
      }
      if (message.method) this.emit("notification", message);
    }
  }

  async request(method, params = {}, timeoutMs = 30_000) {
    if (!this.child || this.child.killed) {
      throw new Error("app-server is not running");
    }
    const id = randomUUID();
    const payload = `${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`app-server request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timeout });
      this.child.stdin.write(payload, "utf8", (error) => {
        if (!error) return;
        clearTimeout(timeout);
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  async listThreads({ limit = 20 } = {}) {
    await this.ensureStarted();
    return this.request("thread/list", {
      cwd: this.cwd,
      archived: false,
      limit,
      sourceKinds: [],
      useStateDbOnly: false
    });
  }

  async listSkills({ cwd = this.cwd } = {}) {
    await this.ensureStarted();
    return this.request("skills/list", { cwd });
  }

  async startThread({ name, sandbox = "workspace-write", model = this.model } = {}) {
    await this.ensureStarted();
    const result = await this.request("thread/start", {
      cwd: this.cwd,
      model,
      sandbox,
      approvalPolicy: "on-request",
      threadSource: "user",
      sessionStartSource: "startup"
    });
    const threadId = result?.thread?.id;
    if (name && threadId) {
      await this.request("thread/name/set", { threadId, name });
    }
    return result;
  }

  async sendInputToThread({ threadId, input, sandbox = "read-only", model = this.model, effort = "medium" }) {
    if (!threadId) throw new Error("threadId is required");
    if (!Array.isArray(input) || input.length === 0) throw new Error("input is required");
    await this.ensureStarted();
    await this.request("thread/resume", {
      threadId,
      cwd: this.cwd,
      model,
      sandbox,
      approvalPolicy: "on-request",
      excludeTurns: true
    });
    return this.request("turn/start", {
      threadId,
      cwd: this.cwd,
      model,
      sandbox,
      approvalPolicy: "on-request",
      effort,
      input
    });
  }

  async sendToThread({ threadId, text, sandbox = "read-only", model = this.model, effort = "medium" }) {
    if (!text?.trim()) throw new Error("message is required");
    return this.sendInputToThread({
      threadId,
      sandbox,
      model,
      effort,
      input: [{ type: "text", text }]
    });
  }

  async listThreadTurns({ threadId, limit = 30 } = {}) {
    if (!threadId) throw new Error("threadId is required");
    await this.ensureStarted();
    return this.request("thread/turns/list", {
      threadId,
      limit,
      sortDirection: "asc",
      itemsView: "full"
    });
  }

  async listThreadTurnItems({ threadId, turnId, limit = 100 } = {}) {
    if (!threadId) throw new Error("threadId is required");
    if (!turnId) throw new Error("turnId is required");
    await this.ensureStarted();
    return this.request("thread/turns/items/list", {
      threadId,
      turnId,
      limit,
      sortDirection: "asc"
    });
  }

  async interruptTurn({ threadId, turnId }) {
    if (!threadId) throw new Error("threadId is required");
    if (!turnId) throw new Error("turnId is required");
    await this.ensureStarted();
    return this.request("turn/interrupt", { threadId, turnId });
  }

  respondToServerRequest(requestId, result) {
    if (!this.child || this.child.killed) {
      throw new Error("app-server is not running");
    }
    if (requestId === undefined || requestId === null) throw new Error("requestId is required");
    const payload = `${JSON.stringify({ jsonrpc: "2.0", id: requestId, result })}\n`;
    return new Promise((resolve, reject) => {
      this.child.stdin.write(payload, "utf8", (error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  }
}
