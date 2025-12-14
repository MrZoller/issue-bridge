FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY .env.example .env

# Create directory for database
RUN mkdir -p /data

# Expose port
EXPOSE 8000

# Set environment variables
ENV DATABASE_URL=sqlite:////data/gitlab_sync.db
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "-m", "app.main"]
