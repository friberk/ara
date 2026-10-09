# Native Linux amd64/arm64 CPU build. GPU variants use the same patched sources.
FROM golang:1.26.0-trixie@sha256:4e603da0ea8df4a8ab10cbf0b3061f7823d277e82ea210a47c32a5fafb43cc43 AS source
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
ARG OLLAMA_COMMIT=cf2a313a298066d572c36812e5ad30a21c0db13b
ARG LLAMA_COMMIT=4625240437c6821ee5c2da99e12d4817c6a8f07f
RUN git init . && git remote add origin https://github.com/ollama/ollama.git && git fetch --depth 1 origin ${OLLAMA_COMMIT} && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${OLLAMA_COMMIT}"
RUN git clone --depth 1 --branch b11454 https://github.com/ggml-org/llama.cpp.git /llama \
    && test "$(git -C /llama rev-parse HEAD)" = "${LLAMA_COMMIT}"
COPY docker/ollama/002-clef-b11454.patch llama/compat/002-clef.patch
RUN printf '%s\n' "${LLAMA_COMMIT}" > LLAMA_CPP_VERSION \
    && git -C /llama apply /src/llama/compat/001-llama-cpp-hooks.patch \
    && git -C /llama apply /src/llama/compat/002-clef.patch

FROM source AS go-build
COPY docker/ollama/003-pull-control.patch /tmp/pull-control.patch
COPY docker/ollama/ara_pull.go docker/ollama/ara_pull_test.go server/
RUN git apply --check /tmp/pull-control.patch && git apply /tmp/pull-control.patch
COPY docker/ollama/004-ifm-thinking.patch /tmp/ifm-thinking.patch
COPY docker/ollama/ara_ifm_thinking.go docker/ollama/ara_ifm_thinking_test.go server/
COPY docker/ollama/ara_ifm_kwargs_test.go llm/
COPY docker/ollama/testdata/ara_ifm_chat_template.jinja server/testdata/
RUN git apply --check /tmp/ifm-thinking.patch && git apply /tmp/ifm-thinking.patch
ENV GOMAXPROCS=2
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go test -p 2 ./server ./llm -run TestARA -count=1 \
    && go build -p 2 -trimpath -ldflags='-w -s -X github.com/ollama/ollama/version.Version=0.40.1-ara.2' -o /out/ollama .
RUN cmake -S . -B build/go-license -DOLLAMA_LLAMA_BACKENDS= -DOLLAMA_MLX_BACKENDS= \
    && cmake --build build/go-license --target ollama-go-license

FROM source AS cpu-build
ARG BUILD_JOBS=2
ENV OLLAMA_LLAMA_CPP_SOURCE=/llama
RUN cmake -S llama/server --preset cpu -DOLLAMA_LLAMA_CPP_SKIP_COMPAT_PATCH=ON \
    && cmake --build build/llama-server-cpu --target llama-server llama-quantize --parallel ${BUILD_JOBS} \
    && cmake --install build/llama-server-cpu --component llama-server --strip

# This derived layer retains the original CMake objects; only the IFM parser
# object and dependent links need rebuilding for the closing-token correction.
FROM cpu-build AS cpu-thinking-build
COPY docker/ollama/005-ifm-thinking-close.patch /tmp/ifm-thinking-close.patch
COPY docker/ollama/ara_ifm_parser_test.cpp /tmp/ara_ifm_parser_test.cpp
COPY docker/ollama/testdata/ara_ifm_chat_template.jinja /tmp/ara_ifm_chat_template.jinja
RUN git -C /llama apply --check /tmp/ifm-thinking-close.patch \
    && git -C /llama apply /tmp/ifm-thinking-close.patch \
    && cmake --build build/llama-server-cpu --target llama-server llama-quantize --parallel 2 \
    && c++ -std=c++17 -I/llama/common -I/llama/vendor -I/llama/include -I/llama/ggml/include \
        /tmp/ara_ifm_parser_test.cpp -L/src/build/llama-server-cpu/bin \
        -Wl,-rpath,/src/build/llama-server-cpu/bin -lllama-common -lllama -o /tmp/ara-ifm-parser-test \
    && /tmp/ara-ifm-parser-test /tmp/ara_ifm_chat_template.jinja \
    && cmake --install build/llama-server-cpu --component llama-server --strip

FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 curl && rm -rf /var/lib/apt/lists/*
COPY --from=go-build /out/ollama /usr/bin/ollama
COPY --from=go-build /src/LICENSE /usr/share/licenses/ollama/LICENSE
COPY --from=go-build /src/build/go-license/lib/ollama/GO_LICENSE /usr/share/licenses/ollama/GO_LICENSE
COPY --from=cpu-thinking-build /src/dist/lib/ollama /usr/lib/ollama
LABEL org.opencontainers.image.title="ARA managed Ollama" \
    org.opencontainers.image.version="0.40.1-ara.2" \
    org.opencontainers.image.source="https://github.com/ollama/ollama" \
    org.opencontainers.image.revision="cf2a313a298066d572c36812e5ad30a21c0db13b" \
    org.opencontainers.image.licenses="MIT" \
    ara.llama.revision="4625240437c6821ee5c2da99e12d4817c6a8f07f"
ENV OLLAMA_HOST=0.0.0.0:11434 OLLAMA_NOPRUNE=true OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=2m OLLAMA_CONTEXT_LENGTH=8192
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]

# Optional GPU payload builds. These are not dependencies of the CPU target.
FROM nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:520292dbb4f755fd360766059e62956e9379485d9e073bbd2f6e3c20c270ed66 AS cuda-build
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build git && rm -rf /var/lib/apt/lists/*
COPY --from=source /src /src
COPY --from=source /llama /llama
COPY docker/ollama/005-ifm-thinking-close.patch /tmp/ifm-thinking-close.patch
RUN git -C /llama apply --check /tmp/ifm-thinking-close.patch && git -C /llama apply /tmp/ifm-thinking-close.patch
WORKDIR /src
ARG BUILD_JOBS=2
ARG CUDA_ARCHITECTURES="75;80;86;89;90"
ENV OLLAMA_LLAMA_CPP_SOURCE=/llama
RUN cmake -S llama/server --preset llama_cuda_v12_user_arch -DOLLAMA_LLAMA_CPP_SKIP_COMPAT_PATCH=ON -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES}" \
    && cmake --build build/llama-server-cuda_v12 --target ggml-cuda --parallel ${BUILD_JOBS} \
    && cmake --install build/llama-server-cuda_v12 --component llama-server --strip
FROM runtime AS nvidia
COPY --from=cuda-build /src/dist/lib/ollama /usr/lib/ollama
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility NVIDIA_VISIBLE_DEVICES=all

FROM rocm/dev-ubuntu-24.04:7.2.1-complete@sha256:3db551c4e1229aac1857ac44fcb6141bb749f41348eb572452f11279153c13c3 AS rocm-build
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build git && rm -rf /var/lib/apt/lists/*
COPY --from=source /src /src
COPY --from=source /llama /llama
COPY docker/ollama/005-ifm-thinking-close.patch /tmp/ifm-thinking-close.patch
RUN git -C /llama apply --check /tmp/ifm-thinking-close.patch && git -C /llama apply /tmp/ifm-thinking-close.patch
WORKDIR /src
ARG BUILD_JOBS=2
ARG AMDGPU_TARGETS="gfx1100;gfx1101;gfx1102;gfx1150;gfx1151;gfx1200;gfx1201"
ENV OLLAMA_LLAMA_CPP_SOURCE=/llama CC=/opt/rocm/llvm/bin/clang CXX=/opt/rocm/llvm/bin/clang++
RUN cmake -S llama/server --preset rocm_v7_2_user_arch -DOLLAMA_LLAMA_CPP_SKIP_COMPAT_PATCH=ON -DAMDGPU_TARGETS="${AMDGPU_TARGETS}" \
    && cmake --build build/llama-server-rocm_v7_2 --target ggml-hip --parallel ${BUILD_JOBS} \
    && cmake --install build/llama-server-rocm_v7_2 --component llama-server --strip
FROM runtime AS amd
COPY --from=rocm-build /src/dist/lib/ollama /usr/lib/ollama

# An unqualified docker build also selects CPU, never an implicit GPU download.
FROM runtime AS default
