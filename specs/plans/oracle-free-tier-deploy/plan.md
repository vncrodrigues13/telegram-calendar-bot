# Deploy telegram-calendar-bot to an Oracle Cloud Always Free VM

## Context

The bot is currently laptop-shaped: `main.py:51` calls `run_polling()`, which
owns the event loop and long-polls Telegram until Ctrl+C. Close the terminal and
the bot stops. README:40 says so outright — *"What you don't need: a server, a
domain, a webhook, an always-on machine."* The goal is always-on, at no cost.

**Research conclusion — Vercel was investigated and rejected.** It is now
technically viable (Python 3.13/3.14 supported, Python bundles raised to 500 MB
vs. our ~155 MB, 300s duration on Hobby), but every Vercel path — including
`Dockerfile.vercel` — runs as a *request-scoped Vercel Function* that must serve
HTTP on `$PORT` and **scales to zero after 5 minutes idle**. `run_polling()`
opens no port and generates no traffic, so it would be `SIGTERM`'d and never
wake. Vercel's own bot KB: functions "can't be depended on for shared state or
reliable disk access." Going there would mean a webhook rewrite plus replacing
sqlite with a hosted DB plus headless OAuth — roughly four subsystems.

Oracle Always Free gives an always-on ARM VM for $0, so **the bot's code does not
change at all**. This plan is packaging and operations only.

One qualification on "always-on": we stay on a no-card Always Free account, which
means the VM is subject to Oracle's idle-reclamation sweep and will occasionally
be stopped until restarted by hand. That tradeoff — and why it is cheap to live
with — is spelled out in step 5.

**Why this is cheaper than the alternatives:** Fly.io dropped its free tier in
Oct 2024 (~$2-5/mo); Render background workers require Starter ($7/mo) and its
free web services spin down at 15 min idle; Railway removed its free tier.

## Approach

Containerize as-is and run it under `docker compose` on an Oracle Ampere A1 VM.
`run_polling()`, sqlite, and the existing OAuth code all stay untouched — the
container just needs a writable volume and correct env vars.

Two properties make this simple:
- **Polling is outbound-only.** The VM needs *no ingress rules at all* — no
  ports, no domain, no TLS, no webhook secret. Smaller attack surface than the
  Vercel design would have had.
- **The dev Mac is `arm64`, same as Ampere A1.** Local `docker build` produces a
  natively-correct image; no cross-compilation, and local testing is faithful.
  Verified all native deps (`cryptography`, `pydantic-core`) ship
  `manylinux_2_17_aarch64` wheels, so nothing compiles from source.

## Work items

### 1. `.dockerignore` (new, at repo root) — do this first

`.env`, `credentials.json`, `token.json` and `bot.db` all currently exist
untracked in the working tree. A naive `COPY . .` bakes live secrets into an
image layer permanently. Mirror `.gitignore` and add build noise:

```
.env
credentials.json
token.json
*.db
.git
.venv
__pycache__/
*.py[cod]
.pytest_cache/
*.egg-info/
specs/
tests/
```

### 2. `Dockerfile` (new)

Multi-stage using the official `uv` image, `uv.lock` honored via `--frozen`:

- **Builder**: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`. Copy
  `pyproject.toml` + `uv.lock` first and run `uv sync --frozen --no-dev
  --no-install-project` so the dependency layer caches independently of source
  edits; then copy `src/` and `uv sync --frozen --no-dev`.
- **Runtime**: `python:3.13-slim-bookworm`, copy the `/app/.venv` across.
- **`tzdata` is required** — `extract.py:27` calls
  `ZoneInfo(settings.timezone)` with `America/Sao_Paulo`. Debian slim ships
  without the zoneinfo database, so this raises `ZoneInfoNotFoundError` and
  *every extraction fails*. Install via `apt-get install -y --no-install-recommends
  tzdata` (or add the `tzdata` PyPI package). This is the most likely silent
  breakage in the whole plan.
- Create a non-root user with **UID 1000**, matching the default `ubuntu` user
  on Ubuntu 24.04. This makes the bind-mounted `./data` directory writable by
  the container without any `chown` dance, which is what lets the `token.json`
  write at `gcal/auth.py:42` succeed.
- `CMD ["python", "-m", "event_bot.main"]` (exec form, so PID 1 receives
  `SIGTERM`; PTB already installs handlers for graceful shutdown).

### 3. `docker-compose.yml` (new)

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: ./data/.env
    environment:
      DB_PATH: /data/bot.db
      TOKEN_PATH: /data/token.json
    volumes:
      - ./data:/data:Z
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
```

No `ports:` — polling needs no inbound. A **bind mount** (`./data:/data`) rather
than a named volume, so seeding secrets is a plain `scp` into a directory you can
see, instead of `docker compose cp` gymnastics against an opaque volume.

The **`:Z` suffix** relabels the directory for SELinux. It is a no-op where
SELinux is disabled and essential where it is enforcing — without it, an
SELinux-enabled host denies the container every write to `/data`, so the
`token.json` write at `gcal/auth.py:42` and every sqlite write fail with a bare
`Permission denied` that looks nothing like a labeling problem. Relevant because
the OCI console defaults to **Oracle Linux**, which is SELinux-capable; Ubuntu
uses AppArmor and ignores the suffix. Cheap insurance either way. Confirm which
you are on with `getenforce`.

The `environment:` block overrides the relative paths from `config.py:32-34`,
which otherwise resolve against CWD. Note `CREDENTIALS_PATH` is deliberately
**not** set — see step 4. Log rotation matters because the boot volume is finite
and this runs for months.

### 4. Google OAuth: bootstrap, and why `credentials.json` stays home

`gcal/auth.py:40` calls `InstalledAppFlow.run_local_server(port=0)`, which opens
a browser — impossible on a headless VM. **No code change needed**; seed the
token from the Mac, where that flow already works.

**`credentials.json` must not be copied to the VM.** Verified: `token.json`
already contains `client_id`, `client_secret`, `refresh_token` and `token_uri`,
so the refresh branch at `auth.py:24-27` is self-sufficient. `credentials_path`
is only read at `auth.py:32`, on the interactive branch that cannot run headless
regardless. Leaving it off the server means one fewer secret at rest, and turns a
would-be browser hang into an immediate, legible `FileNotFoundError`.

1. **First, in Google Cloud Console, move the OAuth consent screen from
   "Testing" to "In production".** Google issues 7-day refresh tokens to apps in
   Testing status, so an unattended VM would go silent every week. Mint **new**
   OAuth credentials after switching — reusing the old client can still yield
   7-day tokens. `calendar.events` is a sensitive scope, so expect a
   verification prompt; self-approval as the sole test user is fine here.
2. Locally: `uv run python -m event_bot.tools.gcal_check` → produces `token.json`.
3. Ship the two files the VM actually needs, over SSH:
   ```bash
   ssh ubuntu@VM 'mkdir -p ~/eventbot/data && chmod 700 ~/eventbot/data'
   scp .env token.json ubuntu@VM:~/eventbot/data/
   ssh ubuntu@VM 'chmod 600 ~/eventbot/data/.env ~/eventbot/data/token.json'
   ```

Secrets-handling rationale, in short: the bot cannot function without these
values in process memory, so every hosting option puts them on the box — the
question is only the transfer channel and the permissions at rest. `scp` is
encrypted over SSH, `0600` on a single-user VM whose only entry is your SSH key
is the proportionate control, and a secrets manager would add real operational
weight for no gain at this scale. The exposure that *does* matter is secrets
baked into image layers, which step 1 (`.dockerignore`) exists to prevent.

### 5. Provision the Oracle VM

- Shape **VM.Standard.A1.Flex**, Ubuntu 24.04 LTS **aarch64**, **1 OCPU / 6 GB**,
  47 GB boot volume minimum. The Always Free A1 allowance is 2 OCPU / 12 GB
  (Oracle halved it from 4/24 during 2026), but deliberately ask for half of it
  — see "Why the smaller shape" below.
- **Create it in your home region.** Always Free resources qualify only there.
- Expect `Out of host capacity` on A1 — retry, or try another availability
  domain in the home region.
- **No payment method. The account stays pure Always Free.** This is a
  deliberate decision, and it has a consequence worth understanding rather than
  discovering: see "Idle reclamation" below.
- **Keep ingress to SSH only.** The default security list already allows TCP 22,
  which step 4's `scp` requires — an earlier draft said "leave ingress rules
  empty," which would lock you out. The point is to add *nothing beyond* 22:
  no 80, no 443, no webhook port, because polling is outbound-only.
- Run **`deploy/setup-vm.sh`** to install Docker Engine + the compose plugin,
  enable it at boot, and create `~/eventbot/data` with mode 700. The script
  detects the distro, because the OCI console defaults to **Oracle Linux**
  (`dnf`, user `opc`) while this plan specifies Ubuntu (`apt`, user `ubuntu`) —
  picking the default image is the usual reason `apt` appears broken on a fresh
  instance. It also waits out the `dpkg` lock held by unattended-upgrades on a
  freshly booted Ubuntu VM, the other common cause.
- The script runs `systemctl enable --now docker`, so `restart: unless-stopped`
  survives reboots. This is what makes reclamation cheap — do not skip it.

#### Idle reclamation — expected, accepted, survivable

Oracle deems an instance idle if, over a 7-day window, 95th-percentile CPU is
<20%, network <20% and memory <20% (memory applies to A1 only). **This bot trips
all three comfortably.** A Telegram long-poll with occasional Gemini calls is
near-zero on every axis, so plan on being reclaimed rather than on avoiding it.

What actually happens, and why it is tolerable:

1. Oracle **emails a warning**; the instance is **stopped roughly a week later**.
2. It is **stopped, not terminated** — the boot volume survives intact, so
   `bot.db`, `.env` and `token.json` are all still there.
3. Restart it from the OCI console (Compute → Instances → Start), retrying if
   the region is momentarily out of A1 capacity.
4. **Nothing else is required.** `systemctl enable docker` plus
   `restart: unless-stopped` (step 3) bring the bot back by itself once the VM
   boots. Recovery is one button, not a rebuild.

Enforcement is sporadic in practice — many idle free instances run untouched for
months, others get swept — so treat the cadence as unpredictable rather than as
a fixed clock.

Upgrading to Pay As You Go would exempt the account from reclamation and stay at
$0 within the Always Free limits. **It was considered and rejected**: with no
card on file, "never billed" is guaranteed by construction rather than by
vigilance, and Oracle has no hard spend cap to fall back on. The accepted cost
is occasional silent downtime until someone presses Start.

The honest downside: you will most likely notice an outage by missing an event.
A free uptime ping would fix that, but it needs a code change, so it is left as
a follow-up rather than compromising the "`src/**` unchanged" property.

#### Nothing irreplaceable lives on the VM

Which is why no backup policy is warranted here:

- `token.json` — regenerate on the Mac with `uv run python -m event_bot.tools.gcal_check`
- `.env` — already on the Mac
- `bot.db` — pending event cards only, ephemeral by nature

Even total loss of the boot volume is re-provision plus the `scp` from step 4 —
minutes of work. This is the strongest argument that accepting reclamation is a
reasonable trade.

#### Why the smaller shape

Not billing headroom — with no payment method there is no billing. Two reasons:

- **Restart capacity.** `Out of host capacity` is the normal A1 experience, and
  it is precisely what will block a restart after reclamation. A 1 OCPU / 6 GB
  request is materially likelier to be satisfiable than 2 OCPU / 12 GB when the
  region is tight. Manual restart is now the recovery path, so restart success
  rate is the metric that matters.
- **Utilization percentages** are proportional, so the same workload scores
  higher on a smaller shape. Directionally helpful; honest caveat: the bot
  idles near zero on any shape and will not clear 20% either way. This does not
  prevent reclamation.

2 OCPU / 12 GB is equally free — this is a judgment call for restart
resilience, not a correctness fix.

### 6. `README.md` — add a Deploy section

Document the VM setup, the token-seeding step, and `docker compose up -d --build`.
Note the "In production" consent-screen requirement prominently; it is the
failure that would take a week to notice.

Also carry over from step 5: the 1 OCPU / 6 GB shape, the home-region
requirement, and a short operational note — *"if the bot goes quiet, check for
an Oracle reclamation email and press Start in the console; it recovers on its
own from there."*

## Files touched

| File | Change |
|---|---|
| `.dockerignore` | new |
| `Dockerfile` | new |
| `docker-compose.yml` | new |
| `deploy/setup-vm.sh` | new — VM bootstrap, distro-detecting |
| `README.md` | new Deploy section |
| `src/**` | **unchanged** |

## Verification

Docker is not currently installed/running on the dev Mac — install Docker Desktop
first, or run steps 1-3 directly on the VM.

1. **Offline suite still green**: `uv run pytest` (no network or keys needed).
2. **Image builds and tzdata resolves** — the highest-risk item:
   ```bash
   docker compose build
   docker compose run --rm bot python -c \
     "from zoneinfo import ZoneInfo; print(ZoneInfo('America/Sao_Paulo'))"
   ```
   Must print a `ZoneInfo` object, not raise `ZoneInfoNotFoundError`.
3. **No secrets in the image** — the exposure that actually matters. Check the
   built layers, not just the running container:
   ```bash
   docker compose run --rm bot sh -c 'ls -a /app; test ! -f /app/.env && echo CLEAN'
   docker history --no-trunc telegram-calendar-bot-bot | grep -iE "TELEGRAM|GEMINI|token" || echo CLEAN
   ```
4. **Bind mount is writable by the UID-1000 app user**:
   `docker compose run --rm bot sh -c 'touch /data/probe && echo WRITABLE'`
5. **Calendar works without `credentials.json` on the box** — proves the
   refresh-only path: with just `token.json` in `./data`, tap ✅ on a card and
   confirm the event is created rather than a `FileNotFoundError`.
6. **End to end, locally**: seed `./data` with `.env` + `token.json`, then
   `docker compose up`. Forward a real invite to the bot; confirm the card
   renders, tap ✏️ and send a correction, then tap ✅ and confirm the event
   appears in Google Calendar.
7. **Restart survives state**: `docker compose restart`, then tap ✅ on a card
   created *before* the restart. It must still work — this proves `bot.db`
   is on the volume and not in the container's ephemeral layer.
   *(Known limitation: the ✏️ flow uses `context.user_data[EDITING_KEY]`
   — `handlers.py:364` → `:175` — which is in-process RAM with no PTB
   persistence configured, so a pending edit is lost across restarts. Pre-existing
   behavior, not introduced here. Worth a follow-up to move it into `store.py`.)*
8. **On the VM**: `docker compose up -d --build`, then `docker compose logs -f`
   and forward an invite from a phone. Reboot the VM and confirm the bot
   comes back by itself.
9. **Account-level, in the OCI console**:
   - **No payment method attached** — Billing → Payment Method is empty and the
     account reads Always Free. This is the check that guarantees $0.
   - Instance is in the **home region**, shape reads **1 OCPU / 6 GB**, and the
     console marks it Always Free eligible.
   - **Rehearse the reclamation recovery**: stop the instance from the console,
     start it again, and confirm the bot reappears on Telegram with no manual
     intervention on the box. Given the decision to accept shutdowns, this is
     the single most valuable check in the list — it proves the one-button
     recovery works *before* you need it at an inconvenient moment.
