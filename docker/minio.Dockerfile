FROM --platform=$BUILDPLATFORM golang:1.24.13-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS builder
ARG TARGETARCH
ARG MINIO_COMMIT=7aac2a2c5b7c882e68c1ce017d8256be2feea27f
ARG MINIO_ARCHIVE_SHA256=71794c2df26aad0cc99e8421c58b7aa2dd55969f979b0e7d1e931042e9fabcd6
WORKDIR /src
RUN curl --fail --location --silent --show-error \
      "https://codeload.github.com/minio/minio/tar.gz/${MINIO_COMMIT}" -o source.tar.gz \
    && echo "${MINIO_ARCHIVE_SHA256}  source.tar.gz" | sha256sum --check --strict \
    && tar --extract --gzip --file source.tar.gz --strip-components=1 \
    && rm source.tar.gz
ENV GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux
RUN --mount=type=cache,target=/go/pkg/mod go mod download && go mod verify
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    GOARCH=${TARGETARCH} go build -trimpath -tags kqueue -ldflags \
    "-s -w -X github.com/minio/minio/cmd.Version=2026-02-12T20:18:48Z -X github.com/minio/minio/cmd.CopyrightYear=2026 -X github.com/minio/minio/cmd.ReleaseTag=DEVELOPMENT.2026-02-12T20-18-48Z -X github.com/minio/minio/cmd.CommitID=${MINIO_COMMIT} -X github.com/minio/minio/cmd.ShortCommitID=7aac2a2c5b7c -X github.com/minio/minio/cmd.GOPATH=/go -X github.com/minio/minio/cmd.GOROOT=/usr/local/go" \
    -o /out/minio .

FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="7aac2a2c5b7c882e68c1ce017d8256be2feea27f" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
RUN groupadd --gid 10001 minio && useradd --uid 10001 --gid minio --no-create-home minio \
    && mkdir /data && chown minio:minio /data
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /src/LICENSE /usr/share/doc/minio/LICENSE
USER minio
EXPOSE 9000
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
