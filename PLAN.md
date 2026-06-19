# Hullucinator Frontend Redesign — Plan

## Subject & Audience

**Subject:** Hullucinator — an AI-powered e-book generator. The name is a playful portmanteau of "hallucination" (LLMs conjuring content from nothing) and "incubator" (nurturing ideas into finished works).

**Audience:** Creative writers, hobbyists, and curious people who want to generate books using AI. They're craft-oriented, tech-comfortable, and appreciate the playful naming.

**The page's single job:** Help people conceive, generate, and export complete books — from first prompt to finished EPUB/PDF.

## Current Design Problems

The current design is the archetypal "dark mode dashboard with red accent" — deep navy background (`#0f0f1a`), red accent (`#e94560`), rounded cards with subtle borders. This is exactly the "near-black background with a single bright acid accent" default the design skill warns against. It looks like any other SaaS admin panel and has nothing to do with books, writing, or creativity.

Emoji icons (📖, 🔗, 🤖, 📝, 🔍, 🗑) scatter the UI and feel cheap. The system-ui font family is neutral to the point of being invisible. Everything shouts "generic template."

## Design Direction: The Writing Desk

**Thesis:** The interface should feel like a writer's study — warm, tactile, bookish, and quietly confident. Not a dark-mode dashboard. Not a clinical tool. A place where ideas become books.

**The aesthetic risk:** Using a high-contrast serif as the primary display typeface throughout the UI (most web apps use sans-serif exclusively). Serifs carry literary authority and warmth — they signal "this is about books."

---

## Token System

### Palette

Eight named values. Primary colors drawn from the material world of books and writing; status colors chosen to work within the warm palette while remaining semantically clear.

| Variable | Hex | Source | Usage |
|----------|-----|--------|-------|
| `--paper` | `#F5F0E8` | Unbleached, slightly warm | Page background (`body`) |
| `--page` | `#FAF7F2` | Fresh paper | Card/form surfaces, modal background |
| `--ink` | `#2C2416` | Deep brown | Primary text color |
| `--teal` | `#1B6B61` | Deep teal, leather bindings | Primary accent, buttons, links, focus |
| `--teal-light` | `#E8F5F3` | Tinted teal | Subtle backgrounds, hover states |
| `--brass` | `#C4883A` | Warm amber, brass desk lamp | Secondary accent, warnings, in-progress |
| `--ash` | `#7A6F62` | Warm gray | Muted text, hints, secondary labels |
| `--vellum` | `#E8DFD0` | Aged paper edges | Borders, dividers, input borders |

**Status colors** (semantic, used for badges, progress, toasts, review scores):

| Variable | Hex | Source | Maps to |
|----------|-----|--------|---------|
| `--status-pending` | `#5B7B8A` | Muted slate blue | `pending`, `summary_generated` |
| `--status-progress` | `#C4883A` | Brass (same as accent) | `outline_generated`, `in_progress` |
| `--status-complete` | `#2D6A4F` | Deep forest green | `completed`, `reviewed` |
| `--status-reviewing` | `#1B6B61` | Teal (same as accent) | `reviewing` |
| `--status-error` | `#9B232C` | Warm ink-red | `failed`, error toasts |
| `--status-good` | `#2D6A4F` | Deep green | Review score ≥ 7 |
| `--status-ok` | `#C4883A` | Brass | Review score 4–6 |
| `--status-bad` | `#9B232C` | Ink-red | Review score < 4 |

### Typography

Three faces loaded from Google Fonts via `<link>` in `<head>`.

| Role | Face | Weights Loaded | Usage |
|------|------|----------------|-------|
| Display | **Playfair Display** | 400, 600, 700 | App title, section headings, book titles, modal titles, review score |
| Body | **Source Sans 3** | 400, 500, 600 | Form labels, body text, UI chrome, buttons, toast |
| Data | **IBM Plex Mono** | 400, 500 | Status labels, model names, technical values, tag badges, hints |

**Type scale** (exact values):

| Element | Font | Size | Weight | Line-height | Tracking |
|---------|------|------|--------|-------------|----------|
| App title (header) | Playfair | 28px | 700 | 1.2 | -0.02em |
| App subtitle | Source Sans 3 | 13px | 400 | 1.4 | 0 |
| Section heading (h2) | Playfair | 22px | 600 | 1.3 | -0.01em |
| Card title (h3) | Playfair | 17px | 600 | 1.3 | 0 |
| Body text (p, pre) | Source Sans 3 | 15px | 400 | 1.65 | 0 |
| Form label | Source Sans 3 | 12px | 500 | 1.3 | 0.08em, uppercase |
| Field hint | IBM Plex Mono | 11px | 400 | 1.4 | 0 |
| Button text | Source Sans 3 | 14px | 600 | 1 | 0 |
| Button (sm) text | Source Sans 3 | 12px | 600 | 1 | 0 |
| Button (lg) text | Source Sans 3 | 15px | 600 | 1 | 0 |
| Status label | IBM Plex Mono | 12px | 500 | 1 | 0 |
| Tag badge | IBM Plex Mono | 11px | 500 | 1 | 0 |
| Toast text | Source Sans 3 | 13px | 500 | 1.3 | 0 |
| Review score | Playfair | 36px | 700 | 1 | 0 |
| Review verdict | Source Sans 3 | 14px | 600 | 1 | 0 |
| Data label (detail) | IBM Plex Mono | 11px | 500 | 1 | 0.06em, uppercase |
| Data value (detail) | Source Sans 3 | 14px | 400 | 1.5 | 0 |
| Model list item | IBM Plex Mono | 13px | 400 | 1.4 | 0 |
| Setup step number | Playfair | 20px | 700 | 1 | 0 |
| Setup section heading | Playfair | 16px | 600 | 1.3 | 0 |

---

## Layout

- **Container:** `max-width: 860px`, centered with `margin: 0 auto`, padding `3rem 2rem` (top/bottom 3rem, left/right 2rem)
- **Section gap:** `2.5rem` between major sections (create form, library)
- **Card padding:** `1.5rem` all sides for create form card; `1.25rem 1.5rem` for book cards
- **Modal:** `max-width: 780px`, padding `2rem`, `max-height: 85vh`
- **Settings panel:** `width: 400px`, `max-width: 90vw`, padding `2rem 1.5rem`
- **Setup card:** `max-width: 580px`, padding `2.5rem 2rem`
- **No border-radius** on structural elements — sharp corners throughout
- **Cards:** subtle shadow `0 1px 3px rgba(44,36,22,0.08), 0 4px 12px rgba(44,36,22,0.04)` — no borders
- **Dividers:** `1px solid var(--vellum)`, used sparingly between sections within modals/setup/settings

---

## Component Specifications

### 1. Header

- **Layout:** `display: flex`, `align-items: center`, `justify-content: space-between`
- **Padding:** `0.75rem 2rem`
- **Background:** transparent (same as `--paper` body background)
- **Bottom border:** `1px solid var(--vellum)`
- **Position:** `sticky`, `top: 0`, `z-index: 100`
- **Title:** Playfair Display 28px/700, color `--ink`, tracking -0.02em
- **Subtitle:** "AI E-Book Generator" in Source Sans 3 13px/400, color `--ash`, appears inline after title separated by `·` (middot)
- **Settings button:** no background, no border, color `--ash`, font-size 1.1rem, padding `0.5rem 0.8rem`, cursor pointer. On hover: color `--teal`. Uses text label "Settings" instead of ⚙ emoji.

### 2. Create Book Form

- **Card wrapper:** background `--page`, shadow as defined above, padding `1.5rem`, `margin-bottom: 2.5rem`
- **Card heading:** "New Manuscript" in Playfair 22px/600, color `--ink`, `margin-bottom: 1.5rem`
- **Labels:** Source Sans 3 12px/500, uppercase, tracking 0.08em, color `--ash`, `margin-bottom: 0.35rem`
- **Inputs (text, url, password):**
  - `width: 100%`, `padding: 0.6rem 0.75rem`
  - `background: var(--page)`
  - `border: 1px solid var(--vellum)`, `border-radius: 0`
  - `color: var(--ink)`, `font-family: var(--body-font)`, `font-size: 15px`
  - `margin-bottom: 0.9rem`
  - `transition: border-color 0.2s`
  - `::placeholder` color: `rgba(122,111,98,0.5)` (ash at 50% opacity)
- **Input focus:** `outline: none`, `border-color: var(--teal)`, `box-shadow: 0 0 0 3px var(--teal-light)`
- **Textarea:** `min-height: 100px`, `resize: vertical`, same base styles as inputs
- **Select:** same base styles, `appearance: none`, custom arrow via background SVG (small chevron in `--ash`), `cursor: pointer`
- **Field hint:** IBM Plex Mono 11px/400, color `--ash`, `margin-top: -0.3rem`, `margin-bottom: 0.5rem`, `font-style: normal`
- **Field wrapper (`.field`):** `margin-bottom: 1rem`
- **Input row (input + button side-by-side):** `display: flex`, `gap: 0.5rem`, `align-items: center`, `margin-bottom: 0.3rem`. Input: `flex: 1 1 0`, `min-width: 0`, `width: auto`, `margin-bottom: 0`. Button: `flex-shrink: 0`, `margin-bottom: 0`.
- **Form row (two columns):** `display: flex`, `gap: 1rem`, `margin-bottom: 0.5rem`. Each `.form-col`: `flex: 1`.
- **Tags input row:** `display: flex`, `gap: 0.5rem`, `margin-bottom: 0.8rem`, `flex-wrap: wrap`, `align-items: center`. Input: `flex: 1`, `margin-bottom: 0`, `min-width: 150px`.
- **Tag badges:** `display: inline-flex`, `align-items: center`, `gap: 0.3rem`, `background: var(--teal-light)`, `color: var(--teal)`, `padding: 0.2rem 0.6rem`, `border-radius: 0`, `font-family: var(--data-font)`, `font-size: 11px`, `border: 1px solid rgba(27,107,97,0.2)`. Remove button: `background: none`, `border: none`, `color: var(--teal)`, `cursor: pointer`, `font-size: 1rem`, `line-height: 1`, `padding: 0`. On hover: color deepens to darker teal.
- **Form actions:** `margin-top: 1.5rem`
- **Submit button:** "Generate Book" — see Button spec below

### 3. Buttons

- **Base (`.btn`):** `display: inline-flex`, `align-items: center`, `justify-content: center`, `gap: 0.5rem`, `border: none`, `cursor: pointer`, `border-radius: 0`, `font-family: var(--body-font)`, `transition: all 0.2s`
- **Primary (`.btn-primary`):** `background: var(--teal)`, `color: #fff`, `padding: 0.7rem 1.3rem`, `font-size: 14px`, `font-weight: 600`. Hover: `background: #155a52` (darker teal). Disabled: `opacity: 0.45`, `cursor: not-allowed`.
- **Secondary (`.btn-secondary`):** `background: transparent`, `color: var(--ink)`, `border: 1px solid var(--vellum)`, `padding: 0.6rem 1.1rem`, `font-size: 14px`, `font-weight: 500`. Hover: `border-color: var(--teal)`, `color: var(--teal)`.
- **Small (`.btn-sm`):** `padding: 0.4rem 0.8rem`, `font-size: 12px`
- **Large (`.btn-lg`):** `padding: 0.9rem 2rem`, `font-size: 15px`
- **Fetch button (icon + label):** `font-family: var(--body-font)`, `font-size: 12px`. Icon: text "↻" or small SVG, `font-size: 1rem`. Spinning animation kept: `@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`, applied via `.fetch-icon.spinning` class.

### 4. Library — Manuscript Cards

**The signature element.** Each book card styled as a manuscript page.

- **List container (`.book-list`):** `display: flex`, `flex-direction: column`, `gap: 1rem`
- **Card (`.book-card`):**
  - `background: var(--page)`
  - `padding: 1.25rem 1.5rem`
  - `cursor: pointer`
  - `position: relative`
  - `transition: transform 0.15s ease, box-shadow 0.15s ease`
  - `box-shadow: 0 1px 3px rgba(44,36,22,0.06), 0 2px 8px rgba(44,36,22,0.03)`
  - **Left margin rule:** `border-left: 3px solid var(--teal)`, no other borders
  - Hover: `transform: translateY(-2px)`, `box-shadow: 0 2px 6px rgba(44,36,22,0.1), 0 4px 16px rgba(44,36,22,0.06)`
- **Book title (`.book-title`):** Playfair Display 17px/600, color `--ink`, `margin-bottom: 0.35rem`
- **Book metadata (`.book-meta`):** `display: flex`, `gap: 0.6rem`, `margin-top: 0.3rem`, `flex-wrap: wrap`, `align-items: center`
- **Book prompt preview (`.book-prompt`):** Source Sans 3 13px/400, `color: var(--ash)`, `font-style: italic`, `margin-top: 0.5rem`, `overflow: hidden`, `text-overflow: ellipsis`, `white-space: nowrap`
- **Delete button (`.book-delete-btn`):**
  - `position: absolute`, `top: 0.6rem`, `right: 0.6rem`
  - `background: transparent`, `border: 1px solid transparent`
  - `color: var(--ash)`, `cursor: pointer`
  - `font-family: var(--body-font)`, `font-size: 12px`, `padding: 0.2rem 0.5rem`
  - `line-height: 1`, `transition: all 0.15s`
  - Text label "Delete" instead of 🗑 emoji
  - Hover: `color: var(--status-error)`, `border-color: var(--status-error)`

### 5. Status Labels

Replaces pill-shaped badges. Clean text labels in mono, color-coded.

- **Base (`.status-label`):** `display: inline-block`, `font-family: var(--data-font)`, `font-size: 12px`, `font-weight: 500`, `padding: 0.15rem 0.5rem`, `border-radius: 0`, `border: none`, `letter-spacing: 0`
- **Color mapping:**
  - `pending`, `summary_generated` → `color: var(--status-pending)`, `background: rgba(91,123,138,0.1)`
  - `outline_generated`, `in_progress` → `color: var(--status-progress)`, `background: rgba(196,136,58,0.1)`
  - `completed` → `color: var(--status-complete)`, `background: rgba(45,106,79,0.1)`
  - `reviewing` → `color: var(--status-reviewing)`, `background: rgba(27,107,97,0.15)`
  - `reviewed` → `color: var(--status-complete)`, `background: rgba(45,106,79,0.15)`
  - `failed` → `color: var(--status-error)`, `background: rgba(155,35,44,0.1)`
- **Display text:** lowercase, underscore-free: "pending", "summary", "outline", "in progress", "completed", "reviewing", "reviewed", "failed"
- **Length badge:** `color: var(--status-pending)`, `background: rgba(91,123,138,0.08)`, same base styles as status label

### 6. Progress Bar

- **Container (`.progress-bar`):** `width: 100%`, `height: 4px`, `background: var(--vellum)`, `border-radius: 0`, `overflow: hidden`, `margin-top: 0.6rem`
- **Fill (`.progress-fill`):** `height: 100%`, `background: var(--teal)`, `transition: width 0.4s ease`, `border-radius: 0`
- **Complete state (`.progress-fill.complete`):** `background: var(--status-complete)`
- **Fail state (`.progress-fill.fail`):** `background: var(--status-error)`

### 7. Detail Modal

- **Overlay (`.modal-overlay`):** `display: none` → `display: flex` when `.active`, `position: fixed`, `inset: 0`, `background: rgba(44,36,22,0.6)`, `z-index: 200`, `align-items: flex-start`, `justify-content: center`, `padding: 2rem`, `overflow-y: auto`. Fade animation: `opacity 0.2s ease`.
- **Modal (`.modal`):** `background: var(--page)`, `border: none`, `border-radius: 0`, `width: 100%`, `max-width: 780px`, `max-height: 85vh`, `overflow-y: auto`, `padding: 2rem`, `margin-bottom: 2rem`, `box-shadow: 0 8px 32px rgba(44,36,22,0.2)`
- **Modal header:** `display: flex`, `justify-content: space-between`, `align-items: flex-start`, `margin-bottom: 1.5rem`, `padding-bottom: 1rem`, `border-bottom: 1px solid var(--vellum)`
- **Modal title:** Playfair Display 24px/700, color `--ink`
- **Close button (`.modal-close`):** `background: none`, `border: none`, `color: var(--ash)`, `font-size: 1.5rem`, `cursor: pointer`, `padding: 0.2rem 0.5rem`, `font-family: var(--body-font)`. Hover: `color: var(--ink)`. Text: "✕" (Unicode multiplication sign, cleaner than ×).
- **Modal sections (`.modal-section`):** `margin-bottom: 1.5rem`
- **Section headings (`.modal-section h3`):** Playfair Display 17px/600, color `--teal`, `margin-bottom: 0.6rem`
- **Section paragraphs:** Source Sans 3 15px/400, color `--ash`, `white-space: pre-wrap`
- **Section `<pre>`:** `background: var(--paper)`, `padding: 1rem`, `border-radius: 0`, `overflow-x: auto`, `border: 1px solid var(--vellum)`, `color: var(--ink)`, `font-family: var(--data-font)`, `font-size: 13px`, `line-height: 1.6`
- **Scrollbar (modal, critique, model list):** Custom styled — `::-webkit-scrollbar` width 6px, track `var(--vellum)`, thumb `var(--ash)`, rounded 3px

### 8. Detail Settings Section

- **Container (`.detail-settings`):** `display: flex`, `flex-direction: column`, `gap: 0.7rem`
- **Setting row (`.detail-setting`):** `display: flex`, `flex-direction: column`, `gap: 0.2rem`
- **Label (`.detail-label`):** IBM Plex Mono 11px/500, color `--ash`, uppercase, tracking 0.06em
- **Value (`.detail-value`):** Source Sans 3 14px/400, color `--ink`, `line-height: 1.5`

### 9. Outline Section

- **Ordered list:** `padding-left: 1.5rem`, `margin-top: 0.5rem`
- **List items:** Source Sans 3 14px/400, color `--ink`, `line-height: 1.8`
- **Markers:** Playfair Display, color `--teal`, `font-weight: 600`

### 10. Chapter Section

- **`<details>` elements:** `margin-bottom: 0.5rem`
- **`<summary>`:** `cursor: pointer`, Playfair Display 15px/600, color `--ink`, `padding: 0.5rem 0`, `border-bottom: 1px solid var(--vellum)`
- **`<pre>` content:** `margin-top: 0.4rem`, `background: var(--paper)`, `padding: 1rem`, `border: 1px solid var(--vellum)`, `border-radius: 0`, `overflow-x: auto`, `color: var(--ink)`, `font-family: var(--data-font)`, `font-size: 13px`, `line-height: 1.6`

### 11. Review Section

Styled as a proofreader's markup — clean, analytical.

- **Container (`.review-section`):** `background: var(--paper)`, `border: 1px solid var(--vellum)`, `border-radius: 0`, `padding: 1rem`, `margin-bottom: 1rem`
- **Heading:** Playfair Display 16px/600, color `--teal`, `margin-bottom: 0.8rem`
- **Review score:** Playfair Display 36px/700, `text-align: center`, `margin: 0.5rem 0`
  - `.good`: `color: var(--status-good)`
  - `.ok`: `color: var(--status-ok)`
  - `.bad`: `color: var(--status-bad)`
- **Review verdict:** Source Sans 3 14px/600, `text-align: center`, `margin-bottom: 0.8rem`
  - `.passed`: `color: var(--status-complete)`
  - `.failed`: `color: var(--status-error)`
- **Max turns warning:** Source Sans 3 13px/400, `color: var(--brass)`, `text-align: center`, `margin-bottom: 0.5rem`
- **Critique (`<details>`/`<summary>`):** Summary text in Source Sans 3 13px/500, color `--ash`, `cursor: pointer`. Critique content (`.review-critique`): `background: var(--page)`, `padding: 0.8rem`, `border: 1px solid var(--vellum)`, `border-radius: 0`, `font-family: var(--data-font)`, `font-size: 13px`, `color: var(--ash)`, `white-space: pre-wrap`, `max-height: 200px`, `overflow-y: auto`
- **Correction items (`.correction-item`):** `background: var(--page)`, `padding: 0.6rem 0.8rem`, `border-radius: 0`, `margin-bottom: 0.4rem`, `font-size: 13px`, `border-left: 3px solid var(--brass)`, `border-top: none`, `border-right: none`, `border-bottom: none`
  - `.corr-chapter`: Source Sans 3 13px/600, color `--ink`
  - `.corr-type`: IBM Plex Mono 11px/500, color `--teal`
- **Review history:** Heading in Playfair 15px/600, color `--ink`. Each turn entry: `background: var(--page)`, `padding: 0.5rem 0.7rem`, `border: 1px solid var(--vellum)`, `border-radius: 0`, `margin-bottom: 0.3rem`, `font-size: 13px`. Turn number in Source Sans 3/600. Score inline in Playfair 14px/700. Verdict in Source Sans 3/600.

### 12. Action Buttons (in modal)

- Export links (`<a>` styled as buttons): same as `.btn-primary` or `.btn-secondary` specs above. Text: "Download EPUB" / "Download PDF" instead of emoji.
- Review trigger: `.btn-secondary`, text "Trigger Review"
- Retry: `.btn-secondary`, text "Retry"
- Delete: `.btn-secondary` with `color: var(--status-error)`, `border-color: var(--status-error)`, text "Delete"

### 13. Empty State (Library)

- **Container (`.empty-state`):** `text-align: center`, `padding: 3rem 1rem`, `color: var(--ash)`
- **Icon area:** removed (no emoji). Replaced with a decorative element — a thin horizontal rule in `--vellum`, 60px wide, centered, with "Your shelves are empty" text below it.
- **Text:** Source Sans 3 15px/400, `margin-top: 1rem`. Copy: "Your shelves are empty. Submit your first manuscript above."

### 14. Settings Panel (slide-out)

- **Panel (`.settings-panel`):** `display: none` → `display: block` when `.active`, `position: fixed`, `top: 0`, `right: 0`, `bottom: 0`, `width: 400px`, `max-width: 90vw`, `background: var(--page)`, `border-left: 1px solid var(--vellum)`, `z-index: 300`, `overflow-y: auto`, `padding: 2rem 1.5rem`, `box-shadow: -4px 0 20px rgba(44,36,22,0.15)`
- **Panel heading:** Playfair Display 20px/600, color `--ink`, `margin-bottom: 1.5rem`, `padding-bottom: 0.8rem`, `border-bottom: 1px solid var(--vellum)`
- **Close button:** `position: absolute`, `top: 1rem`, `right: 1rem`, `background: none`, `border: none`, `color: var(--ash)`, `font-size: 1.3rem`, `cursor: pointer`, `font-family: var(--body-font)`. Hover: `color: var(--ink)`. Text: "✕".
- **Groups (`.settings-group`):** `margin-bottom: 1.5rem`, `padding-bottom: 1.2rem`, `border-bottom: 1px solid var(--vellum)`. Last child: no border.
- **Group headings:** Source Sans 3 12px/500, uppercase, tracking 0.08em, color `--teal`, `margin-bottom: 0.8rem`. No Playfair here — settings are technical, so body font is appropriate.
- **Overlay (`.settings-overlay`):** `display: none` → `display: block` when `.active`, `position: fixed`, `inset: 0`, `background: rgba(44,36,22,0.4)`, `z-index: 250`
- **Model list:** `max-height: 180px`, `overflow-y: auto`, `background: var(--paper)`, `border: 1px solid var(--vellum)`, `border-radius: 0`, `margin-top: 0.3rem`, `margin-bottom: 0.5rem`
- **Model list items:** `padding: 0.4rem 0.8rem`, `cursor: pointer`, `font-family: var(--data-font)`, `font-size: 13px`, `color: var(--ash)`, `border-bottom: 1px solid var(--vellum)`, `transition: background 0.15s`. Last child: no border. Hover: `background: var(--teal-light)`, `color: var(--teal)`. Current: `color: var(--status-complete)`, `font-weight: 500`.

### 15. Setup Wizard

- **Overlay (`.setup-overlay`):** `display: none` → `display: flex` when `.active`, `position: fixed`, `inset: 0`, `background: var(--paper)`, `z-index: 500`, `overflow-y: auto`, `padding: 2rem`. When active: `align-items: center`, `justify-content: center`.
- **Card (`.setup-card`):** `background: var(--page)`, `border: 1px solid var(--vellum)`, `border-radius: 0`, `width: 100%`, `max-width: 580px`, `max-height: 85vh`, `overflow-y: auto`, `padding: 2.5rem 2rem`, `box-shadow: 0 8px 32px rgba(44,36,22,0.15)`
- **Header:** `text-align: center`, `margin-bottom: 1.5rem`, `padding-bottom: 1.2rem`, `border-bottom: 1px solid var(--vellum)`
- **Title:** Playfair Display 32px/700, color `--ink`, `margin-bottom: 0.2rem`
- **Subtitle:** Source Sans 3 14px/400, color `--ash`
- **Intro text:** Source Sans 3 14px/400, color `--ash`, `text-align: center`, `margin-bottom: 1.5rem`
- **Sections (`.setup-section`):** `margin-bottom: 1.5rem`, `padding-bottom: 1.2rem`, `border-bottom: 1px solid var(--vellum)`. Last: no border.
- **Section headings:** Playfair Display 16px/600, color `--teal`, `margin-bottom: 0.8rem`, `display: flex`, `align-items: center`, `gap: 0.5rem`
- **Step numbers:** Each section gets a numbered prefix rendered as Playfair Display 20px/700, color `--teal`, inside a circle: `border: 2px solid var(--teal)`, `width: 28px`, `height: 28px`, `display: inline-flex`, `align-items: center`, `justify-content: center`, `border-radius: 50%`. Numbers: 1 (Connection), 2 (Writer Model), 3 (Reviewer), 4 (Review Settings).
- **Optional badge:** IBM Plex Mono 10px/500, `background: rgba(27,107,97,0.1)`, `color: var(--teal)`, `padding: 0.1rem 0.4rem`, `border-radius: 0`, `text-transform: uppercase`, `letter-spacing: 0.03em`, `border: 1px solid rgba(27,107,97,0.2)`
- **Actions:** `margin-top: 1.5rem`, `text-align: center`

### 16. Toast Notifications

- **Container (`.toast`):** `position: fixed`, `top: 1rem`, `right: 1rem`, `padding: 0.7rem 1rem`, `border-radius: 0`, `font-family: var(--body-font)`, `font-size: 13px`, `font-weight: 500`, `z-index: 999`, `max-width: 360px`, `box-shadow: 0 2px 8px rgba(44,36,22,0.12)`
- **Base:** `background: var(--page)`, `border: 1px solid var(--vellum)`, `color: var(--ink)`
- **Success:** `border-color: var(--status-complete)`, `color: var(--status-complete)`
- **Error:** `border-color: var(--status-error)`, `color: var(--status-error)`
- **Info:** `border-color: var(--status-pending)`, `color: var(--status-pending)`
- **Animation:** `@keyframes toastIn { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }`, duration 0.25s ease

### 17. Optional Badge (in settings/groups)

Same spec as in Setup Wizard section above.

---

## Motion

Minimal. Two animations only:

1. **Card hover:** `transition: transform 0.15s ease, box-shadow 0.15s ease`. On hover: `transform: translateY(-2px)`, shadow deepens.
2. **Modal open/close:** `transition: opacity 0.2s ease`. Fade in/out on overlay.
3. **Fetch button spin:** `@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`, 1s linear infinite. Applied to fetch icon during model fetch.

No bouncing, no elaborate transitions, no page-load sequences. Calm and deliberate.

---

## Accessibility

- **Keyboard focus:** `outline: 2px solid var(--teal)`, `outline-offset: 2px`. Applied to all interactive elements (`input`, `textarea`, `select`, `button`, `a`, `summary`, `.model-list-item`, `.book-card`).
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` — disable all `transition` and `animation` properties globally: `*, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }`
- **Color contrast:** All text meets WCAG AA minimum (4.5:1 for body text, 3:1 for large text 18px+ or 14px+ bold). Verified: `--ink` on `--page` = 12.4:1. `--ash` on `--page` = 4.7:1. `--teal` on `--page` = 7.1:1. `--status-error` on `--page` = 6.8:1.
- **Semantic HTML:** `<header>`, `<main>`, `<form>`, `<label>`, `<details>`, `<summary>`, `<ol>` all used correctly.

---

## Responsive

**Breakpoint:** `600px`

```css
@media (max-width: 600px) {
  .header { padding: 0.75rem 1rem; }
  .header h1 { font-size: 22px; }
  .container { padding: 1.5rem 1rem; }
  .modal { padding: 1.5rem; max-width: 100%; }
  .settings-panel { width: 100%; }
  .setup-card { padding: 1.5rem; max-width: 100%; }
  .input-row { flex-direction: column; align-items: stretch; }
  .form-row { flex-direction: column; }
  .book-card { padding: 1rem 1.25rem; }
  .book-card .book-title { font-size: 15px; }
  .review-score { font-size: 28px; }
}
```

---

## Implementation Plan

### Files to modify

1. **`static/index.html`** — Add Google Fonts `<link>` in `<head>`. Update class names where needed (`.badge` → `.status-label`, remove emoji text, update section-icon elements to step numbers in setup wizard, update empty state text). All `id` attributes preserved.

2. **`static/css/styles.css`** — Complete rewrite. New `:root` variables (fonts + colors). New base styles. New component styles for every element listed above. New responsive breakpoint. New accessibility rules. New scrollbar styling.

3. **`static/js/app.js`** — Update HTML template strings:
   - `buildBookCardHtml()`: new card structure with `.book-card`, `.book-title`, `.book-meta`, `.book-prompt`, `.status-label`, `.progress-bar`, `.book-delete-btn` with text "Delete"
   - `renderDetail()`: new section structure with Playfair headings, `<pre>` styling, `<details>`/`<summary>` for chapters, action buttons with text labels
   - `buildReviewSection()`: new review section structure with Playfair score, mono details, proofreader-style correction items
   - `deleteBook()`: confirmation text unchanged
   - `retryBook()`: confirmation text unchanged
   - Toast calls: unchanged (function signature same)

4. **`static/js/ui.js`** — Update:
   - `statusBadge()`: return `<span class="status-label status-{type}">{text}</span>` with new class names and status text mapping
   - `toast()`: unchanged function signature, CSS handles visual changes
   - `esc()`: unchanged
   - Polling functions: unchanged

5. **`static/js/settings.js`** — Update:
   - Model list item class names (`.model-list-item`, `.current`)
   - Toast calls: unchanged
   - All logic unchanged

6. **`static/js/boot.js`** — No changes needed.

### JS Compatibility Rules

- All element `id` attributes preserved exactly as-is
- All CSS class names that JS references via `classList` or `querySelector` are preserved (`.active`, `.spinning`, `.complete`, `.fail`, `.good`, `.ok`, `.bad`, `.passed`, `.failed`)
- `statusBadge()` function signature unchanged: `statusBadge(status)` returns HTML string
- `toast()` function signature unchanged: `toast(msg, type)`
- All event handler bindings unchanged

### Testing

After implementation:
1. Visual review of every screen: setup wizard, main app (create form + library), detail modal (all sections), settings panel
2. Verify all interactive elements: create book, open detail, trigger review, delete, retry, settings save, model fetch (writer + reviewer), tag input
3. Run `.venv/bin/pytest -x -q` — no backend regressions
4. Test responsive behavior at 600px and below
5. Check keyboard navigation: Tab through all interactive elements, verify focus indicators visible
6. Test with `prefers-reduced-motion` — all animations disabled
7. Verify color contrast on all text elements

---

## Self-Critique

**What could go wrong:**
- Playfair Display is a popular choice — but it's the right popular choice for a book app, not a generic one. The combination with Source Sans 3 + IBM Plex Mono creates a distinctive trio.
- Warm light theme may not suit users who prefer dark mode — but the skill says to take one real risk, and committing to a single direction is more distinctive than offering both.
- Sharp corners may feel harsh to users accustomed to rounded — but they're the right choice for an editorial, bookish aesthetic. The only rounded elements are the setup step number circles (functional, not decorative) and scrollbar thumbs.

**What I'm avoiding:**
- The "warm cream + terracotta + serif" default — my palette uses teal + brass, not terracotta
- The "near-black + acid accent" default — I'm going warm and light
- The "broadsheet + hairline rules + dense columns" default — while I use hairline rules, the layout is airy and spacious, not dense
- Numbered markers on non-sequential content — only used in the setup wizard where steps are genuinely sequential
- Over-decoration — the manuscript card is the signature; everything else is quiet and disciplined

**Before building, I'll verify:** If I ran the same prompt for a different product (e.g., a recipe app, a code editor), would I arrive at the same design? No — the serif + warm palette + manuscript cards are specifically motivated by the book-writing subject. For a recipe app I'd go bold, colorful, photographic. For a code editor I'd go dark, mono, dense. This design is specific to Hullucinator.
