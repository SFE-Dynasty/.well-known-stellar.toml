# -*- coding: utf-8 -*-
"""
Fiduciary Clearing Engine + DAO Treasury Intelligent Search Relay
Production v3.1.0
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

searxng_ready = False

def start_searxng():
    global searxng_ready
    try:
        env = os.environ.copy()
        env['SEARXNG_SETTINGS_PATH'] = '/etc/searxng/settings.yml'
        subprocess.Popen(
            ['python', '-m', 'searxng.webapp'],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        for _ in range(30):
            time.sleep(2)
            try:
                r = requests.get('http://localhost:8888/search?q=test&format=json', timeout=3)
                if r.status_code == 200:
                    searxng_ready = True
                    print('SearXNG ready')
                    return
            except Exception:
                pass
        print('SearXNG startup timeout')
    except Exception as e:
        print('SearXNG start error: ' + str(e))

threading.Thread(target=start_searxng, daemon=True).start()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
    'Referer': 'https://www.google.com/'
}

BING_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.bing.com/'
}

BLOCK_SIGNALS = [
    'unusual traffic',
    'captcha',
    'enable javascript',
    'detected unusual',
    'not a robot',
    'verify you are human',
    'access denied',
    'blocked',
    'please enable cookies'
]

def is_blocked(text):
    t = text.lower()
    return any(sig in t for sig in BLOCK_SIGNALS)

def extract_text(html, max_chars=3000):
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception:
        return html[:max_chars]

def search_via_searxng(query):
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
                output.append(title + ': ' + content + ' [' + url + ']')
        return '\n'.join(output) if output else None
    except Exception:
        return None

def search_via_google(query):
    try:
        url = 'https://www.google.com/search?q=' + requests.utils.quote(query) + '&num=5&hl=en'
        r = requests.get(url, headers=HEADERS, timeout=10)
        if is_blocked(r.text):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        snippets = []
        for div in soup.find_all('div', class_=['BNeawe', 'VwiC3b', 'yXK7lf']):
            text = div.get_text(strip=True)
            if len(text) > 30:
                snippets.append(text)
        if snippets:
            return '\n'.join(snippets[:5])
        text = extract_text(r.text, 2000)
        if is_blocked(text):
            return None
        return text if len(text) > 50 else None
    except Exception:
        return None

def search_via_bing(query):
    try:
        url = 'https://www.bing.com/search?q=' + requests.utils.quote(query) + '&count=5'
        r = requests.get(url, headers=BING_HEADERS, timeout=10)
        if is_blocked(r.text):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        snippets = []
        for div in soup.find_all('div', class_=['b_caption', 'b_snippet']):
            text = div.get_text(strip=True)
            if len(text) > 30:
                snippets.append(text)
        if snippets:
            return '\n'.join(snippets[:5])
        text = extract_text(r.text, 2000)
        if is_blocked(text):
            return None
        return text if len(text) > 50 else None
    except Exception:
        return None

def search_via_duckduckgo(query):
    try:
        url = 'https://html.duckduckgo.com/html/?q=' + requests.utils.quote(query)
        r = requests.get(url, headers=HEADERS, timeout=10)
        if is_blocked(r.text):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        snippets = []
        for div in soup.find_all('div', class_='result__snippet'):
            text = div.get_text(strip=True)
            if len(text) > 20:
                snippets.append(text)
        return '\n'.join(snippets[:5]) if snippets else None
    except Exception:
        return None

def fetch_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        ct = r.headers.get('Content-Type', '')
        if 'json' in ct:
            return json.dumps(r.json(), indent=2)[:3000]
        return extract_text(r.text, 3000)
    except Exception:
        return None

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    result = None
    source = 'none'

    if searxng_ready:
        result = search_via_searxng(query)
        if result:
            source = 'searxng'

    if not result:
        result = search_via_bing(query)
        if result:
            source = 'bing'

    if not result:
        result = search_via_duckduckgo(query)
        if result:
            source = 'duckduckgo'

    if not result:
        result = search_via_google(query)
        if result:
            source = 'google'

    if not result and query.startswith('http'):
        result = fetch_page(query)
        if result:
            source = 'direct_fetch'

    if result:
        return jsonify({'query': query, 'result': result, 'source': source})
    return jsonify({'query': query, 'result': 'No results found for: ' + query, 'source': 'none'})

@app.route('/fetch')
def fetch():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    result = fetch_page(url)
    if result:
        return jsonify({'url': url, 'content': result})
    return jsonify({'url': url, 'content': 'Could not fetch: ' + url})

@app.route('/')
def index():
    return jsonify({
        'engine': 'CLOB Orchestration Layer',
        'status': 'live',
        'version': '3.1.0-production',
        'home_domain': 'sfe-dynasty.github.io',
        'issuer': 'GCLFWV2RMDZYNAMUCBH54U43DP3MSWGCIVOH6SK6F4SVMYYR3CQSLKOP',
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
        'version': '3.1.0-production',
        'searxng_ready': searxng_ready
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
