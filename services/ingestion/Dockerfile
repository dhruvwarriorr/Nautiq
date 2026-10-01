FROM golang:1.27-bookworm AS build
WORKDIR /src
COPY services/ingestion/go.mod services/ingestion/go.sum ./
RUN go mod download
COPY services/ingestion/ ./
RUN CGO_ENABLED=0 go build -o /ingestion ./cmd/ingestion
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /ingestion /ingestion
COPY packages/source-catalog/argo.json /argo.json
ENTRYPOINT ["/ingestion"]
