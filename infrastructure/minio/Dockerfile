# MinIO Community is source-only. Build the pinned upstream release locally.
FROM golang:1.27-bookworm AS server-build
RUN go install github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z
FROM golang:1.27-bookworm AS client-build
RUN go install github.com/minio/mc@RELEASE.2025-08-13T08-35-41Z
FROM debian:bookworm-slim AS server
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* && mkdir /data && chown 10001:10001 /data
COPY --from=server-build /go/bin/minio /usr/local/bin/minio
USER 10001
ENTRYPOINT ["minio"]
FROM debian:bookworm-slim AS client
COPY --from=client-build /go/bin/mc /usr/local/bin/mc
USER 10001
ENV MC_CONFIG_DIR=/tmp/mc
ENTRYPOINT ["mc"]
