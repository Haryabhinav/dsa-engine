# Runner image: language toolchains only. No network tools, no package manager
# left behind, no shell utilities beyond what the compilers need.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get purge -y --auto-remove

# Runs as nobody; /work is bind-mounted read-only by the orchestrator.
USER 65534:65534
WORKDIR /work
ENTRYPOINT []
