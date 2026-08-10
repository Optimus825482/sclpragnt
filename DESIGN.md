# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-10
- Primary product surfaces: Scalper terminal, charts, paper portfolio, settings, reports, chat and scan/replay views.
- Evidence reviewed: `frontend/app/layout.tsx`, `frontend/app/globals.css`, route pages under `frontend/app`, and shared components under `frontend/app/components`.
- Existing design documents, screenshots and brand exports were not present in the repository.

## Brand
- Personality: Focused, technical, calm and operational.
- Trust signals: Explicit PAPER / SALT OKUNUR labels, public-data wording, visible status, auditable logs and clear error states.
- Avoid: Decorative density that hides data, silent failures, real-money execution language and horizontal page scrolling.

## Product goals
- Goals: Make public-data paper trading readable at a glance, keep symbols and actions auditable, and make every core workflow usable on touch screens.
- Non-goals: Real-money execution, opaque automation and replacing evidence with simulated rows.
- Success signals: No page-level horizontal overflow at 320–768px, tables scroll inside their own containers, controls remain reachable, and long-running jobs expose progress/log state.

## Personas and jobs
- Primary personas: Paper-trading operator, strategy reviewer and developer diagnosing market/data flows.
- User jobs: Monitor signals and positions, inspect a symbol chart, adjust settings, review logs and compare strategy outcomes.
- Key contexts of use: Desktop terminal and handheld portrait use during live monitoring.

## Information architecture
- Primary navigation: Sidebar navigation with a compact mobile drawer.
- Core routes/screens: `/`, `/charts`, `/portfolio`, `/settings`, `/reports`, `/backtest`, `/signal-replay`, `/chat` and radar/analysis views.
- Content hierarchy: Current status and primary action first; evidence, tables and diagnostics below; destructive or irreversible actions require visible confirmation.

## Design principles
- Principle 1: Evidence before interpretation. Show source, status, timestamps and reasons.
- Principle 2: Responsive containment. Let data tables scroll locally; never let the page shell grow horizontally.
- Principle 3: Reuse the existing dark terminal language and shared controls before adding new patterns.
- Tradeoffs: Dense monospace data remains horizontally scrollable in tables, while surrounding headings, cards and controls wrap or stack for touch layouts.

## Visual language
- Color: Bunker/dark surfaces with neon green positive/active states, yellow warnings, red errors and blue informational states.
- Typography: Inter for prose and JetBrains Mono/monospace for labels, metrics, symbols and logs.
- Spacing/layout rhythm: Small gaps for data groups, 1rem card rhythm on mobile, bounded page shells and `min-width: 0` on flexible children.
- Shape/radius/elevation: Rounded cards and controls, subtle borders, restrained shadows and translucent dark overlays.
- Motion: Short transitions and live status indicators; respect `prefers-reduced-motion`.
- Imagery/iconography: Compact text/emoji icons already used by the product; no decorative imagery required for monitoring flows.

## Components
- Existing components to reuse: `Sidebar`, `TopBar`, `Card`, `SectionHeader`, `Button`, `Badge`, `SymbolLink`, `LiveTerminal` and table wrappers.
- New/changed components: Responsive rules in `globals.css`; mobile containment classes for terminal, settings, strategies and replay logs.
- Variants and states: Active/passive, loading, empty, error, disabled, running and paper-only states must remain visible.
- Token/component ownership: Shared layout and responsive tokens belong in `frontend/app/globals.css`; page-specific exceptions stay with the page/component.

## Accessibility
- Target standard: Practical WCAG 2.1 AA baseline for contrast, keyboard access and touch targets.
- Keyboard/focus behavior: Preserve visible focus rings, semantic buttons/links, local scroll regions and modal focus semantics already present.
- Contrast/readability: Keep status colors paired with text labels; do not use color as the only signal.
- Screen-reader semantics: Keep labels and dialog/table semantics; icon-only controls require accessible labels.
- Reduced motion and sensory considerations: Disable nonessential transitions under `prefers-reduced-motion`.

## Responsive behavior
- Supported breakpoints/devices: 320px minimum, portrait phones through 768px tablets, then desktop layouts from the existing Tailwind breakpoints.
- Layout adaptations: Mobile drawer navigation, stacked section headers, wrapped action groups, two-column metric cards where readable, and locally scrolling tables/logs.
- Touch/hover differences: Minimum roughly 44px interactive controls; hover is enhancement only and must not be required for meaning or action.

## Interaction states
- Loading: Show explicit loading text/spinners without changing page width.
- Empty: Explain what data is missing and how/when it will appear.
- Error: Keep errors visible in the normal surface and distinguish them from passive/empty states.
- Success: Confirm saves and completed scans without blocking the workflow.
- Disabled: Preserve disabled affordance and explain why when the context needs it.
- Offline/slow network, if applicable: Keep paper/public-data boundaries visible and allow retry/refresh paths.

## Content voice
- Tone: Concise, operational Turkish with familiar technical terms.
- Terminology: Use `PAPER`, `SALT OKUNUR`, `CANLI PUBLIC DATA`, `AKTİF`, `PASİF`, `HATA` consistently.
- Microcopy rules: State the action/result and reason; avoid claims that imply real execution or fabricated market data.

## Implementation constraints
- Framework/styling system: Next.js/React with Tailwind utilities and repository-owned CSS in `frontend/app/globals.css`.
- Design-token constraints: Extend existing bunker/neon palette, spacing, radii and shared UI components.
- Performance constraints: Keep live polling/WebSocket surfaces bounded and avoid layout work that causes page-wide reflow.
- Compatibility constraints: Mobile browsers with safe-area insets; PostgreSQL-backed public-data/paper-trading application.
- Test/screenshot expectations: Run the frontend build and targeted static checks; verify 320px, 375px, 768px and desktop widths when browser tooling is available.

## Open questions
- [ ] Confirm whether a browser screenshot/visual regression harness should be added for future mobile checks / owner: product / impact: medium.
