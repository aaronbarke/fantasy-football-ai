# Dashboard — UI Implementation Prompt

_Composed from `documents/designs/dashboard_design_system.md` + the dashboard's product spec. Implementation-ready for the existing Next.js 14 (App Router, TS, Tailwind, lucide-react) app._

## Aesthetic Principles

- **Minimalism with intent.** Remove every gradient and colored box that isn't earning attention. The ambient page background supplies richness; content stays clean.
- **Typographic hierarchy.** Loud values, quiet labels. Uppercase tracked labels; extrabold tabular numbers.
- **Whitespace.** Group by spacing; use hairline borders sparingly; one corner radius family (`rounded-2xl` surfaces, `rounded-lg` controls).
- **Color theory.** Neutral foundation, green as the single accent for brand / positive / action / the user's own data.

## Product Spec (dashboard)

**Goal:** at-a-glance command center for a connected fantasy team. Answer in 3 seconds: _How am I doing? Who do I play? Anything on fire? What should I do next?_

**Data available:** league (name, platform, season, scoring), roster (record, PF, PA, starters/bench, injuries), matchup (week, opponent record/PF), standings (ranked), AI start/sit record. League may be pre-draft (zeros) — must look intentional with empty/zero data. Team may be unclaimed → claim banner.

**Information hierarchy:**
1. **Identity** — who/what league am I looking at (+ quiet sync & switch controls).
2. **Vitals** — record, rank, PF, PA in a single segmented metric ribbon (tabular, aligned).
3. **This week** — matchup (broadcast VS layout) beside the Game Plan CTA (the accent moment).
4. **Roster health + Ask AI** — injury report; three icon-led quick-ask cards.
5. **League context** — standings, user row highlighted, 1st place flagged.

## Implementation Tasks

- Single page: `frontend/src/app/dashboard/page.tsx` (rebuild in place; this is a production app, not a mockup showcase — no throwaway variations).
- Reusable inline primitives: `SectionLabel`, `Stat` (ribbon segment), `Metric ribbon` card.
- Apply tokens from the design system exactly: section-label style, stat-value `tabular-nums`, `rounded-2xl` cards, green reserved for CTA / positive / user row.
- Replace the multi-gradient stack with: clean header → segmented metric ribbon → 2-col (matchup | game-plan+injuries) → quick asks → standings.
- Skeletons for loading (ribbon + cards). Honest empty states for pre-draft / no matchup / no injuries.
- Responsive: ribbon `grid-cols-2 → grid-cols-4`; week block stacks under `lg`.
- Preserve all existing behavior: `syncNow`, `claimTeam`, league `selectLeague`, quick-ask routing to `/chat?q=`, links to `/gameplan` and `/matchup`.
- Verify: `npx tsc --noEmit` clean.
