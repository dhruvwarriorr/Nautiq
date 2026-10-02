# Frozen Argo scientific fixture

`delayed-profile.nc` is a 19,204-byte real core delayed-mode profile from the International Argo Program, retained by the historical source pilot. Its exact GDAC URL, SHA-256, native profile identity, timestamp and numerical reference levels are in `manifest.json`. Data attribution: **International Argo Program and contributing national programs; doi:10.17882/42182**. Source terms and acknowledgement: https://argo.ucsd.edu/data/acknowledging-argo/ . This small verification fixture does not establish production source approval or complete coverage.

`malformed.nc` deliberately contains invalid text and verifies refusal of malformed NetCDF. It contains no scientific measurements.

Run `make phase3-verify`. It verifies both raw hashes, parses the real fixture twice, compares accepted original levels and QC flags, and checks TEOS-10 reference depths within 1e-7 metres. The reference revision hash records the capture environment; byte-exact repeatability is checked within the installed pinned environment, while cross-platform floating-point references use that explicit tolerance. Parser and dependency versions are also retained in calculation manifests.

Synthetic fault fixtures are created at runtime by the verification scripts and are never used to populate the actual local observation or training dataset.
