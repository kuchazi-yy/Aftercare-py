FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY scripts ./scripts
COPY data/policies ./data/policies

CMD ["uvicorn", "ac_py.main:app", "--host", "0.0.0.0", "--port", "8080"]
