# --- Base image ---
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source files
COPY agent.py .
COPY batch_manager.py .
COPY llm_provider.py .
COPY main.py .
COPY tools.py .

# Cloud Run sets PORT env var; default to 8080
ENV PORT=8080

EXPOSE 8080

# Start the FastAPI server
# Single worker — Cloud Run scales horizontally via new instances, not threads.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1
