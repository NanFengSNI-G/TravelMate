FROM python:3.12-slim AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY --from=build /opt/venv /opt/venv
COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY evals ./evals
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "18080"]
