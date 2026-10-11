# Nautiq documentation

Start with the [project README](../README.md) for the current product, local setup, and limitations. Source code and catalogs are the authority for current behavior.

## Current references

| Document | Use |
| --- | --- |
| [Release review](25-Release-Review.md) | Current distinction between a public code repository and a public marine service; pending external decisions |
| [Source catalog](../packages/source-catalog/fields.json) | Configured forecast products, providers, variables, and attribution |
| [Product policy](../packages/source-catalog/product.json) | Current account, export, location, and availability limits |
| [Production policy](../packages/source-catalog/production.json) | Fail-closed production and scientific approval flags |
| [API schemas](../packages/schemas/) | Versioned endpoint contracts |
| [Design system](../DESIGN.md) | Visual language used by the web app |

## Historical design and delivery records

Documents 01–24 and 26–27 record the project's design and the evidence measured at the time each phase was delivered. They are useful for understanding decisions and reproducing research, but some commands and feature descriptions have been superseded. In particular, the current product no longer ingests official warnings or sends personal alerts, and the public repository omits local-only test and verification harnesses. The operational runbook is a historical template until it is reconciled and independently reviewed for a real deployment.

The retained evidence summaries under [evidence/](evidence/) describe specific local runs. They do not establish current provider freshness, independent scientific approval, data reuse rights, or public deployment readiness.
