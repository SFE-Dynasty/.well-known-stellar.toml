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

# Install msgspec and other build-time dependencies FIRST
RUN pip install msgspec==0.18.6 httpx==0.27.0 babel==2.14.0

# Set working directory
WORKDIR /app

# Copy and install remaining requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install SearXNG with --no-build-isolation so it can see pre-installed msgspec
RUN pip install --no-build-isolation git+https://github.com/searxng/searxng.git@master#egg=searxng

# Copy app files
COPY . .

# Create SearXNG settings directory and copy config
RUN mkdir -p /etc/searxng
COPY searxng/settings.yml /etc/searxng/settings.yml

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "main:app"]
