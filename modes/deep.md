# Mode: deep

**Triggered by:** `ops deep <company-name>`

## What This Mode Does

Deep research on a company before applying or interviewing.
Uses web search to gather current intel. Structures output as a brief.

## Research Sections

### 1. Company Brief
- What they do (1 sentence)
- Founded, HQ, stage (seed/Series X/public)
- Employee count (approximate)
- Key investors / acquirer if applicable
- Recent funding (if any, last 18 months)

### 2. Product & Tech
- Core product description
- Tech stack (public signals: job ads, engineering blog, StackShare)
- Recent product launches or pivots
- Open source activity (GitHub presence)

### 3. Business Health Signals
- Revenue indicators (if public or leaked)
- Growth signals: hiring pace, new offices, partnerships
- Risk signals: layoffs, leadership churn, negative press
- Glassdoor sentiment (if available)

### 4. Engineering Culture
- Engineering blog: exists? Active? Quality?
- How they talk about technical challenges in job ads
- Interview process (if known from Glassdoor/Blind/community)
- Remote/hybrid policy

### 5. Why This Company (for cover letters / interview)
3 specific, non-generic reasons a candidate might want to work there.
These become talking points in applications and interviews.
NOT: "I love your mission." YES: "The way you approached [specific technical problem] in [blog post] aligns with how I think about [problem]."

### 6. Red Flags
Anything that should give the candidate pause. Be honest.

## Output
Save to: `data/research/{company-slug}.md`
Print summary to terminal.
