FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends nodejs npm psmisc \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app

COPY --chown=appuser:appuser pyproject.toml README.md langgraph.json mcp.json ./
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser skills ./skills

RUN python -m pip install --no-cache-dir --editable .

USER appuser

EXPOSE 8000 2024

CMD ["python", "-m", "ssw.start_web"]
