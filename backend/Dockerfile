FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unprivileged, so a compromised app process doesn't own the container.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

# Respect the platform-provided $PORT (Railway/Render/Fly), default 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-server-header"]
