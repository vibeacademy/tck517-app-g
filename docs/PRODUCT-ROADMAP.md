# Product Roadmap

## Overview

A 2–3 month build aimed at launching a vibes-first D&D character builder
by July–August 2026. Phase 1 delivers a usable prompt-to-character flow
behind email auth with per-character workspaces. Phase 2 iterates on the
generation quality and lightweight sharing once we have real user
feedback. Phase 3 expands surface area only if we hit the 100-user
3-month signup target.

## Phase 1: MVP

- **Target**: 2026-07-01 to 2026-08-01 (2–3 months from 2026-05-01)
- **Goal**: Deliver a working prompt-to-character experience that feels
  like fun, not paperwork

### Features

| Feature | Priority | Status |
|---------|----------|--------|
| Email auth (sign up, sign in, password reset) | P0 | Backlog |
| Projects: per-character workspaces (CRUD) | P0 | Backlog |
| Prompt-driven character builder (stats + personality + lore in one pass) | P0 | Backlog |
| Character sheet view (read-only render of generated character) | P0 | Backlog |
| Regenerate / refine character from updated prompt | P1 | Backlog |
| Basic D&D rules validation on generated stat blocks | P1 | Backlog |

### Success Criteria

- [ ] 100 registered users within 3 months of launch
- [ ] A new user can go from sign-up to a generated character in under
      5 minutes
- [ ] Generated characters consistently include stats, personality,
      and lore that reference each other (qualitative dogfood review)

## Phase 2: Iteration

- **Target**: 1–2 months post-launch (2026-09 to 2026-10)
- **Goal**: Sharpen generation quality and reduce regen friction based
  on real user feedback

### Candidate Features (re-prioritize from feedback)

| Feature | Priority | Status |
|---------|----------|--------|
| Prompt templates / starter vibes (e.g. "grizzled veteran", "naive prodigy") | TBD | Backlog |
| Inline edit of generated text fields (without losing other consistency) | TBD | Backlog |
| Shareable read-only character link | TBD | Backlog |
| Cost / token usage surfacing per project | TBD | Backlog |

### Success Criteria

- [ ] Returning-user rate (signup → second session) measurable and
      improving week-over-week
- [ ] Generation cost per character within budget at 2x current user count

## Phase 3: Growth

- **Target**: 3–6 months post-launch
- **Goal**: Expand only if MVP signups target was hit; otherwise stay
  in Phase 2 and keep iterating

### Candidate Features

| Feature | Priority | Status |
|---------|----------|--------|
| Light visual controls (opt-in, layered on top of the prompt flow) | TBD | Backlog |
| Export to common VTT / character-sheet formats | TBD | Backlog |
| Party / campaign workspace (multiple characters together) | TBD | Backlog |

## Milestone Definitions

| Milestone | Criteria | Target Date |
|-----------|----------|-------------|
| M1: MVP Launch | Auth + projects + prompt-driven character generation live in production | 2026-08-01 |
| M2: First 100 Users | 100 registered users | 2026-11-01 |
| M3: Product-Market Fit Signal | Returning-user rate trending up; qualitative "feels like fun" feedback dominates | 2027-Q1 |

## Constraints and Risks

| Risk | Phase | Mitigation |
|------|-------|------------|
| LLM cost overruns the limited budget | 1, 2 | Cap tokens per generation; pick cost-aware default model; monitor cost per character |
| Generated characters feel generic | 1 | Heavy prompt-engineering investment in MVP; dogfood with target users before launch |
| Scope creep into visual controls dilutes the "vibes" differentiator | 1, 2 | PRD out-of-scope list is binding for v1; revisit only after M2 |
| Solo / small team capacity | All | Use managed services (Cloud Run, Neon, Secret Manager); skip undifferentiated infra work |

## Dependencies

```text
Phase 1: MVP
    |
    v
Phase 2: Iteration (requires user feedback from Phase 1)
    |
    v
Phase 3: Growth (requires hitting M2 signup target)
```

## Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-05-01 | Initial roadmap from /bootstrap-product | Teddy Kim |
