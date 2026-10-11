# Release review

Nautiq's source code may be visible in a public repository while the **product remains a local diagnostic prototype**. Public repository visibility does not authorize a public marine service, scientific model promotion, forecast redistribution, or operational trip advice.

The current policy in `packages/source-catalog/production.json` sets both `production_approved` and `scientific_approved` to `false`. No local build, synthetic test, or checked-in evidence changes those flags.

## Current product boundary

- The product displays Argo observations, gridded forecasts, historical comparisons, diagnostic model results, research pages, and timed trip checks.
- Ask validates a bounded question frame and builds an answer from typed evidence. Its optional language model labels questions only. Enabling it sends question text to the configured provider and requires a separate privacy and egress decision.
- The product **does not ingest official marine warnings** or send personal alerts. Check INCOIS, IMD, and local authorities for current warnings.
- Trip checks compare forecast samples with configurable but unreviewed limits. Unknown or stale information is never an all-clear. Results do not certify a vessel, route, or voyage.
- Original Argo research exports have a documented attribution path. Forecast data and other provider products have separate terms; public redistribution and commercial use require source-specific review.

Older design and delivery documents describe previously implemented warnings, alerts, and email workflows. Those are historical records, not current product capabilities.

## External decisions still pending

| Area | Needed before a public marine service |
| --- | --- |
| Scientific models | Independent validation on suitable untouched evidence, calibration and failure review |
| Providers | Repeated acquisition and coverage evidence; source-specific attribution, retention, and redistribution rights |
| Trips and wording | Marine/domain and legal review of thresholds, limitations, and user-facing claims |
| Identity and security | Abuse, recovery, retention, privacy, and independent security review; local accounts currently have no MFA or password recovery |
| Deployment | Real host, DNS, TLS, network/firewall, and end-to-end acceptance |
| Recovery and response | Protected offsite backup and restore drill, key escrow, named incident owner and response exercise |

The production policy still lists a legacy `marine_advisory_completeness` gate from the retired warning feature. It remains fail-closed until an authorized release-policy review explicitly updates the gate list. Its presence does not mean Nautiq currently reads warnings.

## Before changing repository visibility

1. Review **the entire Git history**, not only the latest file tree. Files removed from tracking remain in older commits. The local-only verification harnesses and design-session artifacts removed from the current tree are still in history unless the repository is republished with a reviewed fresh history.
2. Confirm that no real credentials, private data, provider artifacts, or unlicensed third-party content appear in any commit, branch, tag, or release asset. The ignored local `.env`, `artifacts/`, `secrets/`, and `backups/` directories must stay outside publication.
3. Keep the public README aligned with the current application. Do not advertise a live site or scientific approval without evidence.
4. The code is **all rights reserved**. Public visibility grants no reuse license. Third-party software and source data retain their own terms.

The public repository and a public operating service have different readiness decisions. Neither repository visibility nor the local verification record should be treated as permission to deploy Nautiq for decisions at sea.
