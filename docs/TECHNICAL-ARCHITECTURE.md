# Technical Architecture

## Overview

A single-process FastAPI web app, server-rendered with Jinja2 + HTMX,
running on Google Cloud Run with a Neon Postgres backend. Character
generation is delegated to the Anthropic API. Authentication is
passwordless (magic link via Resend). All state of record lives in
Postgres; Cloud Run is stateless and scales to zero.

This is a **modular monolith** — one deployable, organized into
feature-aligned modules under `app/`. Per the budget constraint and
solo-team posture, we explicitly defer microservices, queues,
caches, and any infra that needs ops attention until product-market
fit is proven.

## Technology Stack

### Frontend

- **Framework**: Server-rendered Jinja2 templates + HTMX 2.x — no build
  step, no SPA, no client framework.
- **Styling**: Pico.css via CDN (class-less; replace if we outgrow it).
- **Interactivity**: HTMX for AJAX, form posts, and fragment swaps.
  Streaming character generation uses HTMX SSE (`hx-ext="sse"`) so the
  generated character text appears progressively.
- **No JS bundler / no Node toolchain.** The CI `node` job auto-skips.

### Backend

- **Runtime**: Python 3.12
- **Framework**: FastAPI + Uvicorn
- **Templates**: Jinja2 (rendered server-side; partials returned for
  HTMX swaps)
- **DB layer**: SQLModel + Alembic
- **LLM client**: `anthropic` Python SDK (streaming Messages API)
- **Email**: `resend` Python SDK (magic-link delivery)
- **Auth**: Custom magic-link implementation — short-lived signed tokens
  (itsdangerous `URLSafeTimedSerializer`), session cookie on success.
  No third-party auth provider for v1.
- **Testing**: pytest + httpx (`fastapi.testclient.TestClient`) with an
  in-memory SQLite fixture and `app.dependency_overrides[get_session]`.
- **Package manager**: uv
- **Lint / format / types**: ruff + mypy (config in `pyproject.toml`)

### Database

- **Primary**: Neon Postgres
  - One project per environment (dev / staging / prod)
  - **Per-PR branching** for ephemeral preview environments — every PR
    gets its own isolated DB branch
- **Cache**: None for v1. Postgres + Cloud Run revision-level memory is
  enough at 100-user scale.
- **Search**: None for v1.

### Infrastructure

- **Compute**: Google Cloud Run (one service, scale-to-zero, min
  instances = 0 in dev / staging, = 1 in prod once we have paying users
  to keep cold-start out of the magic-link redemption path)
- **Container Registry**: Google Artifact Registry
- **Secrets**: Google Secret Manager (`ANTHROPIC_API_KEY`,
  `RESEND_API_KEY`, `DATABASE_URL`, `SESSION_SECRET`,
  `MAGIC_LINK_SECRET`)
- **CI/CD**: GitHub Actions → Cloud Run (auth via Workload Identity
  Federation)
- **Logging / Errors**: Google Cloud Logging + Error Reporting (auto-
  groups unhandled FastAPI exceptions). View at
  `https://console.cloud.google.com/errors`.

## System Design

### Component Diagram

```text
        ┌────────────────────┐
        │      Browser       │
        │  (HTMX + Pico.css) │
        └─────────┬──────────┘
                  │ HTTPS
                  v
        ┌────────────────────┐                 ┌──────────────────────┐
        │  FastAPI on        │── messages.api ─▶ Anthropic API        │
        │  Cloud Run         │  (streaming)    │ (Claude Opus / Haiku) │
        │                    │                 └──────────────────────┘
        │  ┌──────────────┐  │                 ┌──────────────────────┐
        │  │ auth         │  │── send.email ──▶ Resend API           │
        │  │ projects     │  │                 └──────────────────────┘
        │  │ characters   │  │                 ┌──────────────────────┐
        │  │ generations  │  │── psycopg ─────▶ Neon Postgres        │
        │  └──────────────┘  │                 │  (per-PR branches)   │
        └─────────┬──────────┘                 └──────────────────────┘
                  │ stdout / unhandled exc
                  v
        ┌────────────────────┐
        │ Cloud Logging /    │
        │ Error Reporting    │
        └────────────────────┘
```

### Module Layout

```text
app/
  main.py              # FastAPI app, middleware, route registration
  config.py            # Pydantic Settings (env-driven)
  db.py                # engine + get_session dependency
  templates.py         # Jinja2 template loader
  auth/
    routes.py          # /auth/login, /auth/verify, /auth/logout
    tokens.py          # magic-link sign / verify
    email.py           # Resend integration
    deps.py            # current_user dependency
  projects/
    routes.py          # /projects, /projects/{id}
    service.py         # CRUD logic
  characters/
    routes.py          # /projects/{id}/character (HTMX endpoints)
    generator.py       # Anthropic prompt assembly + streaming
    schema.py          # Pydantic shape of a generated character
    validator.py       # D&D rules sanity checks on stat blocks
  api/
    health.py          # /healthz for Cloud Run probes
  models/
    user.py
    project.py
    character.py
    generation.py
templates/
  base.html
  home.html
  auth/
  projects/
  characters/
  _fragments/          # HTMX fragment templates
```

### Data Flow — Character Generation

1. User opens a project, types a prompt, submits the HTMX form.
2. The `characters` route persists a `Generation` row (status =
   `pending`, prompt stored), then opens an SSE stream.
3. `generator.py` calls Anthropic's streaming Messages API. Tokens are
   forwarded to the browser as SSE events that HTMX swaps into the page
   in real time.
4. On stream completion, the generator parses the model's structured
   output (JSON mode) into the `Character` schema, runs `validator.py`
   for rules sanity checks, and persists the `Character` row linked to
   the project.
5. The `Generation` row is updated with status (`succeeded` / `failed`)
   plus token counts for cost tracking.

### Data Flow — Magic-Link Auth

1. User submits email at `/auth/login`.
2. Server creates / fetches a `User` row, mints a signed token
   (`URLSafeTimedSerializer`, TTL 15 min, single-use nonce stored on the
   user row), and emails a link to `/auth/verify?token=…` via Resend.
3. On click, server verifies signature + TTL + nonce, rotates the
   nonce (invalidating the link), sets a session cookie
   (HTTP-only, Secure, SameSite=Lax), and redirects to `/projects`.

### API Design

- **REST + HTML fragments.** Most endpoints return HTML (full page or
  HTMX fragment). No public JSON API in v1.
- **Streaming**: SSE for character generation only (`text/event-stream`).
- **CSRF**: HTMX requests carry a per-session token in a custom header,
  validated by middleware.
- **Health**: `GET /healthz` (200 = liveness; used by Cloud Run probes).

## Data Models

### Core Entities

```text
User
  id (uuid, pk)
  email (citext, unique)
  magic_link_nonce (text, nullable)   -- rotated on every successful login
  magic_link_sent_at (timestamptz, nullable)
  created_at (timestamptz)
  last_login_at (timestamptz, nullable)

Project
  id (uuid, pk)
  user_id (fk → User)                 -- one workspace per character
  name (text)
  created_at, updated_at (timestamptz)

Character
  id (uuid, pk)
  project_id (fk → Project, unique)   -- exactly one character per project in v1
  data (jsonb)                        -- the generated sheet (stats, lore, personality)
  created_at, updated_at (timestamptz)

Generation
  id (uuid, pk)
  project_id (fk → Project)
  prompt (text)
  status (enum: pending | succeeded | failed)
  model (text)                        -- e.g. "claude-opus-4-7"
  input_tokens (int, nullable)
  output_tokens (int, nullable)
  error (text, nullable)
  created_at, completed_at (timestamptz, nullable)

Session
  id (uuid, pk)                       -- value stored in HTTP-only cookie
  user_id (fk → User)
  created_at (timestamptz)
  expires_at (timestamptz)
```

### Why JSONB for `Character.data`?

The character schema will evolve quickly during MVP iteration as we
tune the prompt and the validator. A JSONB column with a Pydantic
schema in code lets us reshape without migrations on every prompt
tweak. Migrations come later if we need to query into specific fields.

### Migrations

- Alembic, autogenerate from SQLModel metadata.
- Per-PR Neon branches mean every PR runs its own `alembic upgrade head`
  on a fresh database — schema changes are caught before merge.

## Development Standards

### Code Style

- **Linting**: `ruff check .` (rules `E,F,I,W,B,UP`)
- **Formatting**: `ruff format .`
- **Types**: `mypy app/` — `check_untyped_defs = true`
- **Naming**: `snake_case` for functions/modules; `PascalCase` for
  SQLModel / Pydantic classes; route paths kebab-case (`/auth/verify`,
  `/projects/{id}`).

### Testing Requirements

- **Unit tests**: pytest, in-memory SQLite via `StaticPool` fixture.
- **HTTP tests**: `TestClient` with `app.dependency_overrides[get_session]`
  pointing at the test session.
- **HTMX fragment tests**: assert HTML substrings AND assert
  `"<html" not in response.text` to catch full-page leaks from fragment
  endpoints.
- **LLM tests**: do **not** call the real Anthropic API in tests. Inject
  a fake generator via `app.dependency_overrides` that returns canned
  output. Real-API smoke tests live in a separate, opt-in
  `tests/smoke/` suite gated on `RUN_SMOKE_TESTS=1`.
- **Coverage**: aim for 80% on `app/` excluding `app/main.py` glue.

### Documentation

- One ADR per significant architectural decision (see ADRs below).
- Module-level docstring on each new feature module explaining its
  responsibility.
- Per-route handler: a one-line docstring describing what it returns
  (full page vs. HTMX fragment).

### Code Review

- All CI checks green (lint, types, tests, build).
- Per-PR Neon branch present and `alembic upgrade head` succeeded
  (caught by CI).
- New env vars added to `.env.example` AND to Secret Manager for
  staging/prod.
- For LLM-touching changes: include before/after sample generations in
  the PR description.

## Security

### Authentication

Email magic link only. Tokens are signed with `itsdangerous`
(`URLSafeTimedSerializer`) using `MAGIC_LINK_SECRET`, expire in 15
minutes, and are single-use (per-user nonce rotated on consumption).
Session cookies are HTTP-only, Secure, SameSite=Lax.

### Authorization

Single-tenant model: a user can only access their own `Project`s and
their nested `Character` / `Generation` rows. Enforced via a
`current_user` FastAPI dependency that filters every query by
`user_id`. No row-level security (RLS) in Postgres for v1.

### Data Protection

- All traffic HTTPS (Cloud Run terminates TLS).
- Secrets only in Google Secret Manager — never in repo, never in env
  files committed to git. `.env.example` lists names, not values.
- No PII beyond email addresses; no payment data; no health data.
- Anthropic and Resend API keys scoped to the project; rotated via
  Secret Manager versions (no code changes needed for rotation).
- Cloud Logging redacts request bodies on auth routes (avoid logging
  email addresses in clear).

## Scalability

### Current Targets

- 100 registered users in 3 months.
- Peak concurrent generations: low single digits.
- Cloud Run: max instances 5, concurrency 80 — well within budget.

### Scaling Strategy

The honest answer: we do not need to scale for v1. The architecture
naturally scales horizontally (stateless Cloud Run + managed Postgres),
so when scaling becomes a real concern we will:

1. Raise Cloud Run max instances and add `min_instances >= 1` in prod.
2. Move character generation onto a background worker
   (Cloud Tasks → Cloud Run job) so the request thread is freed.
3. Add a Postgres read replica or pgBouncer if Neon connections become
   the bottleneck.
4. Add caching only when a measured query proves it necessary.

## Architecture Decision Records

### ADR-001: Modular monolith on Cloud Run

- **Status**: Accepted
- **Context**: Solo-team, limited budget, 100-user 3-month target.
- **Decision**: Single FastAPI deployable, scale-to-zero on Cloud Run.
- **Consequences**: Lowest infra surface area; one CI pipeline; easy
  local dev. We accept that splitting later requires real refactor work.

### ADR-002: Anthropic Claude as the LLM provider

- **Status**: Accepted
- **Context**: Need strong long-form, voicey character / lore generation
  with structured output. Cost matters.
- **Decision**: Anthropic Claude — Opus for first-pass generations
  (quality matters most for the "feels like fun" differentiator); Haiku
  for cheaper regenerations and prompt iteration in dev.
- **Consequences**: Vendor lock-in to Anthropic. We mitigate by keeping
  the LLM call isolated in `characters/generator.py` so swapping later
  is a one-file change.

### ADR-003: Magic-link auth, no passwords

- **Status**: Accepted
- **Context**: PRD calls for "email-based authentication." Passwords
  add an attack surface (storage, reset flow, hashing) that buys little
  for a hobbyist tool.
- **Decision**: Magic-link only via Resend. Sessions via signed
  HTTP-only cookies.
- **Consequences**: Email deliverability becomes a critical dependency
  (mitigated by Resend's reputation). User cannot log in if their inbox
  is unavailable — acceptable for the target user.

### ADR-004: JSONB for character data

- **Status**: Accepted
- **Context**: Character schema will iterate fast during MVP. We don't
  yet need to query into character fields.
- **Decision**: Store the generated character as a JSONB blob with a
  Pydantic schema enforced in application code.
- **Consequences**: No migrations needed for prompt-shape changes.
  Trade-off: queries that filter by character traits are deferred until
  schema stabilizes.

### ADR-005: Cloud Logging + Error Reporting (no Sentry)

- **Status**: Accepted
- **Context**: Need observability; budget is tight; everything else is
  on GCP.
- **Decision**: Use Cloud Logging + Error Reporting. Initialize
  structured logging in `main.py`; let Cloud Run capture stdout.
- **Consequences**: Less polished error UX than Sentry. Reconsider
  after MVP if triage time becomes a pain point.

### ADR-006: HTMX SSE for streaming generation

- **Status**: Accepted
- **Context**: Character generation can take 5–30s; users need feedback.
- **Decision**: Stream the Anthropic response over SSE; HTMX `sse-swap`
  paints tokens as they arrive.
- **Consequences**: Cloud Run supports SSE up to its 60-minute request
  timeout — well within our 30-second target. Long-lived connections
  count against per-instance concurrency; acceptable at our scale.
