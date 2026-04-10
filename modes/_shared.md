# Shared Context — Loaded by All Modes

## Scoring Dimensions (10 total, 0.5 each, max 5.0)

1. **Role Fit** — Does the title and seniority match the candidate's level?
2. **Skill Match** — % of required skills present in CV (hard requirement)
3. **Domain Relevance** — Industry/domain match to candidate's background
4. **Growth Potential** — Learning opportunity, career trajectory alignment
5. **Compensation** — Salary range vs. target (if disclosed)
6. **Remote/Location** — Location fit (remote preference, relocation required?)
7. **Company Stage** — Stage match to candidate's preference (seed/growth/public)
8. **Mission Alignment** — Does the mission resonate with candidate's stated values?
9. **Tech Stack** — Language/framework overlap with candidate's toolbox
10. **Speed Signal** — Urgency indicators (new role, fast-growing team, funded)

## Archetypes (edit these to match YOUR career)

When writing the CV summary and tailoring bullets, pick the closest archetype:

- **Builder** — Shipping fast, full-stack, early-stage, 0→1
- **Architect** — System design, scale, distributed systems, staff+
- **Operator** — Infrastructure, reliability, SRE, platform
- **Data** — Data engineering, pipelines, analytics, ML infra
- **AI/ML** — Model training, inference, LLMOps, AI product
- **Leader** — EM, Head of, Director — people + technical

## CV Tailoring Rules (applied by `pdf` and `auto-pipeline` modes)

1. Extract 15–20 keywords from the JD
2. Inject keywords into: summary (3), first bullet of each role (1 each), skills section
3. Reorder experience bullets — most relevant first, nothing removed
4. Select top 3–4 projects by relevance to this role
5. Detect language: English JD → English CV; Spanish JD → Spanish CV
6. Detect region: US company → Letter format; EU company → A4
7. Match archetype to role — shift summary framing accordingly
8. Quantify every achievement: numbers, %, time saved, users, revenue

## Report Format

Every report MUST include these sections in this order:

```
# {###} — {Company} — {Role}

**Score:** {X.X}/5 ({Grade})
**URL:** {url}
**Date:** {YYYY-MM-DD}
**Archetype:** {archetype}

## TL;DR
2-sentence executive summary of fit.

## Evaluation

### 1. Role Fit (0.5)
### 2. Skill Match (0.5)
### 3. Domain Relevance (0.5)
### 4. Growth Potential (0.5)
### 5. Compensation (0.5)
### 6. Remote/Location (0.5)
### 7. Company Stage (0.5)
### 8. Mission Alignment (0.5)
### 9. Tech Stack (0.5)
### 10. Speed Signal (0.5)

## Strengths
- bullet

## Gaps
- bullet

## Tailored CV Notes
What to emphasize, what to reorder, which projects to lead with.

## Recommendation
**APPLY / SKIP / HOLD**
One sentence reasoning.
```

## Canonical Statuses

`Evaluated` | `Applied` | `Responded` | `Interview` | `Offer` | `Rejected` | `Discarded` | `SKIP`

No bold, no dates, no extra text in the status field.
