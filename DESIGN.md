---
name: Nautiq
description: Plain answers about the sea near India's coast, read like a harbour signal mast.
colors:
  sky: "#f2f5f6"
  sky-2: "#e6edf0"
  paper: "#ffffff"
  ink: "#0b2341"
  ink-2: "#34506b"
  ink-3: "#536b83"
  line: "#d3dde3"
  line-2: "#b6c5cf"
  sea: "#123f6b"
  sea-deep: "#0a2747"
  sea-abyss: "#071c35"
  on-sea: "#eef4f8"
  on-sea-2: "#b7cadb"
  selection: "#cfe3f5"
  signal: "#d23f2a"
  signal-ink: "#a8301d"
  signal-wash: "#fbe9e5"
  caution: "#f1bf2c"
  caution-ink: "#6e5200"
  caution-wash: "#fdf4d6"
  chart-land: "#eef2f3"
  patch-blue: "#9fd0f5"
typography:
  display:
    fontFamily: "Big Shoulders, Arial Narrow, sans-serif"
    fontSize: "clamp(54px, 6.6vw, 96px)"
    fontWeight: 800
    lineHeight: 0.86
    letterSpacing: "0.002em"
    fontVariation: "opsz"
  headline:
    fontFamily: "Big Shoulders, Arial Narrow, sans-serif"
    fontSize: "clamp(44px, 5.6vw, 84px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "0.005em"
  title:
    fontFamily: "Big Shoulders, Arial Narrow, sans-serif"
    fontSize: "clamp(30px, 3.2vw, 44px)"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.005em"
  reading:
    fontFamily: "Big Shoulders, Arial Narrow, sans-serif"
    fontSize: "clamp(54px, 5vw, 76px)"
    fontWeight: 800
    lineHeight: 0.9
    fontFeature: "tnum"
  signal-word:
    fontFamily: "Big Shoulders, Arial Narrow, sans-serif"
    fontSize: "27px"
    fontWeight: 800
    lineHeight: 1.05
  body:
    fontFamily: "Overpass, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "kern"
  lead:
    fontFamily: "Overpass, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Overpass, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.08em"
  mono:
    fontFamily: "Overpass Mono, ui-monospace, monospace"
    fontSize: "0.86em"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "4px"
  md: "10px"
  panel: "14px"
  pill: "999px"
spacing:
  gutter: "clamp(16px, 3.2vw, 40px)"
  gap: "8px"
  card: "22px 24px"
  stack: "48px"
  section: "88px"
  wrap: "1200px"
  measure: "68ch"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.sea}"
    textColor: "{colors.paper}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "48px"
  button-ghost-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  button-on-sea:
    backgroundColor: "{colors.on-sea}"
    textColor: "{colors.sea-deep}"
    rounded: "{rounded.pill}"
    height: "48px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "11px 14px"
    height: "48px"
  ask-field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "6px"
    width: "700px"
  chip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "40px"
  nav-link:
    textColor: "{colors.on-sea-2}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "40px"
  nav-link-active:
    backgroundColor: "{colors.on-sea}"
    textColor: "{colors.sea-deep}"
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.card}"
  readings-board:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "24px 22px 22px"
  notice-warning:
    backgroundColor: "{colors.signal-wash}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
  notice-caution:
    backgroundColor: "{colors.caution-wash}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
  map-panel:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.panel}"
    padding: "22px 22px 18px"
    width: "360px"
---

# Design System: Nautiq

## Overview

**Creative North Star: "Port Storm Signals"**

Nautiq reads the sea the way a harbour reads its signal mast: one glance gives a shape and a word, and the answer comes before the numbers. The world is a cool sky-white ground under harbour-navy ink, with deep sea-blue fields that own the top of the page, the map and the footer. Content sits on white paper sheets laid on the sky ground; the sea is the only saturated surface, and the two signal colours appear only when they carry meaning.

Density is low on public surfaces. A page leads with a sea-blue band holding a condensed display title and one plain sentence, then a small number of readings or rows, then evidence behind a disclosure. Status is never colour alone: it is day-signal geometry (ball, half-hoisted ball, diamond, dashed ring, red cone) paired with a word. Iconography is Nautiq's own harbour and signal-flag drawing on a 24-unit grid, and the mark is the November code flag on a staff.

Motion follows the halyard: marks run up the mast on load with an expo ease-out, stale marks settle at half-mast, panels slide in from the mast side, and loading is a short dashed line travelling along a rope. Everything respects reduced motion.

**Key Characteristics:**
- Sky-white ground, navy ink, sea-blue fields; white paper sheets for content.
- Condensed, heavy display type (Big Shoulders 800) for titles, signal words and readings; Overpass for reading.
- Status as shape plus word, everywhere, through one component.
- Pill-shaped controls, gently rounded sheets, no hard edges or offset shadows.
- Plain language first; diagnostics one click away.
- A real vector chart restyled in the same palette.

## Colors

A restrained harbour palette: one deep sea blue carries the brand, navy carries the text, and two signal colours are held in reserve for meaning.

### Primary
- **Harbour Sea** (sea): the hero field, the map water, icon tint on paper, selected layer and choice states, door and step discs, text links on paper.
- **Night Harbour** (sea-deep): the sticky nav, page-head bands, mobile tab bar, board header strip, theme colour.
- **Abyss** (sea-abyss): the footer and code/JSON blocks.
- **Foam** (on-sea): text, icons and focus rings on sea fields; the active nav pill and on-sea primary button.
- **Spray** (on-sea-2): secondary text on sea fields; also the dashed neatline colour on the map.

### Secondary
- **Signal Red** (signal, with signal-ink for text and signal-wash for surfaces): official warnings only. The warning cone, warning notices, warning rows, warning verdicts, warning areas on the map.
- **Signal Yellow** (caution, with caution-ink and caution-wash): caution and out-of-date only. The lower half of the half-hoisted ball, caution notices, clarification prompts.

### Tertiary
- **Patch Blue** (patch-blue): unusual-patch events on the map (dashed outline, 14 to 18% fill). Lives on sea, never on paper.

### Neutral
- **Sky** (sky): the page ground and table header fill.
- **Sky Shade** (sky-2): quiet panels ("What this can't tell you"), current item in the nav panel, neutral category chips.
- **Paper** (paper): every content sheet, input, chip and card.
- **Harbour Ink** (ink): body text, headings, primary button fill, light-ground focus ring, the rule above door lists and signal keys.
- **Ink 2 / Ink 3** (ink-2, ink-3): secondary text and labels; ink-3 also draws the unavailable ring.
- **Line / Line 2** (line, line-2): hairline dividers and borders; line-2 for control borders and dashed empty marks.
- **Pale Sea Selection** (selection): text selection highlight.
- **Chart Land** (chart-land): land on the map, quieter than the page sky so the sea stays the subject.

### Named Rules
**The Reserved Signals Rule.** Signal red appears only for an official warning; signal yellow appears only for caution or out-of-date. Neither is ever used for focus, selection, hover, emphasis or decoration. Focus on sea fields is foam white; selection is pale sea.

**The Shape-and-Word Rule.** No status is ever conveyed by colour alone. Every status renders through the signal component: its shape plus its word (Available, Out of date, Unknown, Not available, Official warning).

**The Sea Owns the Field Rule.** Saturated colour lives in the sea-blue bands (nav, page head, hero, map, footer). Content below sits on paper over sky.

## Typography

**Display Font:** Big Shoulders, optical-size axis enabled (with Arial Narrow)
**Body Font:** Overpass (with system-ui); a system middle dot is borrowed for U+00B7 and U+2022 only
**Label/Mono Font:** Overpass Mono for digests, code and JSON

**Character:** A condensed, heavy harbour-board display face against a plain highway-signage text face. The display face speaks in signal words and numbers; Overpass does the explaining.

### Hierarchy
- **Display** (800, uppercase, line-height 0.86): the home hero headline only; the second line drops to spray.
- **Headline** (800, line-height 0.95): page-head titles on the sea band.
- **Title** (800): section headings; h3 at 24px.
- **Reading** (800, tabular, line-height 0.9): the one big number in a reading cell, with its unit at 0.42em in ink-2.
- **Signal word** (800): hoist words, verdict titles (30px), door titles (30px), place-board names (22px), board place names (28px).
- **Body** (400, 17px, 1.6; 16px under 640px): paragraphs capped at 68ch.
- **Lead** (19px, ink-2 or spray): the one plain sentence under a title, capped near 60ch.
- **Label** (700 to 800, 12.5 to 15px, 0.06 to 0.1em, uppercase): reading titles, table headers, map group legends, board header, footer column heads, hoist mark labels. Always names the content directly beneath it.

### Named Rules
**The Tabular Rule.** Every number that can change (readings, table cells, legend ends, dates in inputs) uses tabular numerals.

**The Plain Absence Rule.** "Not available" is a small dashed ring plus plain bold body text (16px, 700, ink-2). It is never set in display type, and a unit is never shown without a value.

## Layout

A single centred column, 1200px wide plus a fluid gutter (clamp 16 to 40px). Sea bands (nav, page head, hero, promise band, footer) break out to full bleed while their contents re-align to the same column. Sections are spaced 88px apart; the first block after a page head sits 48px below it. Rows and readings use 18 to 24px internal padding with 8px gaps for tight sets.

The home hero is about the viewport tall (capped at 860px): a 230 to 270px mast column on the left and the headline, Ask field (700px max) and five-place board on the right, with a quiet chart of India's seas masked in behind. Inner pages use a sea-blue page head, then content; split layouts use a 340px sticky aside.

Responsive steps: 1100px collapses four-up readings to two and splits to one column; 900px swaps the nav for a menu plus a fixed five-item bottom tab bar, turns the hero mast into a three-up row of tiles, and docks the map panel to the bottom as a sheet; 640px goes single column and wraps the Ask field. The map is full-bleed below the nav.

**The Plain First Rule.** Public pages lead with plain language: title, one sentence, the answer. Diagnostics (identifiers, hashes, JSON, reason lists) sit behind the Technical detail disclosure or a "Why it's unknown" disclosure, never in the first read.

## Elevation & Depth

A hybrid: mostly flat tonal layering (paper on sky, foam on sea) with two soft navy-tinted shadows for sheets that float. Static evidence containers use a 1px inset hairline instead of a shadow. On the sea, floating controls take a deep, diffuse drop that reads as distance over water.

### Shadow Vocabulary
- **Sheet** (`box-shadow: 0 1px 2px rgba(11,35,65,.06), 0 8px 24px -12px rgba(11,35,65,.22)`): readings board, rows, verdict, aside, forms, primary button on hover.
- **Lift** (`box-shadow: 0 2px 4px rgba(11,35,65,.08), 0 18px 40px -18px rgba(11,35,65,.35)`): nav dropdown panel, map panel, map card, map zoom.
- **Over the sea** (`box-shadow: 0 24px 50px -24px rgba(3,14,30,.7)`): the Ask field and place board on sea bands.
- **Hairline** (`box-shadow: inset 0 0 0 1px #d3dde3`): notices, evidence sections, tables, charts, empty states.

### Named Rules
**The Soft Navy Rule.** Shadows are always navy-tinted, blurred and offset downward only. No hard offset shadows, no black shadows.

## Shapes

Controls are pills (999px): buttons, nav links, chips, the Ask field, segmented controls, tags. Sheets are gently rounded (10px); floating map surfaces and place tiles a little more (14px); inputs and selects are nearly square (4px). Icon carriers are circles (44 to 58px discs, sea fill or sky fill). Dashed lines mean absence or boundary: the unavailable ring, the empty-state ring, the trip stop rope, the hoist halyard ties, and the map's forecast-coverage neatline.

## Components

### Buttons
Confident, rounded, and quiet until touched.
- **Shape:** full pill, 48px tall (44px in map cards).
- **Primary:** navy fill, white bold 16px text; hover shifts to sea blue with the sheet shadow; press nudges down 1px.
- **Ghost:** transparent with a 1.5px navy border; hover fills navy. On sea bands the border is 50% foam and hover fills foam with night-harbour text.
- **On sea:** foam fill with night-harbour text; hover goes pure white with a soft foam halo.
- **Plain button:** paper with a 1.5px line-2 border; hover darkens the border to ink. Pressed toggles fill navy.
- **Text link:** sea blue, bold, with an arrow that slides 3px on hover.

### Chips
- **Style:** paper pill, 1px line-2 border, 14.5px semibold; on sea, 6% foam fill with a sea-rule border.
- **State:** hover darkens the border to ink (or lifts the foam fill to 14% on sea). Selected choices fill sea blue with foam text.

### Cards / Containers
- **Corner Style:** 10px (14px for map surfaces).
- **Background:** paper on sky.
- **Shadow Strategy:** sheet shadow for primary content, hairline inset for evidence and notices (see Elevation).
- **Border:** internal 1px line dividers between cells and rows.
- **Internal Padding:** 18 to 24px.

### Inputs / Fields
- **Style:** paper, 1.5px line-2 border, 4px radius, 48px tall, 16px text; custom chevron and clock or calendar glyphs drawn in Nautiq's stroke.
- **Focus:** border goes to ink with a 3px pale sea halo (rgba(18,63,107,.22)).
- **Checkbox and switch:** custom; checked fills navy.

### Navigation
Sticky night-harbour bar, 68px (60px on phones), with the November-flag mark and Big Shoulders wordmark. Links are 15.5px semibold spray pills; hover adds an 8% foam wash; the current page is a foam pill with night-harbour text. "Behind the data" opens a white dropdown sheet with icon, title and one line per item. Under 900px a menu button opens the same sheet and a fixed five-item bottom tab bar takes over.

### The Hoist (signature)
A vertical mast (3px rule with a round truck and a foot) carrying marks; each mark is a 30px signal shape, an uppercase label, a signal word in Big Shoulders and an optional note. Marks run up the halyard on load (1.1s expo ease-out, staggered 140ms) and out-of-date marks rest 14px lower at half-mast. On place pages the hoist appears as a row: three marks between sea-rule hairlines, no mast.

### Signal
The atomic status label: shape plus word, 14.5px bold, used in readings, rows, legends and the map. Ball (available), half-hoisted ball with a yellow lower half (out of date), diamond with centre point (unknown), dashed ring (not available), red cone point-down (official warning). On a sea band, a warning signal becomes a red pill with foam shape and text.

### Ask field
A white pill on the sea, 700px max, with a loud-hailer icon, an 18px input and a navy pill "Ask" button whose arrow slides on hover. Focus adds a 4px foam ring. On paper pages it gains a line-2 border and the sheet shadow.

### Readings board
Up to four cells (waves, wind, current, sea temperature) in one paper sheet split by hairlines. Each cell has an uppercase label with a sea icon, one display number with a small unit, a plain descriptor (Beaufort or sea-state word), and the time in IST ("for 10 am today"). Wind is in knots. A missing reading follows the Plain Absence Rule.

### Verdict and notices
The warning verdict is a paper sheet with a 56px sky disc holding the signal shape, a 30px display title and one sentence; a warning turns the sheet signal-wash with a 1.5px red inset. Notices are hairline sheets with an icon; caution tone uses caution-wash, warning tone uses signal-wash with a red inset.

### Technical detail
A full-width disclosure between hairlines, 60px tall summary with a sounding icon and a rotating chevron, body sliding down 0.3s. The lighter "Why it's unknown" disclosure is a sea-blue 14.5px summary with a rotating caret.

### Ocean map
MapLibre over OpenFreeMap, restyled: sea-blue water with a soft shelf glow, chart-land land, no road clutter below zoom 6, dashed country boundaries, italic spaced uppercase sea names. Argo floats are foam dots with a navy keyline and cluster as foam rings with counts until zoom 6. The forecast coverage box is framed by a dashed spray neatline. Warning areas are red; unusual patches are dashed patch blue. The layer panel docks left (360px) and becomes a bottom sheet on phones. Forecast layers use one sequential sea ramp (#0e345c, #165c8c, #2e8cb0, #7ec4d6, #e2f4f7): calm reads as the chart sea and higher values brighten towards foam white. The same five anchors live in the server tile renderer (ml/nautiq_ml/fields/sampling.py) and the legend; there is no red or orange end, so a forecast never mimics an official warning.

The trip planner places stops by tapping a Nautiq chart (route picker): the active stop is ringed in white, the first stop is navy, the route is a dotted foam line, and typed coordinates sit behind a "Type coordinates instead" disclosure.

## Do's and Don'ts

### Do:
- **Do** render every status through the signal component: shape plus word.
- **Do** reserve signal red for official warnings and signal yellow for caution or out-of-date.
- **Do** use foam white for focus on sea fields and navy for focus on light ground (3px outline, 3px offset).
- **Do** show "Not available" as a small dashed ring plus plain bold body text.
- **Do** lead public pages with a title and one plain sentence; put diagnostics behind Technical detail or "Why it's unknown".
- **Do** carry a hoist row on place pages.
- **Do** pass every time, source and unit through the presentation layer: IST times in plain words, agency names, Beaufort and sea-state words, knots for wind.
- **Do** cluster floats on the map until zoom 6 and frame forecast coverage with a dashed neatline.
- **Do** draw new icons on the 24-unit grid with a 1.75 stroke and round caps.

### Don't:
- **Don't** use red or yellow for focus, selection, hover, emphasis or decoration.
- **Don't** set a missing value in display type or show a unit with no value.
- **Don't** put identifiers, hashes, ISO timestamps or snake_case on a public surface.
- **Don't** use third-party icon sets or glyph icons; every icon is Nautiq's own drawing.
- **Don't** use hard offset or black shadows.
- **Don't** recolour the wave legend without recolouring the tile renderer in the same change.
