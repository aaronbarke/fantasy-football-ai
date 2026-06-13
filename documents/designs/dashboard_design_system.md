# FFAI Design System

_Extracted from the existing FFAI codebase (Tailwind utility language + `globals.css` token layer) and refined toward a clean, data-forward sports-analytics aesthetic. Source of truth for the dashboard rebuild._

## Design Principles

1. **One focal point per view.** The ambient page background and a single accent moment (the Game Plan CTA) carry the "energy." Everything else is calm neutral surfaces. Green means *go / good / action* — never decoration.
2. **Data is the hero.** Numbers use tabular figures and a strong size/weight jump from their labels. Stats align in columns. Labels are quiet; values are loud.
3. **Whitespace over borders.** Group with spacing first, dividers second, boxes last. Generous padding (24px) inside cards.
4. **Restraint with color.** A mostly-neutral palette; green reserved for brand, positive state, the user's own row, and the primary CTA.

## Color Palette

### Brand / Accent (green)
| Token | Hex | Use |
|---|---|---|
| accent-50 | `#f0fdf4` | tint fills, hover backgrounds |
| accent-100 | `#dcfce7` | icon chips, soft highlights |
| accent-600 | `#16a34a` | **primary** — CTAs, focus rings, active state |
| accent-700 | `#15803d` | hover on primary, brand text |
| accent-800 | `#166534` | gradient depth |

### Neutrals — Light
| Token | Hex | Use |
|---|---|---|
| page | `#f6f8f7` | app background (+ ambient green radial glow) |
| surface | `#ffffff` | cards |
| border | `#e5e7eb` @ 70% | card borders (hairline) |
| text-1 | `#111827` | primary text, values |
| text-2 | `#6b7280` | body, secondary |
| text-3 | `#9ca3af` | labels, captions, tertiary |

### Neutrals — Dark
| Token | Hex | Use |
|---|---|---|
| page | `#05080f` | app background (+ layered aurora glows) |
| surface | `#111827` | cards |
| border | `#1f2937` @ 70% | card borders |
| text-1 | `#f3f4f6` | primary text |
| text-2/3 | `#9ca3af` | secondary / labels |

### Functional
| State | Light | Dark |
|---|---|---|
| positive | green-600 | green-400 |
| warning | amber-500/600 | amber-400 |
| danger | red-500/600 | red-400 |
| gold (1st place) | yellow-700 on yellow-100 | yellow-400 on yellow-900/50 |

## Typography

System sans (Tailwind default stack). Hierarchy by size + weight + tracking, not font family.

| Style | Spec | Use |
|---|---|---|
| Display | `text-3xl sm:text-4xl font-extrabold tracking-tight` | page title (league name) |
| Eyebrow | `text-xs font-semibold uppercase tracking-[0.12em] text-3` | context above title |
| Section label | `text-[11px] font-semibold uppercase tracking-[0.08em] text-3` | card/section headers |
| Stat value | `text-2xl font-extrabold tabular-nums` | metric numbers |
| Stat label | `text-[11px] font-medium uppercase tracking-wider text-3` | under/over a stat |
| Body | `text-sm text-2` | descriptions |
| Caption | `text-xs text-3` | meta, hints |

**Rule:** every number that sits in a column or compares against another number uses `tabular-nums`.

## Spacing

4px base. Page gutters `px-4`, max width `max-w-6xl`. Vertical rhythm between major sections: `mt-6`/`mt-8`. Card padding `p-6`. Inline gaps `gap-2`/`gap-3`/`gap-4`.

## Radius & Elevation

| Token | Value | Use |
|---|---|---|
| card | `rounded-2xl` (16px) | all surfaces |
| control | `rounded-lg` (8px) | buttons, inputs, chips |
| pill | `rounded-full` | badges, status, rank circles |

Shadows are subtle and layered (defined in `globals.css`): rest = 1px + 2px soft; hover = lift to 8–24px. Dark mode swaps to a hairline ring that glows green on hover. No hard drop shadows.

## Components

### Card
`rounded-2xl border border-gray-200/70 bg-white p-6 dark:border-gray-800/70` — inherits depth + hover from globals. The `bg-white` class is the dark-mode remap hook.

### Section header
Section label (see type) + optional 14px lucide icon in `text-gray-400`. No heavy bars.

### Stat block
Label (stat-label) above, value (stat-value, tabular) below. Centered in ribbon, left-aligned in cards.

### Primary CTA
`bg-green-600 text-white` icon-led card, arrow chip that nudges right on hover. The single saturated-green element on the page.

### Rank chip
`h-7 w-7 rounded-full` — 1st = gold, others = neutral; the user's own row gets a green tint + green text + "(you)".

### Buttons (ghost)
`border bg-white/transparent`, hover `bg-gray-50`. Used for sync/switcher — quiet, never competing with the CTA.

## Motion

| Token | Value |
|---|---|
| page-in | `opacity + translateY(4px)`, 0.25s ease-out (globals) |
| hover | 0.15–0.18s ease on bg/border/shadow/transform |
| press | `active:scale-[0.98]` on buttons (globals) |
| icon-led CTA | arrow `translate-x-0.5` on group-hover |

## Dark Mode

Driven by `.dark` class. Light utility classes (`bg-white`, `border-gray-200`, `text-gray-*`) are remapped in `globals.css`, so most components are theme-agnostic. Dark surfaces sit on the near-black page with green-tinted hairline rings instead of shadows.
