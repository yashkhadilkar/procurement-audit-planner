# Procurement audit planner web app (Part B) for Railway.
#
# Debian slim (glibc): pip installs claude-agent-sdk as a platform wheel that
# carries the Claude Code CLI as one native binary in claude_agent_sdk/_bundled/.
# The binary embeds ripgrep and needs no Node.js. It refuses root only with
# --dangerously-skip-permissions, which the app never passes (it uses dontAsk).
FROM python:3.13-slim-bookworm

# poppler-utils: pdftotext/pdfinfo for the rules and history stages and the QA quote check.
# git: WORK_DIR is its own git repository, committed before and after every run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TMPDIR=/tmp \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# The agents run .venv/bin/python inside WORK_DIR, which symlinks the repo's .venv,
# so the dependencies go in a virtualenv at the repo root, not the system Python.
COPY requirements.txt .
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install -r requirements.txt \
    && test -x "$(/app/.venv/bin/python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')"

COPY . .
RUN test ! -e /app/.env

# Railway sets PORT; WORK_DIR, ANTHROPIC_API_KEY and ACCESS_CODE come from its variables.
# One worker: the app allows one run at a time and keeps that lock in process.
CMD ["sh", "-c", "exec uvicorn app.server:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
