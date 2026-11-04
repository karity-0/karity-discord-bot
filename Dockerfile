FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends git lua5.3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python scripts/setup_engine.py --destination /opt/karity \
    && useradd --uid 10001 --create-home karity \
    && mkdir -p /work/jobs \
    && chown -R karity:karity /work
ENV KARITY_ENGINE_PATH=/opt/karity KARITY_JOBS_PATH=/work/jobs
USER 10001:10001
CMD ["python", "-m", "karity_bot"]
