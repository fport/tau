# The brain: tau's Python hub in cloud mode (ADR 0007).
#
# `wrangler deploy` builds this image with the repository root as the build context
# (`image_build_context: "../.."` in wrangler.cloud.example.jsonc) and runs it as the
# TauBrain container. The hub keeps its life data in the spine (D1, KV), not on the
# container's disk, which is lost whenever the container stops.
#
# Manual build from the repository root:
#   docker build -f cloud/spine/container/Dockerfile -t tau-brain .
FROM python:3.12-slim

# uv from its official image, pinned to a release.
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

# The packages the brain runs: the agent core, the network and the cloud-mode commands.
COPY packages/tau-core /src/tau-core
COPY packages/tau-net /src/tau-net
COPY packages/tau-cloud /src/tau-cloud
RUN uv pip install --system /src/tau-core /src/tau-net /src/tau-cloud

# Config root and data directory; `tau cloud run` fills them from the spine at start.
ENV TAU_HOME=/tau \
    TAU_DATA_DIR=/data
RUN useradd --system --create-home --home-dir /home/tau tau \
    && mkdir -p /tau /data \
    && chown tau:tau /tau /data
USER tau
WORKDIR /tau

# The spine talks to the brain on this port (TauBrain.defaultPort); `GET /health` answers
# {"ok": true, "version", "hub"} (TAU_CLOUD_HEALTH_PORT overrides the port).
EXPOSE 8080
# `tau cloud run` is PID 1: it pulls tau.toml and the persona files into /tau, then runs
# `tau hub run` in the same process. SIGTERM stops the hub cleanly (exit 0); it needs
# TAU_SPINE_URL and TAU_SPINE_TOKEN, which the spine sets, and exits 1 without them.
STOPSIGNAL SIGTERM
CMD ["tau", "cloud", "run"]
