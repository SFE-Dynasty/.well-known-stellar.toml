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

# Pre-install ALL known SearXNG build-time and runtime dependencies
# so setup.py can import them during metadata generation
RUN pip install \
    msgspec==0.18.6 \
    PyYAML==6.0.1 \
    babel==2.14.0 \
    httpx==0.27.0 \
    httpcore==1.0.5 \
    certifi \
    h11 \
    anyio \
    sniffio \
    idna \
    uvloop \
    redis \
    flask \
    jinja2 \
    markupsafe \
    werkzeug \
    itsdangerous \
    click \
    blinker \
    lxml==5.2.2 \
    requests \
    urllib3 \
    charset-normalizer \
    python-dateutil \
    six \
    pygments \
    markdown-it-py \
    mdurl \
    rich \
    typing-extensions

# Set working directory
WORKDIR /app

# Copy and install app requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install SearXNG with --no-build-isolation so it sees all pre-installed deps
RUN pip install --no-build-isolation git+https://github.com/searxng/searxng.git@master#egg=searxng

# Copy app files
COPY . .

# Create SearXNG settings directory and copy config
RUN mkdir -p /etc/searxng
COPY searxng/settings.yml /etc/searxng/settings.yml

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "main:app"]
