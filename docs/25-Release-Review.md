# Release wording and external review register

Production and scientific approval remain false in `packages/source-catalog/production.json`. Local automated acceptance is implementation evidence. `make production-gate` emits missing review records and exits 2 even if records are supplied; review evidence never silently changes runtime capability flags or release policy.

## Product wording review

| Surface | Required interpretation | Release limitation |
| --- | --- | --- |
| Trip assessment | Provisional diagnostic evidence with timestamps, source coverage, unsupported inputs, uncertainty and official authority references. Unknown is an unavailable result, not a favorable condition. | Never imply navigational authorization, a safe voyage, complete warnings or personalized vessel certification. Independent marine/domain review of thresholds and wording remains required. |
| Personal alerts | User-selected preferences with frozen evidence; fresh positive confirmation is needed for recovery. | Personal limits are not validated operational safety thresholds. Source recovery is not safe-weather clearance. |
| Regional events/models | Diagnostic anomaly/event classifications with immutable lineage. | No production promotion from synthetic tests or local implementation. Scientific calibration, independent validation and cadence remain required. |
| Status | Connection availability, integrity, source age, worker activity and pauses. | A green dependency/transport check does not establish scientific accuracy, rights or warning completeness. |
| Official advisories | Source authority attribution, original validity/revision and links; preserve cancellation/correction semantics. | The configured transport may be incomplete. Absence of a matching advisory never establishes absence of hazards. |
| Email | Generic private inbox link only. | External mail deliverability is unproven; at-least-once acceptance can repeat mail. No forecast/bulletin/private-coordinate content in email. |

The current UI and policies preserve these limitations. The review register is a source-traced engineering wording assessment, not a lawyer's or maritime professional's approval.

## Redistribution boundary

Preserve original source attribution and acquisition receipts. Raw advisory access is for reproducibility under the configured diagnostic interface; do not launch public redistribution or include third-party bulletin text in exports/email without a recorded permission basis. Review each authority separately, including RSS/CAP completeness, copyright, attribution, permitted reuse, retention and geographic coverage. Forecast/analysis availability is also distinct from reuse rights. Disable the `advisories` scope if rights or bulletin integrity are disputed; preserve original evidence privately for investigation according to the approved retention basis.

## Review record format

Operator-owned evidence can be supplied to `scripts/production_gate.py --evidence /private/reviews.json` as an object keyed by each `required_external_gates` entry. Each entry needs `approved: true`, a reviewer identifier, protected evidence URI and SHA-256; do not include private source text or credentials. These records are references for an explicit future release-policy review, not an automatic approval mechanism.

| External gate | Current acceptance |
| --- | --- |
| Scientific validation | Pending independent domain review |
| Repeated source cadence | Pending repeated real acquisitions/coverage evidence |
| Marine advisory completeness | Pending authority-by-authority coverage/transport evidence |
| Source rights | Pending authoritative licensing/redistribution review |
| Trip thresholds and wording | Pending marine/domain and legal sign-off |
| Public identity/security | Pending abuse, recovery, retention and independent security review |
| Deployment TLS/network | Local disposable HTTPS passed; actual host/domain/certificate/firewall acceptance pending |
| Offsite backup restore | Local isolated restore drill; offsite retention, key escrow and target-host recovery pending |
| Incident ownership/response | Runbooks supplied; named on-call ownership, alert routing and response exercises pending |

Until all applicable reviews authorize an explicit policy change, operate as a private diagnostic product. Public deployment is not implied by completing this implementation.

## Additional wording review — question answers, categories, monitoring

| Surface | Required interpretation | Release limitation |
| --- | --- | --- |
| Ask answers | Fixed templates over retained evidence with an explicit window and limits list. | Not a forecast service or a safety statement; official warning completeness unverified. Needs the same independent wording review as trips. |
| Language-model labelling | Optional, off by default; labels only. | Sends question text to a third party when enabled: privacy notice, provider terms and egress approval are release decisions. |
| Evidence category | Descriptive rank band with components. | Not an event, probability or alert; band cut-offs are unreviewed. |
| Model monitoring | Starts investigations. | Thresholds unreviewed; "not enough evidence" is expected until trusted delayed-mode outcomes exist. |
| ETOPO bathymetry | Offline experiment input. | Terms and redistribution review pending before any serving or export use. |
