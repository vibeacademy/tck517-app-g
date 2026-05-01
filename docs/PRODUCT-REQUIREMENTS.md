# Product Requirements Document

## Product Overview

- **Name**: D&D Character Builder (working name)
- **Domain**: A D&D character builder
- **Type**: Web application
- **Category**: Content / Media platform

## Vision and Problem Statement

### Problem

Building a balanced, playable D&D character with a real personality, traits,
and consistent lore is slow and tedious. Rolling for every attribute often
yields a flat mishmash — no clear strengths, no notable weaknesses, no
character to play.

### Vision

Make it easy to create compelling D&D characters with natural-language
prompts — based on **vibes**, not checkboxes on a form.

### How People Solve This Today

Players today use D&D Beyond and similar online character builders. These
tools are exhaustive but feel like work: form-driven, WYSIWYG, optimized
for stat correctness rather than character voice. Personality, backstory,
and lore are left to the user to bolt on after the mechanical sheet is
done — and rarely end up consistent with the rolled stats.

## Target Audience

### Primary Users

- **Who**: A tabletop games hobbyist who wants imaginative, lore-consistent
  characters built from prompts, not WYSIWYG outfit-pickers.
- **Pain Point**: Random rolls produce flat, unplayable characters with no
  meaningful strengths or weaknesses — and no internal consistency between
  stats, backstory, and personality.
- **Current Solution**: D&D Beyond and other form-based character builders.

### Secondary Users

None — single user type for v1.

## Features

### MVP (Must Have)

- [ ] Email-based user authentication (sign up, sign in, password reset)
- [ ] Projects: each project is a workspace for a single character
  (create, list, open, rename, delete)
- [ ] Character builder UI driven by a natural-language text prompt that
  generates a believable, playable character (stats + personality +
  lore, internally consistent)

### Out of Scope (v1)

- Visual / WYSIWYG controls (sliders, dropdowns, outfit pickers, portraits)
- Mobile-native apps (web only)
- Multi-user collaboration on a character
- Campaign / party management
- Marketplace, sharing, or social feed
- Payments / subscriptions
- Export to D&D Beyond or VTT integrations

### Core Value Proposition

Generate believable, engaging, relatable D&D characters from a few
sentences of prompt — fast enough that creating a character feels like
play, not paperwork.

## Success Metrics

| Metric | Target (3 months post-launch) |
|--------|-------------------------------|
| Primary: Registered users | 100 |

## Competitive Analysis

| Competitor | Strength | Weakness | Our Differentiator |
|------------|----------|----------|--------------------|
| D&D Beyond | Comprehensive rules coverage, official content licensing, large user base | Form-driven and exhaustive; feels like work; weak on personality and lore | Prompt-first, vibes-driven flow that produces a coherent character (stats + lore + personality) in one pass — feels like fun |

**Key differentiator**: It feels like fun. Other builders feel like work.

## Constraints and Requirements

- **Timeline**: 2–3 months to launch (target: 2026-07-01 to 2026-08-01)
- **Budget**: Limited resources — pick managed services with generous free
  tiers; avoid infra that needs ops attention
- **Technical**: FastAPI + Jinja2 + HTMX on Python 3.12, SQLModel + Alembic,
  deployed to Google Cloud Run with Neon Postgres (per-PR branching),
  Artifact Registry for images, Secret Manager for credentials, `uv`
  as the package manager
- **Team**: Solo / small (per the budget constraint)

## Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| Security | Email + password auth with hashed passwords; session-based auth; HTTPS only; secrets in Google Secret Manager (never in repo) |
| Performance | Character generation must feel interactive — surface streaming or progress within 2s, full result within 30s |
| Scalability | Cloud Run autoscale to zero acceptable for v1; sized for ~100 users in first 3 months |
| Accessibility | Keyboard navigable; readable contrast; screen-reader friendly text-first UI (text-only scope helps) |

## Dependencies

- LLM provider for character generation (cost is the dominant variable;
  selection deferred to architecture phase)
- Neon (Postgres + per-PR branching)
- Google Cloud Run, Artifact Registry, Secret Manager
- GitHub (source, CI/CD, project board)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM cost per character exceeds free-tier budget at 100 users | High | Pick a cost-aware default model; cap tokens per generation; cache common prompt structures |
| Generated characters feel generic ("sounds like ChatGPT") and don't deliver on the "fun" differentiator | High | Invest prompt-engineering time in MVP; dogfood with target users early; measure qualitative feedback alongside signup count |
| D&D rules accuracy errors in generated stats erode trust | Medium | Validate stat blocks against rule constraints in code; flag generated content as "draft — verify before play" until validation matures |
| Scope creep into visual controls undermines the "vibes" thesis | Medium | Out-of-scope list above is binding for v1; revisit only after MVP signups target hit |

## Glossary

| Term | Definition |
|------|------------|
| Character | A single D&D player-character: stats, class, race, backstory, personality, and lore |
| Project | A workspace for one character — its prompt history, generated drafts, and current sheet |
| Vibes-first | Generation flow driven by natural-language description rather than form fields |
