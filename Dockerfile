FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# CRITICAL: install msgspec FIRST before SearXNG — SearXNG's setup.py imports it at build time
RUN pip install msgspec==0.18.6

# Set working directory
WORKDIR /app

# Copy and install remaining requirements (excluding searxng — installed separately below)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install SearXNG from git AFTER msgspec is available
RUN pip install git+https://github.com/searxng/searxng.git@master#egg=searxng

# Copy app files
COPY . .

# Create SearXNG settings directory and copy config
RUN mkdir -p /etc/searxng
COPY searxng/settings.yml /etc/searxng/settings.yml

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "main:app"]
