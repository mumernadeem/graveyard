# ─── Graveyard CLI — Docker Image ────────────────────────────────────
# Run incident-trained deploy gates in your CI/CD pipeline.
#
# Usage:
#   docker run --rm -v $(pwd):/project graveyard:local check
#
# Build locally:
#   docker build -t graveyard:local .
# ─────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

LABEL org.opencontainers.image.title="Graveyard"
LABEL org.opencontainers.image.description="Incident-trained deploy gates. Your worst days become your strongest safeguards."
LABEL org.opencontainers.image.source="https://github.com/mumernadeem/graveyard"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.version="0.4.0"

# Install Trivy for security scanning (optional dependency, used by security_check)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates git && \
    curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin && \
    apt-get purge -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Install pytest + PyYAML so users can also run tests inside the container
# (PyYAML is optional — Graveyard has its own minimal parser, but PyYAML is preferred when present)
RUN pip install --no-cache-dir pyyaml

# App directory: where Graveyard's source lives
WORKDIR /app

# Copy the CLI source
COPY src/cli/ /app/cli/

# Copy sample data so `graveyard demo` works out-of-the-box inside the container
COPY tests/ /app/tests/
COPY incidents/ /app/incidents/
COPY examples/ /app/examples/
COPY .graveyard.example.yml /app/.graveyard.example.yml

# Make the CLI executable + symlink to /usr/local/bin so it runs as `graveyard`
RUN chmod +x /app/cli/graveyard.py && \
    ln -s /app/cli/graveyard.py /usr/local/bin/graveyard

# User mounts their project here
WORKDIR /project

ENTRYPOINT ["graveyard"]
CMD ["--help"]
