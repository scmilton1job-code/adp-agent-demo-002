# --- Base image ---
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements-backend.txt .
RUN pip install --no-cache-dir -r requirements-backend.txt

# Copy backend source files
COPY agent.py .
COPY batch_manager.py .
COPY main.py .
COPY tools.py .

# Cloud Run sets PORT env var; default to 8080 for local docker testing
ENV PORT=8080

# Expose the port
EXPOSE 8080

# Start the FastAPI server
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
