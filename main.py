import os
import sys
import time
import json
import threading
from datetime import datetime
from flask import Flask, jsonify, request

# Import all necessary enterprise Stellar SDK components
import requests
from stellar_sdk import Server, Network, Asset, Keypair, TransactionEnvelope
from stellar_sdk.transaction_builder import TransactionBuilder
from stellar_sdk.operation import PathPaymentStrictReceive
from stellar_sdk.memo import TextMemo

app = Flask(__name__)

# Injected Render Environment Variables
ISSUER_ACCOUNT = os.environ.get("ISSUER_ACCOUNT", "GCLFWV2RMDZYNAMUCBH54U43DP3MSWGCIVOH6SK6F4SVMYYR3CQSLKOP")
EXECUTOR_ACCOUNT = os.environ.get("EXECUTOR_ACCOUNT", "GCHQWVJ56MQNWSDAXSQEO74WIT76VCCDYLWOWATGRD7SNMCZIQOCEHML")
EXPECTED_CONTRACT = os.environ.get("CONTRACT_REFERENCE", "US-SFE-PFIA-2025-T1A01")
STELLAR_NETWORK = os.environ.get("STELLAR_NETWORK", "Public")
SERVICE_NAME = os.environ.get("RENDER_SERVICE_NAME", "fiduciary-clearing-engine")
HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "fiduciary-clearing-engine.onrender.com")

HORIZON_URL = "https://horizon.stellar.org"
USDC_ISSUER = "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN"

# --- 2. NEW AUTOMATED PROTOCOL FUNCTION (SEP-10 & SEP-24) ---
def get_moneygram_destination(executor_kp, delivery_amount):
    """Automates the live SEP-10 & SEP-24 signature loop directly with MoneyGram's production engine."""
    mg_auth_url = "https://mgxanchor.moneygram.com/stellarsepservice/auth"
    mg_transfer_url = "https://mgxanchor.moneygram.com/stellarsepservice/sep24"
    
    # 1. Request the SEP-10 challenge transaction
    res_challenge = requests.get(mg_auth_url, params={"account": executor_kp.public_key}, timeout=10)
    if res_challenge.status_code != 200:
        raise Exception(f"MoneyGram challenge request failed: {res_challenge.text}")
    challenge_xdr = res_challenge.json()["transaction"]
    
    # 2. Cryptographically sign the Challenge using the Fiduciary Executor private keys
    envelope = TransactionEnvelope.from_xdr(challenge_xdr, network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE)
    envelope.transaction.sign(executor_kp)
    
    # 3. Submit back to acquire the production JWT security token
    res_jwt = requests.post(mg_auth_url, json={"transaction": envelope.to_xdr()}, timeout=10)
    if res_jwt.status_code != 200:
        raise Exception(f"MoneyGram JWT retrieval failed: {res_jwt.text}")
    jwt_token = res_jwt.json()["token"]
    
    # 4. Use the JWT token to request the active payment destination from MoneyGram
    headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
    transfer_payload = {
        "asset_code": "USDC",
        "amount": str(delivery_amount),
        "account": executor_kp.public_key
    }
    
    res_destination = requests.post(
        f"{mg_transfer_url}/transactions/deposit/interactive", 
        json=transfer_payload, 
        headers=headers, 
        timeout=10
    )
    if res_destination.status_code != 200:
        raise Exception(f"Interactive URL generation failed: {res_destination.text}")
        
    return res_destination.json().get("url")
    
def process_transaction_record(tx_data, operations_data):
    """Parses raw transaction details from the Horizon ledger into a structured dictionary."""
    tx_hash = tx_data.get("id")
    raw_seq = tx_data.get("ledger", 0)
    fee_charged = tx_data.get("fee_charged", 0)
    source_acct = tx_data.get("source_account")
    
    # 1. Safely extract nested records list upfront
    embedded_ops = operations_data.get("_embedded", {}).get("records", []) if isinstance(operations_data, dict) else []
    
    # 2. Run your established auditing integration loop
    for op in embedded_ops:
        op_type = op.get("type")
        
        if op_type in ["payment", "path_payment_strict_receive", "path_payment_strict_send"]:
            asset_type = op.get("asset_type", "")
            if asset_type != "native":
                asset_code = op.get("asset_code", "")
                asset_issuer = op.get("asset_issuer", "")
                amount = float(op.get("amount", 0.0))
                dest_acct = op.get("to")
                src_acct = op.get("from") or source_acct
                
                # FIRST CHECK: Core Fiduciary Assets
                if asset_code in ["SFETREAS", "SFE2025PTN", "SFE2025PSCI"] and asset_issuer == ISSUER_ACCOUNT:
                    if asset_code == "SFE2025PTN":
                        anchor_name = "Private_Trust_Note_Series_2025"
                        reported_units = 1250000.00
                        credit_out = 0.0
                        tranche_tag = "RESTORED_LIABILITY_BASELINE"
                    elif asset_code == "SFE2025PSCI":
                        anchor_name = "Private_Sovereign_Credit_Instrument"
                        reported_units = 2500000.00
                        credit_out = 0.0
                        tranche_tag = "RESTORED_LIABILITY_BASELINE"
                    elif asset_code == "SFETREAS":
                        anchor_name = "Sovereign_Trust_Treasury_Certificate"
                        reported_units = amount
                        primary_base_cap = 250000.00
                        credit_out = min(amount, primary_base_cap) if amount > 0 else 0.0
                        surplus_remainder = max(0.0, amount - primary_base_cap)
                        tranche_tag = f"PRIMARY_FLAT_250K_CAP (OnChain_Sent={amount:.2f}, Surplus_Reserved={surplus_remainder:.2f})"

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
                        "LEDGER_SEQUENCE": int(raw_seq),
                        "STROOP_FEE_CONSUMED": int(fee_charged),
                        "BLOCKCHAIN_NETWORK": STELLAR_NETWORK,
                        "COMPILER_RUNTIME": f"Python {sys.version.split()}",
                        "ROUTING_INFRASTRUCTURE": SERVICE_NAME,
                        "PLATFORM_HOSTNAME": HOSTNAME
                    }
                    print(f"\n[RESTORED BASELINE AUDIT LOG]: {json.dumps(comprehensive_row)}", flush=True)
                    return comprehensive_row
                
                # SECOND CHECK: MoneyGram Corridor Asset (Aligned correctly inside the loop!)
                elif asset_code == "USDC" and asset_issuer == USDC_ISSUER and dest_acct == EXECUTOR_ACCOUNT:
                    comprehensive_row = {
                        "CLEARING_TIMESTAMP": datetime.utcnow().isoformat() + "Z",
                        "CONTRACT_REFERENCE": EXPECTED_CONTRACT,
                        "TRANSACTION_ID": tx_hash,
                        "INSTRUMENT_CODE": "SFETREAS->USDC",
                        "ANCHOR_IDENTIFIER": "Sovereign_Trust_MoneyGram_Anchor",
                        "SURRENDERED_UNITS": 250000.00,
                        "CLEARANCE_STATUS": "SUCCESS_VERIFIED" if tx_data.get("successful") else "FAILED",
                        "TREASURY_CREDIT_OUT": amount,
                        "TRANCHE_CLASSIFICATION": "PRIMARY_TRANCH_CURRENCY_CONVERSION",
                        "SOURCE_CLEARING_NODE": src_acct,
                        "VAULT_DESTINATION": dest_acct,
                        "LEDGER_SEQUENCE": int(raw_seq),
                        "STROOP_FEE_CONSUMED": int(fee_charged),
                        "BLOCKCHAIN_NETWORK": STELLAR_NETWORK,
                        "COMPILER_RUNTIME": f"Python {sys.version.split()}",
                        "ROUTING_INFRASTRUCTURE": SERVICE_NAME,
                        "PLATFORM_HOSTNAME": HOSTNAME
                    }
                    print(f"\n[MONEYGRAM CORRIDOR CLEARANCE LOG]: {json.dumps(comprehensive_row)}", flush=True)
                    return comprehensive_row
                    
    # 3. Fallback tracking object (Executed ONLY if nothing matches inside the loop)
    return {
        "transaction_hash": tx_hash,
        "ledger_sequence": raw_seq,
        "network_fee": fee_charged,
        "sender": source_acct,
        "operations_count": len(embedded_ops),
        "status": "NON_CLEARING_ASSET_PASSTHROUGH"
    }

def horizon_stream_listener():
    stream_url = f"{HORIZON_URL}/accounts/{EXECUTOR_ACCOUNT}/transactions?cursor=now"
    headers = {"Accept": "text/event-stream"}
    
    print(f"[HORIZON LISTENER ACTIVE] Streaming mainnet events for {EXECUTOR_ACCOUNT[:12]}...", flush=True)
    
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

@app.route('/', methods=['GET'])
def root_status():
    return jsonify({
        "service": "SF Emerald Dynasty Fiduciary Clearing Engine",
        "status": "active",
        "listener": "direct_horizon_sse",
        "contract": EXPECTED_CONTRACT
    }), 200

@app.route('/api/v1/validate-path', methods=['GET'])
def validate_liquidity_path():
    path_query_url = (
        f"{HORIZON_URL}/paths/strict-receive?"
        f"source_account={EXECUTOR_ACCOUNT}&"
        f"destination_asset_type=credit_alphanum4&"
        f"destination_asset_code=USDC&"
        f"destination_asset_issuer={USDC_ISSUER}&"
        f"destination_amount=250000.00"
    )
    try:
        res = requests.get(path_query_url, timeout=10)
        if res.status_code == 200:
            records = res.json().get("_embedded", {}).get("records", [])
            if records:
                return jsonify({
                    "path_status": "AVAILABLE",
                    "source_asset": "SFETREAS",
                    "estimated_source_amount_needed": records[0].get("source_amount"),
                    "destination_delivery": "250000.00 USDC"
                }), 200
        return jsonify({"path_status": "NO_DIRECT_PATH_FOUND", "details": "Awaiting pool or ledger swap counter-offers"}), 200
    except Exception as e:
        return jsonify({"path_status": "QUERY_ERROR", "error": str(e)}), 500

@app.route('/api/v1/digital-settle', methods=['POST'])
def execute_digital_settle():
    if request.headers.get('X-Sovereign-Sig', '') != "Thesfedynasty30*":
        return jsonify({"status": "rejected", "reason": "Invalid gateway signature credentials"}), 401

    payload = request.get_json(silent=True) or {}
    if payload.get("memo", EXPECTED_CONTRACT) != EXPECTED_CONTRACT:
        return jsonify({"status": "error", "reason": "Contract reference verification mismatch"}), 400

    try:
        local_server = Server(HORIZON_URL)
        executor_kp = Keypair.from_secret(os.environ.get("SEP10_SIGNING_PRIVATE_KEY"))
        
        source_account = local_server.load_account(executor_kp.public_key)
        delivery_amount = str(payload.get("amount", "250000.00"))
        max_source_spend = str(payload.get("max_source_spend", "250050.00"))

        # RESOLVE THE MONEYGRAM INTERACTIVE WEB PORTAL LINK VIA THE MODULE
        interactive_web_url = get_moneygram_destination(executor_kp, delivery_amount)

        source_asset = Asset("SFETREAS", ISSUER_ACCOUNT)
        destination_asset = Asset("USDC", USDC_ISSUER)

        # FIXED: Destination changed to a valid public key to execute the path payment on-chain safely
        op_path_pay = PathPaymentStrictReceive(
            send_asset=source_asset, send_max=max_source_spend,
            destination=executor_kp.public_key, dest_asset=destination_asset,
            dest_amount=delivery_amount, path=[]
        )

        envelope = (TransactionBuilder(source_account=source_account, network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE, base_fee=300)
              .append_operation(op_path_pay)
              .add_memo(TextMemo(EXPECTED_CONTRACT[:28]))
              .set_timeout(30).build())

        # Correctly call sign on the Envelope wrapper object
        envelope.sign(executor_kp)
        
        # Submit the finalized signed envelope to your Horizon cluster node
        response = local_server.submit_transaction(envelope)

        # FIXED: Assigned dynamic URL parameter to "VAULT_INTERACTIVE_PORTAL" key instead of forcing it into an on-chain destination field
        live_receipt = {
            "CLEARING_TIMESTAMP": datetime.utcnow().isoformat() + "Z",
            "CONTRACT_REFERENCE": EXPECTED_CONTRACT,
            "TRANSACTION_ID": response.get("hash"),
            "INSTRUMENT_CODE": "SFETREAS->USDC",
            "ANCHOR_IDENTIFIER": "Sovereign_Trust_MoneyGram_Anchor",
            "SURRENDERED_UNITS": float(max_source_spend),
            "CLEARANCE_STATUS": "DIRECT_PRINCIPAL_SETTLED",
            "TREASURY_CREDIT_OUT": float(delivery_amount),
            "VAULT_INTERACTIVE_PORTAL": interactive_web_url,
            "LEDGER_SEQUENCE": int(response.get("ledger")) if response.get("ledger") else 0,
            "BLOCKCHAIN_NETWORK": STELLAR_NETWORK,
            "ROUTING_INFRASTRUCTURE": SERVICE_NAME
        }
        
        print(f"\n[MONEYGRAM CORRIDOR CLEARANCE LOG]: {json.dumps(live_receipt)}", flush=True)
        return jsonify({"status": "settled", "receipt": live_receipt}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 7. HEALTH AND RUNTIME DAEMON INITIALIZATION ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "active", "listener": "direct_horizon_sse", "network": STELLAR_NETWORK}), 200

if __name__ == '__main__':
    t = threading.Thread(target=horizon_stream_listener, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
