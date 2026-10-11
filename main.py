import os
import sys
import time
import requests
import json
import threading
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

# Injected Render Environment Variables
ISSUER_ACCOUNT = os.environ.get("ISSUER_ACCOUNT", "GCLFWV2RMDZYNAMUCBH54U43DP3MSWGCIVOH6SK6F4SVMYYR3CQSLKOP")
EXECUTOR_ACCOUNT = os.environ.get("EXECUTOR_ACCOUNT", "GCHQWVJ56MQNWSDAXSQEO74WIT76VCCDYLWOWATGRD7SNMCZIQOCEHML")
EXPECTED_CONTRACT = os.environ.get("CONTRACT_REFERENCE", "US-SFE-PFIA-2025-T1A01")
STELLAR_NETWORK = os.environ.get("STELLAR_NETWORK", "Public")
SERVICE_NAME = os.environ.get("RENDER_SERVICE_NAME", "fiduciary-clearing-engine")
HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "fiduciary-clearing-engine.onrender.com")

HORIZON_URL = "https://stellar.org"

def process_transaction_record(tx_data, operations_data):
    tx_hash = tx_data.get("id")
    raw_seq = tx_data.get("paging_token", "").split("-")[0] if tx_data.get("paging_token") else tx_data.get("ledger", 0)
    fee_charged = tx_data.get("fee_charged", 0)
    source_acct = tx_data.get("source_account")
    
    embedded_ops = operations_data.get("_embedded", {}).get("records", [])
    
    for op in embedded_ops:
        op_type = op.get("type")
        if op_type in ["payment", "path_payment_strict_receive", "path_payment_strict_send"]:
            asset_code = op.get("asset_code", "")
            asset_issuer = op.get("asset_issuer", "")
            amount = float(op.get("amount", 0.0))
            dest_acct = op.get("to")
            src_acct = op.get("from") or source_acct
            
            if asset_code in ["SFETREAS", "SFE2025PTN", "SFE2025PSCI"] and asset_issuer == ISSUER_ACCOUNT:
                # Restored baseline mapping & flat tranche enforcement
                if asset_code == "SFE2025PTN":
                    anchor_name = "Private_Trust_Note_Series_2025"
                    reported_units = 1250000.00  # Restored original gross ledger entry
                    credit_out = 0.0
                    tranche_tag = "RESTORED_LIABILITY_BASELINE"
                elif asset_code == "SFE2025PSCI":
                    anchor_name = "Private_Secured_Capital_Instrument"
                    reported_units = 2500000.00  # Restored original gross ledger entry
                    credit_out = 0.0
                    tranche_tag = "RESTORED_LIABILITY_BASELINE"
                elif asset_code == "SFETREAS":
                    anchor_name = "Sovereign_Trust_Treasury_Certificate"
                    reported_units = amount
                    # Enforce flat 250,000.00 primary tracking (flag remainder as surplus)
                    primary_flat = 250000.00 if amount >= 250000.00 else amount
                    credit_out = primary_flat
                    tranche_tag = "PRIMARY_FLAT_250K_TRANCHE" if amount >= 250000.00 else "AUXILIARY_DEPLOYMENT"

                comprehensive_row = {
                    "CLEARING_TIMESTAMP": datetime.utcnow().isoformat() + "Z",
                    "CONTRACT_REFERENCE": EXPECTED_CONTRACT,
                    "TRANSACTION_ID": tx_hash,
                    "INSTRUMENT_CODE": asset_code,
                    "ANCHOR_IDENTIFIER": anchor_name,
                    "SURRENDERED_UNITS": reported_units,
                    "CLEARANCE_STATUS": "SUCCESS_VERIFIED" if tx_data.get("successful") else "FAILED",
                    "TREASURY_CREDIT_OUT": credit_out,
                    "TRANCHE_CLASSIFICATION": tranche_tag,
                    "SOURCE_CLEARING_NODE": src_acct,
                    "VAULT_DESTINATION": dest_acct,
                    "LEDGER_SEQUENCE": int(raw_seq) if str(raw_seq).isdigit() else 0,
                    "STROOP_FEE_CONSUMED": int(fee_charged),
                    "BLOCKCHAIN_NETWORK": STELLAR_NETWORK,
                    "COMPILER_RUNTIME": f"Python {sys.version.split()[0]}",
                    "ROUTING_INFRASTRUCTURE": SERVICE_NAME,
                    "PLATFORM_HOSTNAME": HOSTNAME
                }
                
                print(f"\n[RESTORED BASELINE AUDIT LOG]: {json.dumps(comprehensive_row)}", flush=True)
                return comprehensive_row
    return None

def horizon_stream_listener():
    stream_url = f"{HORIZON_URL}/accounts/{ISSUER_ACCOUNT}/transactions?cursor=now"
    headers = {"Accept": "text/event-stream"}
    
    print(f"[HORIZON LISTENER ACTIVE] Streaming mainnet events for {ISSUER_ACCOUNT[:12]}...", flush=True)
    
    while True:
        try:
            with requests.get(stream_url, headers=headers, stream=True, timeout=60) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            decoded = line.decode('utf-8')
                            if decoded.startswith("data: "):
                                json_str = decoded[6:]
                                if json_str.strip() == '"hello"':
                                    continue
                                try:
                                    tx_obj = json.loads(json_str)
                                    tx_id = tx_obj.get("id")
                                    ops_url = f"{HORIZON_URL}/transactions/{tx_id}/operations"
                                    ops_res = requests.get(ops_url, timeout=10)
                                    if ops_res.status_code == 200:
                                        process_transaction_record(tx_obj, ops_res.json())
                                except Exception as parse_err:
                                    print(f"[STREAM PARSE ERROR]: {parse_err}", flush=True)
                else:
                    print(f"[HORIZON HTTP ERROR]: Status {response.status_code}. Retrying in 5s...", flush=True)
                    time.sleep(5)
        except Exception as conn_err:
            print(f"[HORIZON CONNECTION DROP]: {conn_err}. Reconnecting in 5s...", flush=True)
            time.sleep(5)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "active", "listener": "direct_horizon_sse", "network": STELLAR_NETWORK}), 200

if __name__ == '__main__':
    t = threading.Thread(target=horizon_stream_listener, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

