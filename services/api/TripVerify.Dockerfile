FROM golang:1.27-bookworm AS build
WORKDIR /src
COPY services/api/go.mod services/api/go.sum ./
RUN go mod download
COPY services/api/ ./
RUN CGO_ENABLED=0 go build -o /verify-trip-storage ./cmd/verify-trip-storage
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /verify-trip-storage /verify-trip-storage
COPY migrations/ /migrations/
ENTRYPOINT ["/verify-trip-storage"]
