# System under test: payments API. Same image for the API and the one-shot seed job.
FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY payments_api ./payments_api

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# One process, no access log: the API is a measurement target, not a production service.
CMD ["uvicorn", "payments_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
