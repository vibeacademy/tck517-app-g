# Project Configuration

## Platform

- **Hosting**: gcp
- **Compute**: Cloud Run
- **Container Registry**: Artifact Registry
- **Database**: Neon (serverless Postgres with per-PR branching)
- **Secrets**: Google Secret Manager
- **Auth (CI/CD → GCP)**: Workload Identity Federation
- **Selected**: 2026-05-01

## Stack

- **Runtime**: Python 3.12
- **Web**: FastAPI + Uvicorn
- **Templates**: Jinja2 + HTMX 2.x (no JS build step)
- **Styling**: Pico.css via CDN
- **DB layer**: SQLModel + Alembic
- **Package manager**: uv

## Key Service Choices

- **LLM provider**: Anthropic Claude (Opus for quality drafts; Haiku for
  iteration / cheaper regen) — accessed via the Anthropic Python SDK.
- **User auth**: Email magic-link only (no passwords).
- **Email sender**: Resend (default; free tier covers MVP user volume).
- **Observability**: Google Cloud Logging + Error Reporting (zero-setup,
  GCP-native).
