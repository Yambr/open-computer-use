# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
FROM golang:1.25.0 AS build
WORKDIR /src
COPY go.mod .
COPY main.go .
RUN CGO_ENABLED=0 go build -o /embed-portal .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /embed-portal /embed-portal
EXPOSE 3003
ENTRYPOINT ["/embed-portal"]
