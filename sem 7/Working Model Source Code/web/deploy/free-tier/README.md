# Free deployment: Oracle VM + existing InsForge backend

Status: prepared locally, NOT deployed. Oracle signup is blocked because it requires
card verification and the user has no credit card. The deployment must require no
card as well as zero recurring hosting cost. Do not proceed with Oracle signup or
provisioning; preserve these files for reuse. A replacement hosting route is pending
the user's choice about whether their PC may remain the runtime host.
User constraint: zero recurring cost; do not upgrade plans, provision paid compute,
or enable paid model gateways. Temporary trial credits do not count as free hosting.

Local verification completed during preparation:

- Both production Docker images built for `linux/arm64`.
- Web container serves the homepage and rejects unauthenticated workspace POSTs.
- Agent starts, serves health, and enforces the shared key on private routes.
- Caddy configuration and Linux shell syntax checks pass.
- Typecheck, lint, application tests (125 Node tests plus script suites), and all
  789 intelligence tests pass. Frozen-source checksums needed LF checkout rules;
  `.gitattributes` now preserves the exact committed bytes.
- Four SQLite snapshots pass integrity checks; the application's `Ledger.verify()`
  confirms all 1,314 staged forecast records. Live WAL and tamper-refusal checks pass.
- Both build contexts were scanned for copied credentials and environment files.

These checks do not establish public HTTPS, hosted account onboarding, free-model
response quality, broker OAuth, backup recovery on a replacement VM, or live
browser-closed order settlement. Those remain deployment acceptance checks.

## Account and VM

The account owner completes Oracle identity/card/OTP verification at
https://www.oracle.com/cloud/free/. Never put card details, passwords, OTPs,
API private keys or SSH private keys in chat.

Choose the home region carefully: Always Free compute is restricted to that region.
Prefer Mumbai if available. On the current free allowance, create one **Always Free
eligible** Ampere A1 ARM VM, 2 OCPUs / 12 GB RAM, with Ubuntu 24.04 ARM64 and a
50 GB boot volume. Confirm the console's eligibility label and all existing usage
before creating it. Do not add paid images, NAT gateways, load balancers or extra
storage. Capacity can be unavailable; do not solve that by upgrading the account.
Oracle can reclaim idle free instances: keep tested backups elsewhere.

Allow inbound TCP 80/443, UDP 443 (optional HTTP/3), and SSH only from the operator's
IP in both the OCI network rules and the OS firewall. Only Caddy publishes ports;
agent 8000 and web 3000 are reachable inside Docker. Do not expose the Docker API.

Create a free DuckDNS hostname and point it at the VM's public IP. A paid domain
is optional. Domain setup and VM access are still needed before actual deployment.

## Private release bundle

From the web repository:

```powershell
node scripts/prepare-free-deployment.mjs --domain YOUR-HOST.duckdns.org
```

The default agent source is `D:/QP/agent-service`; override with `--backend`.
The generator reads ignored local environment files but copies only an explicit
credential allowlist into `.local-data/free-deployment/<release>/secrets/`.
It generates a new shared internal key. Server credentials never enter either
Docker build context. Public InsForge values are passed as web build arguments.
The entire bundle is private: never commit it or upload it to public file hosting.
An OpenRouter key is required even for the agent's health check; the bundle refuses
to proceed without one. Only free model routing is enabled in this profile.

SQLite's backup API captures committed WAL contents and checks integrity for all
four databases. The forecast chain is checked separately. Existing broker tokens
are not transferred: Fyers needs a fresh operator login after deployment.
The frozen `.local-data/workspace.json` is neither copied nor modified.

`--domain quantplus.invalid` creates a validation bundle only; it is not deployable
as a public site. Every bundle is a point-in-time snapshot, not a live data sync.

## On the VM

Transfer the bundle over SSH to a private directory such as `/opt/quantplus`.
Verify the SSH host fingerprint before accepting it. Preserve the previous release
and database snapshots on later updates; do not overwrite current data with an old
bundle. Initial installation only:

```bash
cd /opt/quantplus
sudo bash install.sh
```

The installer installs Docker from Docker's official Ubuntu repository, validates
Compose, builds both ARM images, and fixes mount ownership. It deliberately leaves
containers and cron stopped so local and cloud writers cannot overlap.
Finish these steps before starting:

1. Inventory Windows forecast tasks and the running local hosted paper worker.
   Disable local scheduled jobs and stop local production workers at handoff.
   Record their old state so rollback can restore it. Leave local browser-test
   profiles isolated. Take a **final** SQLite snapshot after local writers stop;
   replace the initial staged DB snapshots before the first cloud start.
2. Add the real HTTPS app origin to InsForge's auth redirect allowlist using
   `npx.cmd -y @insforge/cli config export/plan/apply`. Preserve existing redirects
   and verification settings. Do not run the old two-user isolation harness: it
   changes project-wide verification settings.
3. Register `https://YOUR-HOST.duckdns.org/api/v1/fyers/callback` in the Fyers app.
   Caddy forwards only this callback and the legacy `/fyers/callback` to the agent;
   all other traffic goes through the session-authenticated web app.
4. Confirm public DNS, inbound ports, and free-tier quotas. Start:

```bash
sudo docker compose up -d --wait
sudo docker compose ps
```

Sign in, reconcile the hosted portfolio, complete Fyers login, and check live
quotes. During market hours, place a throwaway limit order, close every browser,
and verify server settlement. Restart the containers and verify persistence.
Use `Ledger.verify()` on the server for the full application-level chain check.
Do not announce production readiness until these checks pass.

Review `cron.example` against the actual Windows schedules before installing it.
The example assumes a UTC host clock. Generation jobs are commented out until
quota testing; the 50-stock local research workload will exceed free inference.
Add log rotation for cron's `state/*.log`. Retain only the required snapshot history
within the disk allowance and copy completed backups to separate free storage or
the development PC. Same-VM snapshots alone do not protect against VM loss.

## Free AI profile and limits

Compose overrides paid provider credentials to empty and uses `openrouter/free`.
Automatic prediction warming and AI sentiment enrichment are disabled to preserve
free quota. Foreground research and chat remain available when the free model can
serve the request. Agent request cap is 35/day; chat cap is 10/day (chat limits are
per user, so these are not a shared account-wide quota). OpenRouter's provider
limits remain authoritative; retries, multiple users and independent jobs can hit
429s sooner. There is no paid fallback. Some research outputs can abstain or remain
unavailable. Test structured JSON responses before enabling research schedules.

Check the existing InsForge project's plan and database/auth/storage usage before
launch: keeping the backend does not remove its quotas. Do not enable paid AI
features or paid backup products. Project memory writes currently require paid
InsForge AI, so the zero-cost decision is recorded in this repository instead.

## Rollback

Stop the cloud worker before restarting a local hosted worker. Keep InsForge as
the paper-book authority; do not switch back to the frozen historical local book.
For app rollback, use the recorded release image tags and existing current state
mounts. Restore SQLite only after stopping every writer and retaining the newer
databases; forecast evidence must not be silently truncated.

Sources: [Oracle Always Free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Oracle signup and trial conditions](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm),
[Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/),
[InsForge pricing](https://insforge.dev/pricing),
[OpenRouter limits](https://openrouter.ai/docs/api_reference/limits).
