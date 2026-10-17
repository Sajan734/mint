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

**Theme (Oct 17): the original Mint palette, light mode only.** The pine-and-oat palette tried earlier was dropped.
Tokens in both `globals.css` (identical) and `scanner/ios/Mint/Brand.swift`.

| Token | Value | Role |
|---|---|---|
| `--bg` (paper) | `#FAF7F2` | Page canvas. |
| `--surface` | `#F0ECE4` | One tone step: image wells, panels, inputs. |
| `--surface-2` | `#E7E1D6` | Hover, selected. |
| `--raised` | `#FFFEFC` | Cards, dialogs, sheets. |
| `--ink` | `#0B0F0E` | All text; the primary button fill (paper text on it). |
| `--ink-2` | `#4A5552` | Secondary text. |
| `--mint` (`--spark`) | `#3DDC97` | Brand mint: logo, fills, rings, the done check. Not for text. |
| `--mint-ink` (`--leaf`) | `#1B6B49` | Green text and links. |
| `--mint-wash` (`--wash`, `--pine`) | `#DDF6EA` | The light band ("How Mint works", footer, phone panel), fair-price badge. Ink text on it. |
| `--amber` / `--amber-wash` | `#7A4A00` / `#FCEBC6` | "A bit high", disclosed marks, demo notices. |
| `--coral` / `--coral-wash` | `#A8301F` / `#FFE0DA` | "Overpriced", new damage, errors. |
| `--focus` | `#2F6FD0` | Focus outline. |

Checked in `buyer/tests/design-tokens.test.ts` (WCAG AA for every text pair, light only).

## 3. Typography

Bricolage Grotesque (600/700) for headings and the wordmark, Figtree for everything else. The iOS app uses SF Pro
Rounded, as it always has. Five sizes, nothing below 13px, sentence case.

## 4. Components

**Buttons** have 14px corners. Height 48px (44px small). Press: `scale(0.97)`.
- Primary: ink fill, paper text, 600.
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
