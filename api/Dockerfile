FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -o /out/trackside-api .

FROM alpine:3.20
RUN adduser -D -u 10001 app
USER app
COPY --from=build /out/trackside-api /usr/local/bin/trackside-api
EXPOSE 8000
ENTRYPOINT ["trackside-api"]
