# Abdelrahman's design review

This work covers the visual system and printable scouting report assigned in section 6.2 of the team plan. The branch starts from `origin/main` at `4bcaf68`. Ahmed's design approval is pending. These changes are a review proposal, not an approved design or a merged release.

## Audit

| Finding in the starting screens | Change |
| --- | --- |
| Desktop navigation wraps into several competing rows | Persistent desktop side navigation and a horizontally scrollable phone navigation |
| Secondary text and chart axes are too faint | Stronger shared text palette and chart labels |
| Small buttons and filter chips are difficult to touch | Shared controls use a 44 px minimum touch height |
| Cards, fields and tables use different spacing | Shared tokens and primitives establish one hierarchy |
| Wide integrity evidence expands the phone viewport | Grid children can shrink; tables scroll in their own region |
| Keyboard focus varies by control | Global visible focus, a skip link and keyboard-operated shared tabs |
| No selectable reading direction | Persistent RTL layout control, logical shell spacing, charts and numeric inputs kept LTR |
| Loading and empty content lack structure, and rejected reads can leave permanent skeletons | Shared skeleton, empty and error treatments; explicit retry states for the coach, profile, search, oversight and integrity screens |
| Scouting report is only a dark screen | A4 print layout, monochrome charts with distinct filled/outline markers, repeated source/date footer, table headers and explicit page-break rules |

## Design contract

`app/tokens.css` defines surfaces, text, semantic colours, type, spacing, radius and shadow. `tailwind.config.ts` maps existing slate utilities to the stronger palette so screens share it without changing their data requests. `components/ui.tsx` owns cards, buttons, inputs, tables, tags, tabs and states. SVG charts remain hand written. No production dependency was added.

Role accents keep their meaning: green for the coach, amber for the scout, violet for the federation and rose for the player. An alert does not become a role accent. Forecast bands, uncertain comparisons, withheld values, consent and source caveats remain visible.

## Review material and reproduction

The visual script renders real frontend routes in Firefox with small invented API responses intercepted by Playwright. Fixtures never enter the application bundle. It checks 360 and 1280 px, LTR and RTL, records browser errors and viewport overflow, checks direction persistence and keyboard access, and captures empty/error states. Chromium produces a sample PDF from the same invented report. These checks do not test database access, authentication or backend policy.

Start the built web app, then from `apps/web`:

```powershell
npm run build
npm run start
# In another terminal; use an existing Playwright installation.
# NORTHSTAR_PLAYWRIGHT can point to its absolute index.mjs if it is not on the module path.
node scripts/check-contrast.mjs
node scripts/design-review.mjs
```

Optional variables: `DESIGN_BASE_URL`, `DESIGN_OUTPUT`, `DESIGN_PHASE` (`before` or `after`). `DESIGN_CHECKS_ONLY=1` repeats the state/keyboard/print checks using existing captures; `DESIGN_PRINT_ONLY=1` regenerates only the PDF. Default output is `.next/design-review`, which is ignored by Git. Capture `before` against a separate untouched checkout, then `after` against this branch, using the same script and fixtures. The screenshots are design proposals for Ahmed to review; RTL screenshots are not evidence of a fully translated Arabic interface.

## Remaining review gates

- Ahmed must approve the proposed layouts. The team plan's per-screen approval and merge steps have not happened.
- Run the existing real-stack Firefox suite in `tests/e2e` before merge; synthetic visual checks cannot replace it. Execution results are recorded in `verification.md`.
- The RTL layout preserves Arabic names and chart axes. Existing English domain copy is not translated by the layout control.
- The app has no separate identity-edit route. The visual review includes the existing profile measurement editor, not a newly invented editing workflow.
- A report's original source is printed only when the current response supplies it. Otherwise the footer explicitly says the source was not supplied.
- Contrast checks cover shared text/surface tokens. A full control-by-control accessibility audit is still a review task.
