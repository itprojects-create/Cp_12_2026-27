// Creates a PRIVATE release bundle. Never prints credentials or copies local books.
// node scripts/prepare-free-deployment.mjs --domain your-name.duckdns.org
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs, parseEnv } from "node:util";
import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";

const root = fileURLToPath(new URL("..", import.meta.url));
const { values } = parseArgs({
  options: {
    domain: { type: "string" },
    backend: { type: "string", default: "D:/QP/agent-service" },
    python: {
      type: "string",
      default: join(root, ".local-data/backend-runtime/Scripts/python.exe"),
    },
  },
});
const domain = values.domain;
if (
  !domain ||
  !/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain)
) {
  throw new Error("Pass --domain with the DNS hostname only (no scheme or path)");
}
const backend = resolve(values.backend);
const load = (file) => (existsSync(file) ? parseEnv(readFileSync(file, "utf8")) : {});
const web = { ...load(join(root, ".env")), ...load(join(root, ".env.local")) };
const agent = load(join(backend, ".env"));
const required = (value, name) => {
  if (!value || /[\r\n\0]/.test(value)) throw new Error(`Missing or multiline credential: ${name}`);
  return value;
};
const url = required(web.INSFORGE_URL, "INSFORGE_URL");
const anon = required(web.INSFORGE_ANON_KEY ?? web.VITE_INSFORGE_ANON_KEY, "INSFORGE_ANON_KEY");
const admin = required(web.INSFORGE_API_KEY, "INSFORGE_API_KEY");
if (anon === admin) throw new Error("Public anon and server admin keys must differ");
if (web.VITE_INSFORGE_URL && web.VITE_INSFORGE_URL !== url) throw new Error("InsForge URLs differ");
const release = new Date().toISOString().replace(/[-:.]/g, "").replace("Z", "z");
const out = join(root, ".local-data/free-deployment", release);
mkdirSync(out, { recursive: true });
for (const path of ["secrets", "state/fyers", "backups"])
  mkdirSync(join(out, path), { recursive: true });
// Raw Compose env_file format preserves literal $, # and quotes inside secrets.
const env = (path, object) => {
  for (const [name, value] of Object.entries(object)) {
    if (/[\r\n\0]/.test(String(value))) throw new Error(`Multiline env value: ${name}`);
  }
  writeFileSync(
    join(out, path),
    Object.entries(object)
      .map(([k, v]) => `${k}=${v}`)
      .join("\n") + "\n",
    { mode: 0o600 },
  );
};
const shared = randomBytes(32).toString("hex");
const openrouter = agent.OPENROUTER_API_KEY || agent.OPENROUTER_KEY || web.OPENROUTER_API_KEY || "";
required(openrouter, "OPENROUTER_API_KEY (required by the agent health check)");
env("secrets/web.env", {
  INSFORGE_URL: url,
  INSFORGE_API_KEY: admin,
  INSFORGE_ANON_KEY: anon,
  AGENT_SERVICE_API_KEY: shared,
  OPENROUTER_API_KEY: openrouter,
});
env("secrets/agent.env", {
  WEBSITE_API_KEY: shared,
  OPENROUTER_API_KEY: openrouter,
  FYERS_CLIENT_ID: required(agent.FYERS_CLIENT_ID, "FYERS_CLIENT_ID"),
  FYERS_SECRET_KEY: required(agent.FYERS_SECRET_KEY, "FYERS_SECRET_KEY"),
});
env(".env", {
  RELEASE_ID: release,
  APP_DOMAIN: domain,
  VITE_INSFORGE_URL: url,
  VITE_INSFORGE_ANON_KEY: anon,
});
const blocked = new Set([".git", "node_modules", "__pycache__", ".venv", "fyers_private"]);
const filter = (path) =>
  !blocked.has(basename(path)) &&
  !/^\.env(?:\.|$)/.test(basename(path)) &&
  !/\.(?:db|sqlite3?|pem|key|log)(?:-.*)?$/.test(basename(path));
function copySources(source, destination, names) {
  mkdirSync(destination, { recursive: true });
  for (const name of names)
    cpSync(join(source, name), join(destination, name), { recursive: true, filter });
}
copySources(root, join(out, "web"), [
  "src",
  "public",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "vite.config.ts",
  "Dockerfile",
  ".dockerignore",
]);
copySources(backend, join(out, "agent"), [
  "app",
  "quantplus_intelligence",
  "contract",
  "scripts",
  "requirements.lock.txt",
  "Dockerfile",
]);
// The build context is allowlisted, and a second boundary excludes any future env files.
writeFileSync(
  join(out, "agent/.dockerignore"),
  ".env*\n**/fyers_private\n**/__pycache__\n**/*.db*\n**/*.sqlite*\n*.pem\n*.key\n",
);
mkdirSync(join(out, "agent/data"), { recursive: true });
for (const name of ["nifty500.txt", "event_calendar.json"])
  cpSync(join(backend, "data", name), join(out, "agent/data", name));
// Refuse any accidental copy of an actual credential into either build context.
const privateValues = [admin, shared, agent.FYERS_SECRET_KEY, openrouter].filter(Boolean);
let checkedFiles = 0;
function checkContext(directory) {
  for (const name of readdirSync(directory)) {
    const file = join(directory, name);
    if (statSync(file).isDirectory()) checkContext(file);
    else {
      const bytes = readFileSync(file);
      if (
        /^\.env(?:\.|$)/.test(name) ||
        privateValues.some((key) => bytes.includes(Buffer.from(key)))
      )
        throw new Error("Refusing build context containing environment files or credentials");
      checkedFiles++;
    }
  }
}
checkContext(join(out, "web"));
checkContext(join(out, "agent"));
for (const name of [
  "compose.yaml",
  "Caddyfile",
  "backup.py",
  "install.sh",
  "run-job.sh",
  "cron.example",
  "README.md",
]) {
  cpSync(join(root, "deploy/free-tier", name), join(out, name));
}
execFileSync(
  values.python,
  ["-B", join(out, "backup.py"), join(backend, "data"), join(out, "state/agent-data")],
  { stdio: "pipe" },
);
for (const name of [
  "nifty500.txt",
  "event_calendar.json",
  "forecast_universe.json",
  "nifty500_sectors.json",
]) {
  const file = join(backend, "data", name);
  if (existsSync(file)) cpSync(file, join(out, "state/agent-data", name));
}
const revision = (cwd) => {
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
};
const snapshot = JSON.parse(readFileSync(join(out, "state/agent-data/snapshot.json"), "utf8"));
writeFileSync(
  join(out, "release.json"),
  JSON.stringify(
    {
      release,
      domain,
      web_commit: revision(root),
      agent_commit: revision(backend),
      source: "Working tree snapshot; includes uncommitted deployment preparation",
      profile: "free-models-only; no paid provider credentials copied",
      broker: "Fresh Fyers login required; existing tokens not copied",
      status: "PREPARED_NOT_DEPLOYED; final snapshot and local-worker handoff required",
      snapshot,
    },
    null,
    2,
  ) + "\n",
);
console.log(`Private release prepared: ${out}`);
console.log(`Build contexts checked: ${checkedFiles} files; no copied credentials or env files.`);
console.log(
  `SQLite integrity OK; forecast chain verified (${snapshot.forecast_chain.checked} entries).`,
);
console.log("No containers started. No local jobs stopped. No cloud resources created.");
if (domain.endsWith(".invalid"))
  console.log("Validation-only hostname: replace with real DNS before deploying.");
