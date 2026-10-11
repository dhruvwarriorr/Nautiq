# Nautiq

<div align="center">

**Understand what the sea is doing, and where the evidence runs out.**

An ocean conditions explorer for India's coast, built around clear answers, source times, and visible uncertainty.

</div>

---

## What is Nautiq?

Waves, wind, currents, sea temperature, and float observations come from different sources and cover different places and times. Nautiq brings them into one map and explains what is available for a place or trip. Every answer can lead back to its source, valid time, and calculation.

This repository contains a **local diagnostic product**. Its scientific models and trip limits are research and engineering prototypes. Nautiq does not track official marine warnings, and it is not approved as a public marine safety service.

## What you can do

- **Ask about a place and time.** Type a question about conditions near Mumbai, Goa, Kerala, the Arabian Sea, or the Bay of Bengal. Review and correct the place, time, and question type before seeing an answer assembled from stored evidence.
- **Explore the ocean map.** Switch between wave, wind, current, and sea temperature layers, inspect forecast times, and find Argo float readings.
- **Trace an observation.** Inspect original float levels, quality flags, revisions, and the raw and derived evidence behind a profile.
- **Compare with history.** See how a reading differs from a fixed seasonal reference and inspect diagnostic model and anomaly evidence without treating it as a warning.
- **Check a timed route.** Add outward and return stops, compare forecasts with configurable wave, wind, and current limits, and see missing inputs. A result is never a declaration that a trip is safe.
- **Keep a private workspace.** Save routes, places, and bounded research exports in a local account. Public account recovery and MFA are not implemented.

## How it works

```text
Argo observations + forecast providers
                │
                ▼
     ingestion and immutable evidence
                │
                ▼
  PostgreSQL/PostGIS/TimescaleDB + MinIO
                │
                ▼
     Go API + Python scientific services
                │
                ▼
    Next.js map, Ask, trips, and research
```

Ask turns a question into a bounded, editable query. The answer is built from typed data and fixed templates. An optional language model can label the question's intent, place, and time; it does not produce measurements or write the answer. With no API key, built-in rules handle questions locally.

Scientific releases are selected by exact ID. A running service or a passing local check does not qualify a model for scientific use. See the [historical architecture design](docs/04-Nautiq-System-Architecture.md) and [current release review](docs/25-Release-Review.md).

## Run locally

You need Docker with Compose and a running daemon, Go 1.26+, Node.js 24+, npm, and [uv](https://docs.astral.sh/uv/). Setup creates a Python 3.12 environment and copies `.env.example` to `.env` if needed.

```sh
make setup
make up
```

Open [Nautiq](http://localhost:3000), the [getting-started guide](http://localhost:3000/start), or the [service status](http://localhost:3000/status). The API is at `http://localhost:8080`. Check the status page after startup; first startup can take several minutes while images and dependencies build.

The default credentials in `.env.example` are **local development values**. Keep real credentials in the ignored `.env` file. Copernicus Marine wave, current, and sea temperature downloads need a [Copernicus Marine account](https://data.marine.copernicus.eu/register) and `CMEMS_USERNAME` / `CMEMS_PASSWORD` in `.env`. Without provider credentials or fresh acquisitions, related readings can correctly appear unavailable or out of date.

```sh
make ingest        # Acquire one bounded Argo batch
make field-refresh # Acquire configured forecast products
make down          # Stop containers and preserve data volumes
```

The [documentation index](docs/README.md) separates current behavior from historical design and delivery records. The [operations runbook](docs/24-Operations-Runbook.md) is a historical template for migrations, recovery, and deployment controls; its private verification tools are not distributed in this repository.

## Project layout

| Path | Purpose |
| --- | --- |
| `apps/web/` | Next.js product and research pages |
| `services/api/` | Go APIs, product rules, and trip engine |
| `services/ingestion/` | Argo discovery and acquisition |
| `ml/` | Python normalization, field sampling, and scientific models |
| `migrations/` | Ordered PostgreSQL schema upgrades |
| `packages/` | Source catalogs, API schemas, and scientific fixtures |
| `infrastructure/` | Local storage build and private deployment configuration |
| `docs/` | Design, delivery evidence, limitations, and runbooks |

## Data, limitations, and attribution

Nautiq distinguishes an observation from a forecast, a historical comparison from a prediction, and missing data from a favorable result. The current product does **not** ingest official warnings. Check [INCOIS](https://incois.gov.in/) and [IMD](https://mausam.imd.gov.in/) before any real trip, along with local authorities and conditions.

Argo profile data is credited to the [International Argo Program and contributing national programs](https://doi.org/10.17882/42182). Forecast layers use [Copernicus Marine](https://marine.copernicus.eu/) and NOAA products as identified in the [source catalog](packages/source-catalog/fields.json). Source attribution, terms, and redistribution rights require review before a public data service or commercial use. The repository includes selected historical evidence summaries, but no raw provider datasets or private user data.

The code can be viewed publicly without operating Nautiq as a public service. The [release review](docs/25-Release-Review.md) records pending scientific validation, source cadence and rights, independent security review, and real deployment and recovery checks. `packages/source-catalog/production.json` keeps production and scientific approval false.

## FAQ

**Is there a live public app?**

No public deployment is claimed here. Run the project locally to explore it.

**Does Nautiq decide whether it is safe to go to sea?**

No. Trip checks compare forecast samples with unreviewed limits and show what they could not check. They do not include official warnings, vessel details, or every local hazard.

**Does AI invent the answers?**

No. The optional model only labels a question. Nautiq validates that label and builds the response from stored evidence.

**Can I reuse the data?**

Each source has its own terms. Review those terms before redistribution; the repository's source catalogs and release review record known limits.

**Can I reuse the code?**

Copyright © 2026 Dhruv Kumar. All rights reserved. This public repository grants no license to use, modify, or redistribute the code.

---

<div align="center">

Built by **Dhruv Kumar**

</div>
