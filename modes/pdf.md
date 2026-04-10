# Mode: pdf

**Triggered by:** `ops pdf <report-id>`

## What This Mode Does

Generates a tailored ATS-optimized PDF CV for a specific evaluated offer.
Reads the existing report for context. Does NOT re-evaluate.

## Steps

1. Load report #{id} from reports/
2. Extract: keywords list, archetype, tailoring notes from report
3. Load cv.md and templates/cv-template.html
4. Apply tailoring rules from _shared.md:
   - Inject top 15 keywords (summary × 3, first bullet of each role × 1, skills)
   - Reorder bullets by relevance
   - Shift summary to match archetype
   - Select top 3–4 projects
5. Render HTML with injected content
6. Convert to PDF via WeasyPrint → output/{###}-{slug}-cv.pdf
7. Confirm path to user

## ATS Rules
- No tables, no columns, no text boxes
- All text selectable (no images of text)
- Standard fonts: system fonts only (no custom embeds needed for ATS)
- Sections: Summary, Experience, Projects, Education, Skills
- One page preferred; two pages max for 10+ years experience
