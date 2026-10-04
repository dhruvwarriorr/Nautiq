# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: the coastal public of India and the Northern Indian Ocean: small-boat fishers, recreational boaters, divers, kayakers and coastal travellers who want to know what the sea is doing near a place, or along a timed trip, before they go. They read on phones as often as on laptops, often outdoors, and are not scientists.

Secondary (one level deeper, never on the front door): researchers, students, coastal agencies and domain professionals who need exact observations, depth profiles, QC flags, model versions, intervals, provenance and exports.

## Product Purpose

Nautiq answers one question in plain language: what is the sea doing here, is it unusual, does it matter for my trip, and what evidence supports that. It combines real observations (Argo floats), native forecast fields (NOAA OISST, GFS-Wave, GFS weather, HYCOM currents), official agency bulletins (NDMA CAP, INCOIS) and a fixed historical normal. Success is a non-expert reaching a clear, honest answer in seconds, and being able to dig into the evidence if they choose.

## Positioning

Nautiq is honest about uncertainty in a way neighbouring weather and fishing apps are not: an unknown warning state is never an all-clear, missing data is shown as missing, it never declares a trip safe, and every answer can be traced to the original source file.

## Operating Context

Public views need no account. A private workspace (sign-in) holds saved places, timed trips with frozen replayable receipts, alerts and exports. A natural-language Ask flow parses a question into place, time and activity, then answers from retained evidence. The web app is a Next.js front end over a Go API and Python ML/field services.

## Capabilities and Constraints

- Conditions at named places; timed trip diagnostics; official warnings; regional events; Argo profiles with expected state, intervals and anomaly category; forecast field rasters; research queries and exports; alerts with in-app and email delivery.
- Trip limits are not yet approved by marine and legal reviewers, so real trips return "insufficient data" unless an official warning applies. Official marine coverage is not yet verified.
- Learned models did not beat the historical seasonal normal convincingly; the normal is in use.
- Status vocabulary (Available, Stale, Unknown, Unavailable, Official warning) is product truth and must be communicated with words and symbols, never colour alone.
- Technical pages (models, monitoring, climatology, intervals, calculations, training snapshots, data quality, status) live under a "Behind the data" area: plain summary first, raw identifiers, hashes and JSON behind an explicit "technical detail" disclosure. Removed from primary navigation.
- Raw machine values (ISO timestamps, source IDs, snake_case enums, SHA digests) must pass through a presentation layer that renders them human-readable (relative/local time, agency names, sentence-case labels) before reaching a public view.

## Brand Commitments

- Name: Nautiq.
- Ocean theme, minimalist, low data density on public surfaces (user-binding).
- All icons, the search bar and UI components are custom-drawn for Nautiq; no third-party icon sets or web icon sources (user-binding).
- Map: a real zoomable vector map (MapLibre GL with a key-less OpenFreeMap basemap) restyled into Nautiq's own chart look, with Nautiq's own markers and layers (user-confirmed).
- References the user offered as inspiration only, not to copy: Dribbble "Dive Website", Best of Collingwood, Lacadives redesign, SeaGuard cleanup dashboard, Transocean, National Geographic "Tip of the Iceberg", Aqualine Logistics, iaculus.

## Evidence on Hand

Live retained data through the local API: field releases with freshness, Argo profiles, event candidates, advisory polygons/circles, source health. No testimonials, customers, usage numbers or partner logos exist; never fabricate them.

## Product Principles

1. Answer first, evidence second: every public page leads with a plain sentence, numbers come after, raw provenance last and on request.
2. Honest by construction: unknown is never shown as clear; missing is never filled.
3. One thing per screen: remove before adding; density belongs behind disclosure.
4. Words for people: no IDs, hashes, ISO strings or snake_case on public surfaces.
5. Safety language is never softened for aesthetics.

## Accessibility & Inclusion

WCAG 2.2 AA. Status never by colour alone. 44px touch targets. Reduced-motion respected. Readable outdoors on phones (contrast and type size).
