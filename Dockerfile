FROM python:3.13-slim

WORKDIR /app

# Install DejaVu fonts for PDF export
RUN apt-get update && apt-get install -y \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Environment variables (M2 fix: no hardcoded local defaults)
# Configure via .env file, environment, or the web UI settings panel:
#   AI_ENDPOINT_URL  - LLM API endpoint (e.g., http://host:port/v1)
#   AI_MODEL_NAME    - Model name for book generation
#   AI_API_KEY       - Bearer token (optional)
#   REVIEWER_ENDPOINT_URL  - Reviewer LLM endpoint (optional, defaults to writer's)
#   REVIEWER_MODEL_NAME    - Reviewer model (optional, defaults to writer's)
#   HULLUCINATOR_HOST      - Bind address (default: 0.0.0.0)
#   HULLUCINATOR_PORT      - Port (default: 8000)
#   PDF_FONT_DIR           - Font directory for PDF export
#   LOG_LEVEL              - Logging level (default: INFO)
#   AI_TIMEOUT             - HTTP client timeout in seconds (default: 1800)

ENV HULLUCINATOR_HOST=0.0.0.0
ENV HULLUCINATOR_PORT=8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
