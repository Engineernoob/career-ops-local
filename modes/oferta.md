# Mode: oferta (Single Offer Evaluation)

**Triggered by:** `ops evaluate <url-or-id>`

## What This Mode Does

Deep single-offer evaluation. More detailed than auto-pipeline.
6 evaluation blocks + personalization analysis + interview angle.

## Evaluation Blocks

### Block 1 — Summary
- Company name, role, location, salary range (if disclosed)
- One-sentence description of what the company does
- One-sentence description of what this role does

### Block 2 — CV Match
Score each dimension from _shared.md.
Be explicit about which CV lines match which JD requirements.
Identify the hardest requirement and whether candidate meets it.

### Block 3 — Level Assessment
- Is the level right? (IC3/IC4/Staff/Principal/Director)
- Signs of over-leveling or under-leveling?
- How does comp align with level if disclosed?

### Block 4 — Compensation Analysis
- Base, equity, bonus if mentioned
- Compare to candidate's target range from profile.yml
- Flag if compensation is missing (common red flag or just unlisted)

### Block 5 — Personalization
- Which 3 proof points from cv.md land hardest here?
- Which projects should lead the CV?
- What's the single sentence that makes this application personal?

### Block 6 — Interview Angle
- What's the hiring manager's likely top concern?
- What story should the candidate lead with?
- What question should the candidate ask at the end?

## Output

Full report per _shared.md format.
Also print summary to terminal.
