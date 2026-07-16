# ---------- Stage 1: frontend build ----------
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: backend ----------
FROM python:3.12-slim
WORKDIR /app/backend

# Install uv (fast Python package manager)
RUN pip install uv

# Install backend dependencies (cached layer)
COPY backend/pyproject.toml backend/uv.lock ./
RUN rm -f .python-version && uv sync --frozen --no-dev

# Copy backend source
COPY backend/ ./

# Copy frontend build output (served by FastAPI as static files)
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Data directory (mount as volume for persistence)
RUN mkdir -p /app/backend/data
VOLUME /app/backend/data

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]