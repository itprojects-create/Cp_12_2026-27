"""Generate a typed TypeScript client from contract/openapi.json + contract/schemas.json.

No npm needed: pure-stdlib generator. Output: frontend-client/client.ts with
interfaces for every backend schema plus a thin fetch/WS wrapper for /api/v1.
"""
from __future__ import annotations
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIM = {"string": "string", "number": "number", "integer": "number", "boolean": "boolean",
        "object": "Record<string, unknown>", "null": "null"}

def ts_of(node: dict, defs: dict) -> str:
    if "$ref" in node:
        return node["$ref"].split("/")[-1]
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])
    if "anyOf" in node:
        return " | ".join(ts_of(x, defs) for x in node["anyOf"])
    t = node.get("type", "unknown")
    if t == "array":
        return f"{ts_of(node.get('items', {}), defs)}[]"
    return PRIM.get(t, "unknown")

def interface(name: str, schema: dict, defs: dict) -> str:
    req = set(schema.get("required", []))
    lines = [f"export interface {name} {{"]
    for prop, sub in schema.get("properties", {}).items():
        opt = "" if prop in req else "?"
        lines.append(f"  {prop}{opt}: {ts_of(sub, defs)};")
    lines.append("}")
    return "\n".join(lines)

WRAPPER = '''
export class AgenticOSClient {
  constructor(private base = "", private fetcher: typeof fetch = fetch) {}
  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await this.fetcher(this.base + path, {
      ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${path} -> ${r.status}`);
    return r.json() as Promise<T>;
  }
  createSession(body: SessionRequest): Promise<SessionStatus> {
    return this.call("/api/v1/sessions", { method: "POST", body: JSON.stringify(body) });
  }
  getSession(id: string): Promise<SessionStatus> {
    return this.call(`/api/v1/sessions/${id}`);
  }
  getTheses(instrument: string): Promise<unknown> {
    return this.call(`/api/v1/theses/${encodeURIComponent(instrument)}`);
  }
  diffTheses(instrument: string, v1: number, v2: number): Promise<unknown> {
    return this.call(`/api/v1/theses/${encodeURIComponent(instrument)}/diff/${v1}/${v2}`);
  }
  runEval(): Promise<unknown> {
    return this.call("/api/v1/eval/run", { method: "POST" });
  }
  health(): Promise<unknown> {
    return this.call("/api/v1/health");
  }
  getArena(): Promise<ArenaState> {
    return this.call("/api/v1/arena");
  }
  bootstrapFounders(): Promise<unknown> {
    return this.call("/api/v1/arena/founders", { method: "POST" });
  }
  getKillSwitch(): Promise<KillSwitchState> {
    return this.call("/api/v1/killswitch");
  }
  setKillSwitch(engage: boolean, reason = ""): Promise<KillSwitchState> {
    return this.call("/api/v1/killswitch", {
      method: "POST", body: JSON.stringify({ engage, reason }),
    });
  }
  exportAudit(limit = 1000): Promise<unknown> {
    return this.call(`/api/v1/audit/export?limit=${limit}`);
  }
  subscribeArenaEvents(onEvent: (e: ArenaEvent) => void): WebSocket {
    const ws = new WebSocket(`${this.base.replace(/^http/, "ws")}/api/v1/arena/events`);
    ws.onmessage = (m) => onEvent(JSON.parse(m.data as string) as ArenaEvent);
    return ws;
  }
  subscribeSessionEvents(id: string, onEvent: (e: StageEvent) => void,
                         onDone: (final: StageEvent) => void): WebSocket {
    const ws = new WebSocket(
      `${this.base.replace(/^http/, "ws")}/api/v1/sessions/${id}/events`);
    ws.onmessage = (m) => {
      const e = JSON.parse(m.data as string) as StageEvent;
      (e.status === "done" || e.status.startsWith("failed") ? onDone : onEvent)(e);
    };
    return ws;
  }
}
'''

def main() -> None:
    with open(os.path.join(ROOT, "contract", "schemas.json"), encoding="utf-8") as f:
        schemas = json.load(f)
    parts = ["/* AUTO-GENERATED from agent-service/contract — do not hand-edit. */"]
    for name, sch in schemas.items():
        parts.append(interface(name, sch, schemas))
    parts.append("export interface StageEvent {\n  stage: string;\n  agent: string;\n"
                 "  status: string;\n  output_ref?: string;\n}")
    parts.append(WRAPPER.strip())
    out_dir = os.path.join(ROOT, "frontend-client")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "client.ts")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) + "\n")
    print(f"wrote {out} ({len(schemas)} interfaces + client)")

if __name__ == "__main__":
    main()
