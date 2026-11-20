/* AUTO-GENERATED from agent-service/contract — do not hand-edit. */

export interface AnalystReport {
  agent: string;
  summary: string;
  signals?: Signal[];
  confidence: number;
  evidence?: Evidence[];
}

export interface ArenaEvent {
  seq: number;
  ts: string;
  variant_id: string;
  event: string;
  detail?: string;
}

export interface ArenaState {
  living: ArenaVariant[];
  seed_bank: Record<string, unknown>[];
  allocation: Record<string, unknown>;
  cap: number;
  as_of: string;
}

export interface ArenaVariant {
  id: string;
  name: string;
  status: string;
  strikes: number;
  probation: boolean;
  parent_id?: string | null;
  genome: Record<string, unknown>;
}

export interface Challenge {
  status: ThesisStatus;
  core_claim_restated: string;
  new_evidence_considered?: string[];
  duplicate_risks_discarded?: string[];
  direction_symmetry_check_passed: boolean;
  raw_override_applied?: boolean;
  reasons?: string[];
}

export interface ControlRequest {
  engage: boolean;
  reason?: string;
}

export interface DebateTurn {
  stance: string;
  argument: string;
  rebuttal_to?: string;
  confidence_delta: number;
}

export interface Evidence {
  source: string;
  ref: string;
  available_at: string;
}

export interface FinalDecision {
  action: string;
  size: number;
  rationale: string;
  thesis_version: number;
  authority?: string;
  cannot_create_position?: boolean;
  cannot_reverse_position?: boolean;
  cannot_increase_exposure?: boolean;
}

export interface KillSwitchState {
  engaged: boolean;
  reason?: string;
  updated_ts?: string | null;
}

export interface RawExhaustionSignals {
  flush_flag: boolean;
  blowoff_flag: boolean;
  ret_5d_pct: number;
  dist_from_20d_low_pct: number;
  dist_from_20d_high_pct: number;
}

export interface RiskVerdict {
  approve: boolean;
  adjusted_size: number;
  notes?: string;
}

export interface SessionRequest {
  instrument: string;
  as_of: string;
  interval?: string;
  force_rerun?: boolean;
  portfolio?: Record<string, unknown> | null;
  manager_mode?: string;
}

export interface SessionStatus {
  id: string;
  status: string;
  decision?: FinalDecision | null;
}

export interface Signal {
  name: string;
  value: number;
  direction: string;
}

export interface StageEvent {
  stage: string;
  agent: string;
  status: string;
  output_ref?: string;
}

export interface Thesis {
  direction: string;
  conviction: number;
  key_evidence?: string[];
  key_risks?: string[];
  mechanism_type?: MechanismType;
}

export interface TradeProposal {
  instrument: string;
  direction: string;
  size_pct: number;
  entry: number;
  stop: number;
  target: number;
}

export interface StageEvent {
  stage: string;
  agent: string;
  status: string;
  output_ref?: string;
}

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
