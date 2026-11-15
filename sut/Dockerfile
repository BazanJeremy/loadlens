# System under test: payments API. Same image for the API and the one-shot seed job.
FROM python:3.15.0-slim-trixie@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58

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
