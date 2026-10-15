FROM python:3.12-slim
WORKDIR /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY evals ./evals
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "18080"]
