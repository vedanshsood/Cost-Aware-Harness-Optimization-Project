FROM python:3.12-slim-bookworm

# Install a fixed version of the Python package manager.
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /usr/local/bin/

# Docker client and Compose used to launch task containers.
COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:29-cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/

# Tools required to retrieve and install the benchmark.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Supplied by scripts/build_runtime.py from our saved manifest.
ARG BENCHMARK_COMMIT

# Retrieve official source directly to preserve Linux file formatting.
RUN test -n "$BENCHMARK_COMMIT" \
    && git clone https://github.com/facebookresearch/TUA-Bench.git /opt/tua-bench \
    && git -C /opt/tua-bench checkout --detach "$BENCHMARK_COMMIT" \
    && test "$(git -C /opt/tua-bench rev-parse HEAD)" = "$BENCHMARK_COMMIT"

WORKDIR /opt/tua-bench

ENV UV_PYTHON=python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Install the benchmark's locked dependencies, including Harbor.
RUN uv sync --locked

ENV PATH="/opt/tua-bench/.venv/bin:${PATH}"

LABEL org.opencontainers.image.title="PE6203 benchmark runtime"
LABEL pe6203.benchmark.commit="${BENCHMARK_COMMIT}"

CMD ["harbor", "--help"]