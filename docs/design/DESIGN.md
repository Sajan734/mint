# Mint design system

The one design source for the buyer site, the seller site and the iOS scanner. Format follows the Stitch
`DESIGN.md` layout used by [awesome-design-md](https://github.com/voltagent/awesome-design-md). Rules for what to
avoid come from [taste-skill](https://github.com/Leonxlnx/taste-skill) (`design-taste-frontend` and
`redesign-existing-projects`). The colour structure borrows from the Starbucks system in awesome-design-md (a warm
neutral canvas, a tiered green set, deep green bands and footer, pill buttons that press in).

Supersedes the brand draft in CLAUDE.md §15. Implemented in `buyer/app/globals.css`, `seller/app/globals.css`
(identical token blocks) and `scanner/ios/Mint/Brand.swift`.

## 1. Visual theme

**A neighbourhood shop on a calm street.** Mint sells your neighbours' things: a mouse from Agincourt, a chair from
the Annex. The site should feel like walking into a well-kept corner shop: warm paper-coloured walls, green paint
on the door, hand-lettered signs, everything on the shelf turned so you can see it. Trust comes from plainness and
from showing the thing itself, not from badges.

- **Idea:** the item turning on the seller's kitchen table becomes the shop window. The landing opens on a real
  Mint scan you can drag to turn. Every card turns on hover.
- **Oat canvas, pine ink, mint-leaf actions.** One ground, one ink, one action colour. A pale mint wash and a deep
  pine field are the two whole-section colours.
- **Fraunces for signs, Figtree for everything you read or press.** The soft serif carries the homely voice the way
  Starbucks uses a serif for its warm editorial moments; the sans keeps shopping clear.
- **No ornaments.** No outlined boxes, hairline rules, gradients, glows, monospace labels, eyebrow chips, icon
  feature cards or numbered steps. Surfaces separate by a step in tone.

## 2. Colour

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg` (Oat) | `#F1EFE9` | `#0F201B` | Page canvas. Low-chroma warm, never yellow cream, never pure white. |
| `--surface` (Shelf) | `#E7E4DC` | `#17302A` | One tone step up: image wells, inputs, quiet panels, chips. |
| `--surface-2` (Deeper shelf) | `#DCD8CE` | `#1F3B34` | Hover and pressed state of a shelf surface; selected tile. |
| `--raised` (Paper) | `#FFFFFF` | `#17302A` | Only things that float: dialogs, sheets, menus, the sticky phone bar. |
| `--ink` (Pine ink) | `#15302A` | `#EDEBE4` | All running text and headings. Never pure black. |
| `--ink-2` | `#4A5953` | `#A9B8B1` | Secondary notes, metadata. Never for body copy. |
| `--leaf` (Mint leaf) | `#0B6B4C` | `#3DDC97` | Every action: buttons, links, the selected state. White text on it (dark: pine text). |
| `--leaf-press` | `#085A40` | `#5BE6AA` | Hover/pressed action. |
| `--pine` (Field) | `#163A30` | `#0A1814` | Deep band: footer, "how it works", the phone panel. Oat text on it. |
| `--wash` (Mint wash) | `#D6EBDF` | `#123A2A` | The light field: fair-price badge, verified notes, one landing band. |
| `--spark` (Brand mint) | `#3DDC97` | `#3DDC97` | Brand mint. Only on pine: progress ring, done check, the logo dot. Never text on oat. |
| `--amber` / `--amber-wash` | `#7A4A00` / `#F2E1B8` | `#F5C66A` / `#3A2A0C` | "A bit high", disclosed marks, demo notices. |
| `--coral` / `--coral-wash` | `#A33A25` / `#F4D8CF` | `#FF9A84` / `#3D1A12` | "Overpriced", new damage, errors. |
| `--focus` | `#0B6B4C` | `#3DDC97` | 2px focus outline, 2px offset. |

Contrast targets (light): ink on oat and ink-2 on oat above 4.5:1, white on leaf above 4.5:1, oat on pine above
7:1. Checked in `buyer/tests/design-tokens.test.ts`.

Proportions: oat holds most of every page; shelf tiles hold the product pictures; leaf appears on the one primary
action per view and on links; pine appears once or twice per page as a whole band; wash at most once.

## 3. Typography

| Role | Face | Size | Weight | Leading | Tracking |
|---|---|---|---|---|---|
| Display (landing headline) | Fraunces, `SOFT 100`, `opsz` auto | `clamp(2.75rem, 6.2vw, 5.75rem)` | 600 | 0.98 | -0.03em |
| Heading (page and section titles) | Fraunces, `SOFT 100` | 32px (phone 26px) | 600 | 1.1 | -0.02em |
| Title (card titles, panel titles) | Figtree | 18px | 600 | 1.3 | -0.01em |
| Body | Figtree | 16px | 400 | 1.55 | 0 |
| Meta (labels, notes, small buttons) | Figtree | 14px | 500 | 1.45 | 0 |

- Five sizes, far apart. Nothing below 13px. Sentence case everywhere, no tracked capitals.
- Prices: Figtree 700, `tabular-nums`. The big price on the listing page uses the Heading size.
- Headlines: two lines or fewer at every width, `text-wrap: balance`. Body text `text-wrap: pretty`, max 68ch.
- iOS: New York (`.serif`) for display and headings, SF Pro (`.default`) for everything else, SF Pro Rounded
  only for the big upload percentage. `.monospacedDigit()` for numbers.

## 4. Components

**Buttons** are full pills, decided once. Height 48px (44px small). Press: `scale(0.97)`.
- Primary: leaf fill, white text, 600. Hover leaf-press.
- Secondary: shelf fill, ink text. Hover surface-2. No outline.
- On pine: oat fill with pine text (primary), or a plain oat text link.
- Text link: leaf, underline on hover, 600.

**Product card**: no box. A shelf-coloured image well (16px radius, square) with the picture, then price and badge
on one line, then the title in two lines at most. Hover (fine pointer): the well steps to surface-2 and the scan
turns in 3D. Status ("Sold", "Reserved") is a small paper tag in the well's top left. Save is a round button in the
well's top right. Whole card is one link.

**Price badge**: small rounded rectangle (8px), 13px/600, sentence case, a glyph per state (never colour only):
"Great price" leaf text on wash, "Fair price" ink on deeper shelf, "A bit high" on amber-wash, "Overpriced" on
coral-wash, "No price check" ink-2 on shelf. Never a solid leaf fill: leaf is for actions.

**Inputs**: shelf fill, 12px radius, no border at rest; 2px leaf outline on focus; coral outline and message on
error. Labels above, 14px/600.

**Panels**: a tone step (shelf on oat, or oat on paper), 20px radius, no border, no shadow.

**Dialogs and sheets**: paper, 24px radius, layered soft shadow `0 1px 2px rgb(21 48 42 / .08), 0 12px 32px
rgb(21 48 42 / .16)`, scrim `rgb(21 48 42 / .45)`.

**Header**: oat bar, wordmark left, search, three links, one leaf "Sell an item" pill. No rule underneath.

**Footer**: pine field. The wordmark set large at full width in Fraunces, a few links, the demo note. It is a
close, not a sitemap.

**Phone hand-off panel** (web) and the iOS full-screen moments: pine field, oat type, spark ring and check,
Fraunces / New York for the big line, Figtree / SF Pro for the rest. Ripples are spark rings fading out.

## 5. Layout

- Container 1240px, gutters 16 / 24 / 40px (phone / tablet / desktop).
- Section gap on the landing 96–128px desktop, 64px phone; inside a section 24–32px.
- Product grids, not side-scrolling rails: 2 columns on phones, 3 at 768px, 4 at 1024px, 5 at 1280px.
- Text blocks share two left edges per page: the container edge and the content column.
- Neighbouring landing sections never share a composition.

## 6. Depth

Flat at rest. Tone steps carry hierarchy: oat < shelf < surface-2. Only floating things get the layered shadow:
dialogs, sheets, the mobile sticky bar, menus. No glows, no hover shadows.

## 7. Do and don't

Do
- Show the real thing large: the scan, the real photographs, the real listing text.
- Say it plainly. "Fair price" not "Great value detected". "Scanned on the seller's phone" not "AI-verified".
- Use leaf for the one primary action per view.
- Keep every honesty rule from `docs/web-handoff/HANDOFF.md` (real data only, label demo data and sample 3D).

Don't
- Outline a box, draw a divider line (except form fields and real tables), add a shadow at rest.
- Use gradients, glass, glows, emoji, decorative blobs.
- Put a small label or chip above a heading. Number steps 01/02/03.
- Use monospace outside code. Use more than two typefaces.
- Put spark (#3DDC97) text on oat: it fails contrast.

## 8. Responsive

| Width | Changes |
|---|---|
| < 640 | One column, 16px gutters, 2-up product grid. Header: wordmark + Sell on row 1, search row 2, links row 3. |
| 640–1023 | 3-up grid, 24px gutters. |
| ≥ 1024 | 4–5-up grid, 40px gutters, hero split 55/45 (words / scan). |

Touch targets 44px minimum. Reduced motion: no travel, no turning; content always visible.

## 9. Motion

- Entrance: each section's heading, then text, then picture rise 20px and fade in, 70ms apart, once, using
  `animation-timeline: view()` where supported (no script; content is never hidden without support).
- Signature move: the hero scan turns slowly on its own until touched.
- Feedback: buttons press to 0.97; cards' image wells step a tone; links underline.
- Durations 120ms (feedback), 220ms (state), 600ms (entrance). Ease `cubic-bezier(0.16, 1, 0.3, 1)`.
