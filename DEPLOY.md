---
cdm:
  audience: user-guide
  fingerprint: 8ae5a1f86c4241f9
  fingerprint_tiers:
    composite: 8ae5a1f86c4241f9
    signature: 8ae5a1f86c4241f9
  schema_version: 1.0.0
  symbol_sigs:
    01f66393966eb9a0: 28c1356e6569b64d
    0876b97b4f87642b: 0021bebafd35d002
    0cf12e8c5846c397: 6fb6a046f63b2027
    12bc63d1607505d1: 91fadcaece9e3b4d
    1ba1047b0e3840ba: b06a571295e930a9
    2376642f85d6463f: 61ed4daf9127944d
    298f02b756782040: a81d4761f106d3e9
    2d3a243e7b4afcd0: 0d648ce9b564f72c
    35baa09cb51c3139: 405c8ee1d41e1889
    4562956ed28f8632: 5908d8f78a58e17b
    458fa7b520b82d56: 2ab353191c86540e
    470b20ec1ecf1cac: f9b2c5aff8cb1397
    5804430045d4534f: a8b86e393976ed9d
    5f442d09f3aa3126: ba0c652224613544
    5fbd6e86a6eeb2a6: db590ff2d383b6db
    621b2ef70ffdfa64: 1369bed2bcb219f3
    63dbbf550bcfeaa9: 766897f2187147da
    6d4138cfa565642a: f3e305054b38a60a
    74a883a037bc227f: a60b2a5031562161
    7bde6a55f740200c: 5990f2faea734fd4
    933f0965d57cdda4: 0a5c6acfc0be7f37
    940945089b7c29d9: 8e8845973d11785f
    9e61e18aeafda85e: 6fb1c274999cb179
    a3cea1fc61cf0ed9: 77d50fc3897935d5
    aacf030a822d3bdf: 2988594c7fa419f8
    abf4c8a1df8a34b4: 74cacc7f9d39fa48
    b373b61c9e7799d5: 6704c1c20f6ef089
    b7fcfd70051cca68: 9230fe9bab5509a1
    d6277c00e8da4b3d: 723a679e89d2d281
    ea6dc935ad4149be: 01d12d3d400a6334
    ec0f5c2c5e88caaf: 8b3d6a7fcf9bc95f
    f10f27c94ea61b7f: 084d9b571a2aa001
    f34e0384fdc7abd9: 00b12bc7e4cac976
    fefa85429324cd68: 3f70f5f582076839
---
# Deploying the custodex central server

> The operator runbook for the central server: how to start it, every setting it
> reads and the variable that overrides it, the secrets, the production hardening,
> and how to upgrade it to a new release. This page is itself monitored by `cdx`
> against the settings models it documents.

The central server (`cdx-server`) ingests review records from many repos, syncs
configs, opens docs-PRs, and serves the console. This is the operator runbook for
running it for real. (For a single local repo with no central state, you don't need
any of this — just `cdx serve`.)

## TL;DR — Docker Compose (server + Postgres)

```bash
# Generates the three secrets into .env on the first run only; a later run
# keeps them. Compose reads .env on every start.
[ -e .env ] || (umask 077 &&
  admin=$(openssl rand -hex 32) &&
  kek=$(openssl rand -base64 32) &&
  db=$(openssl rand -hex 16) &&
  printf '%s\n' "CDMON_ADMIN_TOKEN=$admin" "CDMON_SECRET_KEY=$kek" \
    "CDMON_DB_PASSWORD=$db" > .env) &&
  docker compose up --build
# → console + API on http://localhost:33333 (server.port)  (GET /health, GET /settings)
```

Run this from the checkout, next to `docker-compose.yml`. It generates the secrets
once: `.env` is readable by you alone, git ignores it, and the image never copies
it. Keep it, and never commit it. If a secret cannot be generated, no `.env` is
written and nothing starts: fix the cause (such as a missing `openssl`) and run it
again. The secrets section below says why the values must not change.

On startup the server reads `CDMON_DATABASE_URL`, runs the Alembic migrations to
head, and uses a persistent `SqlStore` — records/resolutions/coverage/roster survive a
restart. With no database URL it logs a loud warning and falls back to an in-memory
store (everything is lost on restart) — fine for a demo, never for production.

## Configuration — `config/settings.yaml` + `CDMON_*`

Non-secret runtime tunables live in `config/settings.yaml` (mounted read-only in the
compose file). Every key is optional: a key you leave out keeps its built-in default.
Precedence is **environment variable > file > built-in default** (the central server
reads no CLI flags; `cdx serve`'s own `--host`/`--port` only affect the standalone
dashboard, which keeps its localhost defaults).

This is the complete file at its built-in defaults. A `# env:` comment names the
environment variable that overrides the key on that line; a key without one is set
in the file only.

```yaml
version: "1.0.0"
server:
  host: 0.0.0.0                # env: CDMON_SERVER_HOST
  port: 33333                  # env: CDMON_SERVER_PORT
  log_level: info              # env: CDMON_SERVER_LOG_LEVEL
  trusted_hosts: ["*"]         # env: CDMON_TRUSTED_HOSTS  ("*" = any Host header)
  cors:
    allow_origins: []          # env: CDMON_CORS_ORIGINS  (empty = CORS off)
    allow_credentials: false
    allow_methods: ["*"]
    allow_headers: ["*"]
  rate_limit:
    requests_per_minute: null  # env: CDMON_RATE_LIMIT_RPM  (null = no limit)
  git:
    allowed_hosts: [github.com, gitlab.com]
    extra_allowed_hosts: []    # env: CDMON_ALLOWED_GIT_HOSTS
    allow_file_scheme: true
    clone_timeout_seconds: null  # env: CDMON_GIT_CLONE_TIMEOUT  (null = no timeout)
  workers:
    enabled: false             # env: CDMON_WORKER_ENABLED
    interval_seconds: 900      # env: CDMON_WORKER_INTERVAL
    kinds: [fixes, docs]       # env: CDMON_WORKER_KINDS
```

The file is validated against the `Settings` model and its nested `ServerSettings`,
`CorsSettings`, `RateLimitSettings`, `GitSettings` and `WorkerSettings` models. An
unknown key, a value that cannot be read as the key's type (such as
`interval_seconds: soon`), or a value a model check rejects (such as
`requests_per_minute: 0`) stops the server at startup with a `ConfigError` naming the
problem. A value that can be read as the key's type is converted, so
`interval_seconds: "60"` loads as the number 60. **server.log_level** is not checked
when the file loads; it is passed to uvicorn as written.

How an environment override is parsed depends on the key it sets:

- **Lists** (`CDMON_TRUSTED_HOSTS`, `CDMON_CORS_ORIGINS`, `CDMON_ALLOWED_GIT_HOSTS`,
  `CDMON_WORKER_KINDS`) are comma-separated, and spaces around each item are trimmed.
  A value with no items left (only commas) is a startup error. A list override
  replaces the file's list; it never appends to it.
- **Integers** (`CDMON_SERVER_PORT`, `CDMON_RATE_LIMIT_RPM`, `CDMON_GIT_CLONE_TIMEOUT`,
  `CDMON_WORKER_INTERVAL`) must be whole numbers; anything else is a startup error.
- **Booleans** (`CDMON_WORKER_ENABLED`) are on for `1`, `true`, `yes` or `on`, in
  any case and with spaces around the value trimmed; every other value turns the
  key off.

An override set to the empty string is ignored, so the file value (or the default)
stands. The git hosts named by the git-hosts override are added to
**server.git.allowed_hosts**, which keeps its own list.

Inspect the **effective** resolved settings any time: `GET /settings` returns every
value above plus whether each secret is configured (never the secret values), and
`cdx settings` prints a summary of the server, CORS, rate-limit and git values with
the same secret presence.

### Secrets (environment only — never the file)

| Env var               | Purpose                                                         |
|-----------------------|-----------------------------------------------------------------|
| `CDMON_ADMIN_TOKEN`   | Bearer token for the GLOBAL roster routes (`POST /admin/roster*`). **Unset = those routes are OPEN** — the server warns loudly on a persistent store. Always set it in a shared deployment. |
| `CDMON_DATABASE_URL`  | A `postgresql+psycopg` URL with user, password, host and database — selects the persistent store and runs migrations. The compose file sets it for you. |
| `CDMON_SECRET_KEY`    | base64 32-byte KEK that AES-256-GCM-seals per-repo git provider credentials at rest. |
| `CDMON_DB_PASSWORD`   | Compose only: the bundled Postgres password, which the compose file also writes into the database URL. It falls back to a placeholder when unset, so set it for any real deployment. |

Generate these once and pass the same values on every start, upgrades included:
the TL;DR's `.env` file does this for Compose. Two of them cannot simply be changed
later. Postgres takes its password only when its data volume (`cdx-db`) is first
created, so a new `CDMON_DB_PASSWORD` also needs `ALTER USER cdx PASSWORD '...'`
run inside the database. A new `CDMON_SECRET_KEY` cannot open the git provider
credentials sealed with the old one, so each repo's credentials must be registered
again.

Per-repo write tokens are passed at registration and stored only as sha256 hashes.

## Hardening checklist (production)

1. **Restrict the Host header.** Set **server.trusted_hosts** to your real
   hostname(s) so a spoofed `Host` / DNS-rebinding is a 400. Under Compose, also
   list `localhost`: the container's healthcheck calls `GET /health` on it, and
   without it the healthcheck gets a 400 and the container is reported unhealthy.
2. **Set the admin token, the KEK and the database password.** See the secrets
   table; the compose file refuses to start without `CDMON_ADMIN_TOKEN` and
   `CDMON_SECRET_KEY`.
3. **Terminate TLS at a reverse proxy.** The app speaks plain HTTP; run nginx/Caddy/an
   ingress in front for TLS, and forward to the port in **server.port** (`:33333` by
   default). When the proxy is on the same host, keep the app off other interfaces.
   Without Docker, bind it to `127.0.0.1` (set **server.host**). Under Compose, leave
   **server.host** as it is, because Docker forwards the published port to the
   container's own interface, not its loopback; publish the port on the host's
   loopback instead (`127.0.0.1:33333:33333` in the server's `ports:`).
4. **CORS only if the console is hosted separately.** The bundled console is served
   single-origin (no CORS needed). If you host the frontend elsewhere, list its origin
   in **server.cors.allow_origins**.
5. **Rate limiting.** Set **server.rate_limit.requests_per_minute** to throttle
   brute-force of the bearer/admin tokens and clone-on-demand. **Caveat:** the limiter
   is per-process — with N uvicorn workers the effective limit is N×, and it resets on
   restart. For a hard, shared limit, enforce it at the reverse proxy instead.
6. **Cap clone-on-demand.** Set **server.git.clone_timeout_seconds** so a slow or hung
   remote can't pin a worker; add self-hosted git hosts to
   **server.git.extra_allowed_hosts**.
7. **Refuse `file://` remotes.** Set **server.git.allow_file_scheme** to false
   unless you register repos by a `file://` URL. The flag refuses `file://` remote
   URLs and nothing else: a registration that names a local path on the server's own
   disk (its **local_path** field) is not checked, and the first registration of a
   repo needs no token. On a shared deployment keep the API on a trusted network or
   behind the reverse proxy's access control.

The settings block above shows which of these keys also take an environment
override.

## Health & operations

- **Liveness:** `GET /health` → `{"status": "ok"}` (unauthenticated).
- **Effective config:** `GET /settings` (open, redacted) or `cdx settings`.
- **Migrations** run automatically on startup from `CDMON_DATABASE_URL`; to run them
  by hand, export that variable and run `alembic upgrade head`.
- **Background suggesters** are off by default. Set **server.workers.enabled** to
  run them; **server.workers.interval_seconds** sets how often they run and
  **server.workers.kinds** picks which ones run (fixes, docs or both). Each server
  process runs its own loop.
- **Scaling:** the store is the only shared state, so you can run multiple replicas
  against one Postgres. Remember the rate limiter is per-replica.

## Upgrading the hub

The console the server serves is build output: `frontend/dist` is ignored by git, so
updating the code never updates it. Rebuild it on every upgrade, or the server keeps
serving the console of the release you upgraded from.

Upgrade to a release tag (replace vX.Y.Z with the release you are moving to), never
to whatever is on the default branch:

```bash
git fetch --tags &&
  git checkout --merge vX.Y.Z &&
  pip install -e '.[server]' &&
  cdx settings &&
  (cd frontend && npm ci && npm run build)
# then restart the server; migrations run on startup
```

Each step runs only if the one before it succeeded, so a failed step stops the
upgrade before you restart anything. `config/settings.yaml` is tracked, so a plain
`git checkout` refuses to run over your edits whenever the release changes that
file; `--merge` carries your edits across to the release. `cdx settings` then loads
the file with the new release and stops the block if the release rejects it. If one
of your edits conflicts with a change in the release, git leaves conflict markers in
the file and `cdx settings` stops there: edit the file to keep the value you want,
run `git reset -q -- config/settings.yaml`, and run the block again.

With Docker, run the same `git fetch --tags` and `git checkout --merge vX.Y.Z`, then
`docker compose up --build` from the same directory, so Compose reads the same
`.env`. The image's first stage rebuilds the console from the checked-out source,
and the build context never includes a local `frontend/dist`. The server refuses to
start with a `ConfigError` if the release rejects your settings file; fix it as
above.

## Building the image standalone

```bash
docker build -t cdx-server .
docker run --rm -p 33333:33333 \
  -e CDMON_DATABASE_URL=postgresql+psycopg://user:pw@db.example/custodex \
  -e CDMON_ADMIN_TOKEN=... -e CDMON_SECRET_KEY=... \
  cdx-server
```

The image builds the Astro console in a node stage and serves it single-origin, so
`GET /` returns the dashboard (and falls back to a JSON landing if the build is absent).
