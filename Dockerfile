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

# Environment variable defaults
ENV AI_ENDPOINT_URL=http://192.168.0.40:1234
ENV AI_MODEL_NAME=qwen3.6-27b
ENV AI_API_KEY=
ENV HULLUCINATOR_HOST=0.0.0.0
ENV HULLUCINATOR_PORT=8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
