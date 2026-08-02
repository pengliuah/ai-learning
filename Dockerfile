# ---------- Stage 1: frontend build ----------
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: backend ----------
FROM python:3.12-slim
WORKDIR /app/backend

# Aliyun PyPI mirror (国内加速)
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# Install backend dependencies (pip respects PIP_INDEX_URL)
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "langchain>=0.3" \
    "langchain-openai>=0.3" "langchain-core>=0.3" "langgraph>=0.2" \
    "deepagents>=0.5" "pydantic>=2.9" "pydantic-settings>=2.5" \
    "python-dotenv>=1.0" "psycopg[binary,pool]>=3.2"

# Copy backend source
COPY backend/ ./

# Copy frontend build output (served by FastAPI as static files)
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Data directory (mount as volume for persistence)
RUN mkdir -p /app/backend/data
VOLUME /app/backend/data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]