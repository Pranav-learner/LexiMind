# ==========================================================
# Multi-stage Dockerfile for LexiMind Production Platform
# ==========================================================

# --- Stage 1: Build Dependencies ---
FROM python:3.11-alpine AS builder

WORKDIR /build
RUN apk add --no-cache gcc musl-dev libffi-dev g++ postgresql-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# --- Stage 2: Development Stage ---
FROM python:3.11-alpine AS development

WORKDIR /app
RUN apk add --no-cache libpq curl

COPY --from=builder /install /usr/local
COPY . .

ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=development
ENV DATABASE_URL=sqlite:///leximind.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- Stage 3: Production Minimal alpine Stage ---
FROM python:3.11-alpine AS production

WORKDIR /app
RUN apk add --no-cache libpq curl \
    && addgroup -S leximind && adduser -S leximind -G leximind

COPY --from=builder /install /usr/local
COPY . .

# Secure permissions for non-root execution
RUN chown -R leximind:leximind /app
USER leximind

ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

EXPOSE 8000

# Health check probes (readiness/liveness)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
