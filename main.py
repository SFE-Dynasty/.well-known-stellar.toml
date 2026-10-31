"""
Fiduciary Clearing Engine + DAO Treasury Intelligent Search Relay
Production | v3.0.0
"""

import os
import json
import threading
import subprocess
import time
import re
from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# ═══ SEARXNG PROCESS MANAGEMENT ══════════════════════════════════════════════
searxng_ready = False

def start_searxng():
    global searxng_ready
    try:
        # Start SearXNG as a subprocess on port 8888
        env = os.environ.copy()
        env['SEARXMNG_SETTINGS_PATH'] = '/etc/searxng/settings.yml'
        proc = subprocess.Popen(
            ['python', '-m', 'searxng.webapp'],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # Wait for SearXNG to be ready
        for _ in range(30):
            time.sleep(2)
            try:
                r = requests.get('http://localhost:8888/search?q=test&format=json', timeout=3)
                if r.status_code == 200:
                    searxng_ready = True
                    print('SearXNG ready')
                    return
            except:
                pass
        print('SearXNG startup timeout — using direct fetch fallback')
    except Exception as e:
        print(f'SearXNG start error: {e} — using direct fetch fallback')

# Start SearXNG in background thread on boot
threading.Thread(target=start_searxng, daemon=True).start()

# ═══ BROWSER HEADERS ══════════════════════════════════════════════════════════
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Referer': 'https://www.google.com/'
}

def extract_text(html, max_chars=3000):
    """Strip HTML to clean readable text."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # Remove scripts, styles, nav, footer
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except:
        return html[:max_chars]

def search_via_searxng(query):
    """Search using local SearXNG instance."""
    try:
        r = requests.get(
            'http://localhost:8888/search',
            params={'q': query, 'format': 'json', 'language': 'en'},
            timeout=10
        )
        data = r.json()
        results = data.get('results', [])[:5]
        output = []
        for res in results:
            title = res.get('title', '')
            content = res.get('content', '')
            url = res.get('url', '')
            if content:
                output.append(f"{title}: {content} [{url}]")
        return '\n'.join(output)
    except Exception as e:
        return None

def search_via_google(query):
    """Direct Google fetch fallback."""
    try:
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=5&hl=en"
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        snippets = []
        # Extract result divs
        for div in soup.find_all('div', class_=['BNeawe', 'VwiC3b', 'yXK7Lf']):
            text = div.get_text(strip=True)
            if len(text) > 30:
                snippets.append(text)
        if snippets:
            return '\n'.join(snippets[:5])
        # Fallback: extract any paragraph text
        text = extract_text(r.text, 2000)
        return text if len(text) > 50 else None
    except:
        return None

def search_via_bing(query):
    """Direct Bing fetch fallback."""
    try:
        url = f"https://www.bing.com/search?q={requests.utils.quote(query)}&count=5"
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        snippets = []
        for div in soup.find_all('div', class_=['b_caption', 'b_snippet']):
            text = div.get_text(strip=True)
            if len(text) > 30:
                snippets.append(text)
        if snippets:
            return '\n'.join(snippets[:5])
        text = extract_text(r.text, 2000)
        return text if len(text) > 50 else None
    except:
        return None

def fetch_page(url):
    """Fetch and extract text from any URL — HTML, API docs, etc."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        ct = r.headers.get('Content-Type', '')
        if 'json' in ct:
            return json.dumps(r.json(), indent=2)[:3000]
        return extract_text(r.text, 3000)
    except:
        return None

# ═══ SEARCH ENDPOINT ══════════════════════════════════════════════════════════
@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    result = None

    # Try SearXNG first (aggregates 70+ engines)
    if searxng_ready:
        result = search_via_searxng(query)

    # Fallback: Google direct
    if not result:
        result = search_via_google(query)

    # Fallback: Bing direct
    if not result:
        result = search_via_bing(query)

    # If a URL was passed as query, fetch it directly
    if not result and query.startswith('http'):
        result = fetch_page(query)

    if result:
        return jsonify({'query': query, 'result': result, 'source': 'searxng+web'})
    else:
        return jsonify({'query': query, 'result': 'Search returned no results for: ' + query, 'source': 'none'})

# ═══ PAGE FETCH ENDPOINT ═══════════════════════════════════════════════════════
@app.route('/fetch')
def fetch():
    """Fetch and extract any URL ~ API DOcs, PDFs, news articles, anything."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    result = fetch_page(url)
    if result:
        return jsonify({'url': url, 'content': result})
    return jsonify({'url': url, 'content': 'Could not fetch: ' + url})

# ═══ CLEARING ENFINE ROUTES (preserved) ═══════════════════════════════════════
@app.route('/')
def index():
    return jsonify({
        'engine': 'CLOB Orchestration Layer',
        'status': 'live',
        'version': '3.0.0-production',
        'home_domain': 'sfe-dynasty.github.io',
        'issuer': 'GCLFWV2RMDZYNAMUC@��4U43DP3MSWGCIVOH6SK6F4SVMYYR3CQSLKOP',
        'asset': 'SFETREAS',
        'agreed_amount': 250000,
        'clearing_counterparty': 'Stellar Native CLOB',
        'offer_id': '1861780521',
        'offer_remaining': 0,
        'offer_status': 'consumed',
        'settlement_type': 'Bilateral Atomic DvP'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'engine': 'CLOB Orchestration Layer',
        'version': '3.0.0-production',
        'searxng_ready': searxng_ready
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
