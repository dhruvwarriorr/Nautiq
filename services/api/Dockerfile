FROM golang:1.27-bookworm AS build
WORKDIR /src
COPY services/api/go.mod services/api/go.sum ./
RUN go mod download
COPY services/api/ ./
RUN CGO_ENABLED=0 go build -o /api ./cmd/api && CGO_ENABLED=0 go build -o /operations ./cmd/operations
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /api /api
COPY --from=build /operations /operations
COPY migrations/ /migrations/
EXPOSE 8080
ENTRYPOINT ["/api"]
