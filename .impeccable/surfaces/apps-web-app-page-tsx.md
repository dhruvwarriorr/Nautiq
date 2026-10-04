---
version: 1
slug: "apps-web-app-page-tsx"
primary_target: "apps/web/app/page.tsx"
related_targets: ["apps/web/app/layout.tsx"]
---

# Surface brief: Nautiq web app (full revamp)

Scope: every public route plus the workspace shell. Mode: Persuade on the home front door, Operate on every other route. Desktop first, fully responsive to phones.

Audience/job: coastal public (fishers, boaters, divers, travellers) checking the sea near a place or asking a question; researchers one level deeper under "Behind the data".
Home action: two equal doors, Ask a question and Pick a place.
Avoid: anything that reads as a generic weather app; too many numbers on screen.
Constraints: keep every route working; honesty wording keeps its meaning; status by shape + word, never colour alone.

## Direction contract

THESIS: Nautiq reads the sea the way a harbour reads its signal mast: one glance gives a shape and a word, the answer before the numbers. It refuses the category default of a full-screen weather map with a sidebar of figures.

OWN-WORLD: Cool sky-white ground (#f3f6f7) under harbour-navy ink (#0b2341); deep sea-blue fields (#123f6b to #0a2a4d) own the hero, the map and the footer. Signal red (#d23f2a) is only for official warnings; signal yellow (#f1bf2c) only for caution and stale. Status is day-signal geometry: ball (available), half-hoisted ball (stale), diamond (unknown), empty dashed ring (unavailable), red cone (official warning), always paired with a word. Icons are custom flat signal-flag geometry with a 1.75px stroke. Big Shoulders Display for signal words, Overpass for reading, tabular numerals.

STORY: The visitor sees today's hoist for India's seas, picks a place or asks in their own words, gets one sentence and up to four readings in plain time ("for 10 am today"), and can open the evidence if they want it.

FIRST VIEWPORT: A full-bleed sea-blue band at about 88vh. A slim nav sits on the blue. The left quarter holds a vertical mast with three live marks (Warnings, Forecasts, Observations), each a shape with a word. The right three quarters hold a display headline at about 6rem, a custom Ask field about 680px wide, and below it a signal board of five places as equal buttons. Ask and the places get equal weight.

FORM: Port Storm Signals, ranked #1 on my ordered list, the IMPECCABLE'S PICK card; seed 2677f21c. Signature interaction: the hoist. Marks run up the halyard on load, re-hoist when the place changes, and stale marks rest at half-mast. Motion grammar: vertical halyard travel with an expo ease-out, and panels that slide in from the mast side.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Unresolved: none.
