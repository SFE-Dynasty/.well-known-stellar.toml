# -*- coding: utf-8 -*-
"""
Fiduciary Clearing Engine + DAO Treasury Intelligent Search Relay
Production v4.0.0 — Yahoo HTML scraping + RSS parsing, no DD, no cold-start dependency
"""

import os
import json
import threading
import subprocess
import time
import re
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

searxno_ready = False

def start_searxng():
    global searxno_ready
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
                    searxno_ready = True
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
}

BLOCK_SIGNALS = [
    'unusual traffic', 'captcha', 'enable javascript',
    'detected unusual', 'not a robot', 'verify you are human',
    'access denied', 'blocked', 'please enable cookies'
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
            snippet = res.get('content', '')
            url = res.get('url', '')
            if title or snippet:
                output.append(title + ': ' + snippet + ' (' + url + ')')
        return ' | '.join(output) if output else None
    except Exception:
        return None

def search_via_yahoo(query):
    try:
        url = 'https://search.yahoo.com/search?p=' + requests.utils.quote(query) + '&n=5'
        r = requests.get(url, headers=HEADERS, timeout=10)
        if is_blocked(r.text):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for item in soup.select('.algo-sr, .Sr')[:5]:
            title_el = item.select_one('h3, .title')
            snippet_el = item.select_one('.compText, p')
            title = title_el.get_text(strip=True) if title_el else ''
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            if title or snippet:
                results.append(title + ': ' + snippet)
        return ' | '.join(results) if results else None
    except Exception:
        return None

def search_via_bing(query):
    try:
        url = 'https://www.bing.com/search?q=' + requests.utils.quote(query)
        r = requests.get(url, headers=HEADERS, timeout=10)
        if is_blocked(r.text):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for item in soup.select('.b_algo')[:5]:
            title_el = item.select_one('h2')
            snippet_el = item.select_one('.b_caption p, p')
            title = title_el.get_text(strip=True) if title_el else ''
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            if title or snippet:
                results.append(title + ': ' + snippet)
        return ' | '.join(results) if results else None
    except Exception:
        return None

def fetch_rss(url, source_name, max_items=5):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        root = ET.fromstring(r.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = root.findall('.//item') or root.findall('.//atom:entry', ns)
        titles = []
        for item in items[:max_items]:
            title_el = item.find('title') or item.find('atom:title', ns)
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())
        return source_name + ': ' + ' | '.join(titles) if titles else None
    except Exception:
        return None

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'query': query, 'result': 'No query provided', 'source': 'none'})

    # Try SearXNG first (if warm)
    if searxno_ready:
        result = search_via_searxng(query)
        if result:
            return jsonify({'query': query, 'result': result, 'source': 'searxng'})

    # Try Yahoo HTML scraping
    result = search_via_yahoo(query)
    if result:
        return jsonify({'query': query, 'result': result, 'source': 'yahoo'})

    # Try Bing HTML scraping
    result = search_via_bing(query)
    if result:
        return jsonify({'query': query, 'result': result, 'source': 'bing'})

    # RSS fallback --- AP, Reuters, BBC
    rss_results = []
    for rss_url, name in [
        ('https://feeds.apnews.com/rss/apf-topnews', 'AP'),
        ('https://feeds.reuters.com/reuters/topNews', 'Reuters'),
        ('https://feeds.bbci.co.uk/news/rss.xml', 'BBC')
    ]:
        r = fetch_rss(rss_url, name)
        if r:
            rss_results.append(r)
    if rss_results:
        return jsonify({'query': query, 'result': ' || '.join(rss_results), 'source': 'rss'})

    return jsonify({'query': query, 'result': 'No results found for: ' + query, 'source': 'none'})

@app.route('/fetch')
def fetch_url():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'})
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        content = extract_text(r.text, max_chars=4000)
        return jsonify({'url': url, 'content': content, 'status': r.status_code})
    except Exception as e:
        return jsonify({'url': url, 'error': str(e)})

@app.route('/rss')
def rss_feed():
    url = request.args.get('url', '').strip()
    name = request.args.get('name', 'feed')
    result = fetch_rss(url, name)
    return jsonify({'result': result, 'source': name})

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'engine': 'CLOB Orchestration Layer',
        'version': '4.0.0-production',
        'searxno_ready': searxno_ready
    })

@app.route('/')
def index():
    return jsonify({'service': 'DAO Treasury Clearing Engine', 'version': '4.0.0'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
