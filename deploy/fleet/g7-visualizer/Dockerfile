# syntax=docker/dockerfile:1
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod .
COPY proxy.go .
RUN CGO_ENABLED=0 go build -o /g7-proxy .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /g7-proxy /g7-proxy
COPY index.html /web/index.html
EXPOSE 8099
ENTRYPOINT ["/g7-proxy"]
