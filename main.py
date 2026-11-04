# -*- coding: utf-8 -*-
"""
Fiduciary Clearing Engine + DAO Treasury Intelligent Search Relay
Production v4.2.1 — Yahoo HTML scraping + RSS parsing, no DD, no cold-start dependency
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
import uuid as _uuid
import datetime as _datetime
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, Asset

app = Flask(__name__)

searxno_ready = False

DAO_TREASURY = 'GCATMWLZ7EU7EUWJ3LS6SBHKILWEUS3QBALHGF3XH4IZCOPJHFB5DJYW'
FRAMEWORK_REF = 'US-SFE-PFIA-2025-T1A01'
DTI_TOKEN = 'BGP5VXJME'
USDC_ISSUER = 'GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN'
USD_ISSUER = 'GCVDS3YYXQVFVVG4HSIBZAHQJAGMQUM6ZTJHUOQGEZHEV4VN2CX5SAT3'
CLOB_SETTLEMENT_TX = '65947e881619d0374c69a25481665f05f9e0d59e84cf79438961ed5bfefdd58b'
CLOB_SETTLEMENT_LEDGER = '65120726'
SETTLEMENT_AMOUNT = '250000'

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
        'version': '4.2.0-production',
        'searxno_ready': searxno_ready
    })

@app.route('/')
def index():
    return jsonify({'service': 'DAO Treasury Clearing Engine', 'version': '4.2.1'})

@app.route('/pacs008', methods=['POST', 'GET'])
def pacs008():
    try:
        body = request.get_json(silent=True) or {}
        amount = body.get('amount', SETTLEMENT_AMOUNT)
        currency = body.get('currency', 'USD')
        msg_id = 'SFE-' + _uuid.uuid4().hex[:12].upper()
        uetr = body.get('uetr', str(_uuid.uuid4()))
        now = _datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {
            'MsgId': msg_id, 'CreDtTm': now, 'NbOfTxs': '1',
            'IntrBkSttlmAmt': {('Ccy': currency, 'value': amount},
            'Cdtr': DAO_TREASURY, 'UETR': uetr,
            'RmtInf': FRAMEWORK_REF + ' DTI:' + DTI_TOKEN + ' CLOB:' + CLOB_SETTLEMENT_TX
        }
        return jsonify({'status': 'accepted', 'step': 'pacs008', 'msg_id': msg_id, 'uetr': uetr, 'amount': amount, 'currency': currency, 'treasury': DAO_TREASURY, 'framework': FRAMEWORK_REF, 'dti': DTI_TOKEN, 'clob_settlement_tx': CLOB_SETTLEMENT_TX, 'payload': payload, 'timestamp': now})
    except Exception as e:
        return jsonify({'status': 'error', 'step': 'pacs008', 'error': str(e)}), 500

@app.route('/ach', methods=['POST', 'GET'])
def ach():
    try:
        body = request.get_json(silent=True) or {}
        amount_cents = body.get('amount_cents', int(SETTLEMENT_AMOUNT) * 100)
        uetr = body.get('uetr', str(_uuid.uuid4()))
        now = _datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        moov_url = os.environ.get('MOOV_ACH_URL', 'http://localhost:8080')
        ach_payload = {'id': uetr, 'transferAmount': amount_cents, 'currency': 'USD', 'description': FRAMEWORK_REF, 'destination': {'routingNumber': os.environ.get('ACH_DESTINATION_ROUTING', '021000021'), 'accountNumber': os.environ.get('ACH_DESTINATION_ACCOUNT', ''), 'accountType': 'checking', 'holderName': 'SF Emerald Dynasty DAO Treasury'}}
        moov_status = 'pending'
        moov_response = None
        try:
            r = requests.post(moov_url + '/files/create', json=ach_payload, timeout=5)
            moov_status = 'submitted' if r.status_code in [200, 201, 202] else 'error'
            moov_response = r.text[:200]
        except Exception as moov_err:
            moov_status = 'container_unavailable'
            moov_response = str(moov_err)
        return jsonify({'status': moov_status, 'step': 'ach', 'uetr': uetr, 'amount_cents': amount_cents, 'amount_usd': amount_cents / 100, 'framework': FRAMEWORK_REF, 'moov_url': moov_url, 'moov_response': moov_response, 'timestamp': now})
    except Exception as e:
        return jsonify({'status': 'error', 'step': 'ach', 'error': str(e)}), 500

@app.route('/transmit', methods=['POST', 'GET'])
def transmit():
    try:
        body = request.get_json(silent=True) or {}
        uetr = body.get('uetr', str(_uuid.uuid4()))
        amount = body.get('amount', SETTLEMENT_AMOUNT)
        currency = body.get('currency', 'USD')
        now = _datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        executor_public = os.environ.get('EXECUTOR_PUBLIC', 'GCHQWVJ56MQNWSDAXSQEO74WIT76VCCDYLWOWATGRD7SNMCZIQOCEHML')
        manifest = {'framework': FRAMEWORK_REF, 'dti': DTI_TOKEN, 'clob_settlement_tx': CLOB_SETTLEMENT_TX, 'clob_settlement_ledger': CLOB_SETTLEMENT_LEDGER, 'amount': amount, 'currency': currency, 'treasury': DAO_TREASURY, 'usdc_issuer': USDC_ISSUER, 'uetr': uetr, 'timestamp': now, 'instruction': 'ISSUE_USDC_TO_TREASURY', 'anchor': 'mgxanchor.moneygram.com', 'executor_public': executor_public, 'signature_ref': 'SEP-10:' + executor_public[:8] + '...' + executor_public[-4:]}
        sftp_url = os.environ.get('SFTP_DELIVERY_URL', '')
        delivery_status = 'manifest_ready_awaiting_sftp_config'
        delivery_response = None
        if sftp_url:
            try:
                r = requests.post(sftp_url, json=manifest, timeout=10)
                delivery_status = 'delivered' if r.status_code in [200, 201, 202] else 'delivery_error'
                delivery_response = r.text[:200]
            except Exception as sftp_err:
                delivery_status = 'sftp_unavailable'
                delivery_response = str(sftp_err)
        return jsonify({'status': delivery_status, 'step': 'transmit', 'uetr': uetr, 'manifest': manifest, 'delivery_response': delivery_response, 'timestamp': now})
    except Exception as e:
        return jsonify({'status': 'error', 'step': 'transmit', 'error': str(e)}), 500

@app.route('/stellar', methods=['POST', 'GET'])
def stellar_payment():
    try:
        body = request.get_json(silent=True) or {}
        amount = str(body.get('amount', SETTLEMENT_AMOUNT))
        uetr = body.get('uetr', str(_uuid.uuid4()))
        now = _datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

        # GCHQ Fiduciary Executor signs - sends USD:GCVDS3 to DAO Treasury
        source_secret = os.environ.get('GCHQ_SECRET', 'SBTXFQABN3XNCJJFZGOQRQO3P4USQTG2INX2UVOHWUCKRZRNRWU7FZR7')
        source_keypair = Keypair.from_secret(source_secret)
        destination = DAO_TREASURY

        # USD:GCVDS3 - CLOB Cold Issuer asset
        usd_asset = Asset('USD', USD_ISSUER)

        # Stellar Horizon
        server = Server('https://horizon.stellar.org')

        # Load source account
        source_account = server.load_account(source_keypair.public_key)

        # Build transaction
        transaction = (
            TransactionBuilder(
                source_account=source_account,
                network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE,
                base_fee=100
            )
            .append_payment_op(
                destination=destination,
                asset=usd_asset,
                amount=amount,
                source=source_keypair.public_key
            )
            .add_text_memo(uetr[:28])
            .set_timeout(30)
            .build()
        )

        # Sign
        transaction.sign(source_keypair)

        # Submit
        response = server.submit_transaction(transaction)

        return jsonify({
            'status': 'submitted',
            'step': 'stellar_payment',
            'tx_hash': response.get('hash', ''),
            'ledger': response.get('ledger', ''),
            'amount': amount,
            'asset': 'USD',
            'destination': destination,
            'source': source_keypair.public_key,
            'uetr': uetr,
            'timestamp': now
        })

    except Exception as e:
        return jsonify({'status': 'error', 'step': 'stellar_payment', 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

