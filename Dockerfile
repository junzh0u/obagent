# obagent — bundles Python 3.14 + uv + all deps so the NAS needs none of them.
# Build:  docker build -t obagent .
# Run a single pass (Synology Task Scheduler can call this every N minutes).
# --name gives a free overlap guard: a tick that fires while one is still
# running just errors ("name in use") and no-ops, so passes never race.
#   docker run --rm --name paperless-sync \
#     -e OBAGENT_VAULT=/vault/Paperless -e OBAGENT_CONSUME=/inbox \
#     -e OBAGENT_EXPORT=/drive -e NOTION_TOKEN=… -e MISTRAL_API_KEY=… -e OPENAI_API_KEY=… \
#     -v /volume1/paperless-vault:/vault -v /volume1/scan-inbox:/inbox \
#     -v /volume1/drive-export:/drive -v /volume1/obagent/ssh:/root/.ssh:ro \
#     obagent
# (run.sh also flocks the vault, so `docker exec`/loop invocations don't overlap.)
FROM python:3.14-slim

# git/ssh: needed by the publish step to push the vault to GitHub/GitLab.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Trust the bind-mounted vault repo. The container runs as root, but the mounted
# vault files are owned by the NAS user — without this, git's "dubious ownership"
# guard blocks sync's git-diff narrowing, the machine commit, and the push.
RUN git config --system --add safe.directory '*'

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
# Resolve deps first (cached layer), then install the project.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# Default: one pass, then exit (ideal for Task Scheduler `docker run --rm`).
# For a self-contained loop instead, override CMD:
#   ["sh","-c","while true; do /app/scripts/run.sh; sleep 60; done"]
CMD ["/app/scripts/run.sh"]
