FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY pyproject.toml ./
COPY company_os ./company_os
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir .
USER app
EXPOSE 8000
CMD ["kozphy", "api", "--host", "0.0.0.0"]
