FROM python:3.11-slim

# Install system dependencies for SearXNG and content extraction
RUN apt-get update && apt-get install -y \
    git \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install SearXNG
RUN pip install searxng

# Set working directory
WORKDIR /app

# Copy app files
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Create SearXNG settings directory
RUN mkdir -p /etc/searxng

# Copy SearXNG settings
COPY searxng/settings.yml /etc/searxng/settings.yml

# Expose port
EXPOSE 8080

# Start Flask app (which internally manages SearXNG queries)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "main:app"]
