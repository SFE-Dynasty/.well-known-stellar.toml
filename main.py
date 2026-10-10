import os
import sys
import hmac
import hashlib
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# Enforce the strict Contract Reference established in your GitHub manifest
EXPECTED_CONTRACT = os.environ.get("CONTRACT_REFERENCE", "US-SFE-PFIA-2025-T1A01")

def verify_bitbond_signature(raw_payload, inbound_signature):
    """Cryptographically validates that the data packet came directly from Bitbond"""
    secret = os.environ.get("BITBOND_WEBHOOK_SECRET", "").encode('utf-8')
    if not secret:
        return False
    computed_signature = hmac.new(secret, raw_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_signature, inbound_signature)

@app.route('/api/v1/clearance', methods=['POST'])
def process_fiduciary_clearance():
    # 1. Capture the raw network payload data string
    raw_data = request.get_data()
    inbound_sig = request.headers.get('X-Bitbond-Signature', '')
    
    # 2. Enforce strict data validation checks before parsing
    if not verify_bitbond_signature(raw_data, inbound_sig):
        return jsonify({"status": "error", "message": "Unauthorized payload source"}), 401
        
    payload = request.get_json()
    tx_data = payload.get("transaction", {})
    memo_text = tx_data.get("memo", "")
    
    # 3. Verify that the inbound block matches your exact Contract tracking reference
    if memo_text != EXPECTED_CONTRACT:
        return jsonify({"status": "error", "message": "Contract mismatch"}), 400

    # 4. Map the exact primary and secondary data columns for your private ledger sheets
    comprehensive_row = {
        # --- Primary Accounting Core ---
        "CLEARING_TIMESTAMP": datetime.utcnow().isoformat() + "Z",
        "CONTRACT_REFERENCE": EXPECTED_CONTRACT,
        "TRANSACTION_ID": tx_data.get("id"),
        "INSTRUMENT_CODE": tx_data.get("asset_code"),
        "ANCHOR_IDENTIFIER": tx_data.get("anchor_name", "Private_Trust_Note_Series_2025"),
        "SURRENDERED_UNITS": float(tx_data.get("amount", 0)),
        "CLEARANCE_STATUS": "SUCCESS_VERIFIED" if tx_data.get("status") == "completed" else "FAILED",
        "TREASURY_CREDIT_OUT": float(tx_data.get("amount", 0)) * 0.20, # 20% Release ratio
        
        # --- Expanded Audit Elements ---
        "SOURCE_CLEARING_NODE": tx_data.get("source_account"),
        "VAULT_DESTINATION": tx_data.get("destination_account"),
        "LEDGER_SEQUENCE": int(tx_data.get("ledger_sequence", 0)),
        "STROOP_FEE_CONSUMED": int(tx_data.get("fee_charged", 0)),
        
        # --- Platform Infrastructure Verification ---
        "BLOCKCHAIN_NETWORK": os.environ.get("STELLAR_NETWORK", "Public"),
        "COMPILER_RUNTIME": f"Python {sys.version.split()[0]}",
        "ROUTING_INFRASTRUCTURE": os.environ.get("RENDER_SERVICE_NAME", "fiduciary-clearing-engine"),
        "PLATFORM_HOSTNAME": os.environ.get("RENDER_EXTERNAL_HOSTNAME", "unknown")
    }
    
    # Stream the compiled dataset straight to your live Render log dashboard terminal screen
    print(f"[TREASURY AUDIT LOG ENTRY]: {comprehensive_row}", flush=True)
    
    return jsonify({"status": "completed", "transaction_id": comprehensive_row["TRANSACTION_ID"]}), 200

if __name__ == '__main__':
    # Internal communication port assigned by Render's compiler runtime
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
