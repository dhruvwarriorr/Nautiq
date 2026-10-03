FROM golang:1.27-bookworm AS build
WORKDIR /src
COPY services/api/go.mod services/api/go.sum ./
RUN go mod download
COPY services/api/ ./
RUN CGO_ENABLED=0 go build -o /notifications ./cmd/notifications && CGO_ENABLED=0 go build -o /verify-notifications ./cmd/verify-notifications
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /notifications /notifications
COPY --from=build /verify-notifications /verify-notifications
COPY migrations/ /migrations/
ENTRYPOINT ["/notifications"]
