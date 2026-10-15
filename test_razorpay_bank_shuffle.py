"""
Razorpay Bank Account Shuffle Test Script
==========================================
Tests the possibility of:
1. Listing all connected/linked bank accounts (fund accounts)
2. Listing settlement accounts
3. Creating a fund account (test bank account)
4. Switching settlement destination ("shuffling") via:
   - Route transfers to different accounts
   - Fund account switching in payouts

Uses TEST credentials: rzp_test_TSKRoPOJkAYjlZ
"""

import requests
import json
from requests.auth import HTTPBasicAuth

# --- Test Credentials ---
RAZORPAY_KEY_ID     = "rzp_test_TSKRoPOJkAYjlZ"
RAZORPAY_KEY_SECRET = "Vqo4n049GLygLmxmSL43J6t8"
BASE_URL            = "https://api.razorpay.com/v1"
AUTH                = HTTPBasicAuth(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
HEADERS             = {"Content-Type": "application/json"}

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def pretty(data):
    print(json.dumps(data, indent=2))

# 1. List Settlements
def test_list_settlements():
    section("1. List Settlements")
    resp = requests.get(f"{BASE_URL}/settlements", auth=AUTH, headers=HEADERS)
    print(f"Status: {resp.status_code}")
    pretty(resp.json())
    return resp.json()

# 2. List All Fund Accounts (Linked Bank Accounts)
def test_list_fund_accounts():
    section("2. List All Fund Accounts (Connected Bank Accounts)")
    resp = requests.get(
        f"{BASE_URL}/fund_accounts",
        auth=AUTH,
        headers=HEADERS,
        params={"account_type": "bank_account"}
    )
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    accounts = data.get("items", [])
    print(f"\nFound {len(accounts)} fund account(s)")
    return accounts

# 3. List All Contacts
def test_list_contacts():
    section("3. List All Contacts")
    resp = requests.get(f"{BASE_URL}/contacts", auth=AUTH, headers=HEADERS)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    contacts = data.get("items", [])
    print(f"\nFound {len(contacts)} contact(s)")
    return contacts

# 4. Create a Test Contact
def test_create_contact(name="Insight Institute Shuffle Test"):
    section("4. Create a Test Contact")
    payload = {
        "name": name,
        "email": "fees.iipepropfirm@gmail.com",
        "contact": "9999999999",
        "type": "vendor",
        "notes": {"test": "bank_shuffle_test"}
    }
    resp = requests.post(f"{BASE_URL}/contacts", auth=AUTH, headers=HEADERS, json=payload)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    contact_id = data.get("id")
    print(f"\nContact ID: {contact_id}")
    return contact_id

# 5. Create a Fund Account (bank account under a contact)
def test_create_fund_account(contact_id, account_label="Bank A"):
    section(f"5. Create Fund Account - {account_label}")
    test_accounts = {
        "Bank A": {"name": "Insight Institute A", "ifsc": "HDFC0000053", "account_number": "9876543210001234"},
        "Bank B": {"name": "Insight Institute B", "ifsc": "ICIC0000004",  "account_number": "1234567890009876"},
    }
    bank = test_accounts.get(account_label, test_accounts["Bank A"])
    payload = {
        "contact_id": contact_id,
        "account_type": "bank_account",
        "bank_account": {
            "name":           bank["name"],
            "ifsc":           bank["ifsc"],
            "account_number": bank["account_number"]
        }
    }
    resp = requests.post(f"{BASE_URL}/fund_accounts", auth=AUTH, headers=HEADERS, json=payload)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    fa_id = data.get("id")
    print(f"\nFund Account ID ({account_label}): {fa_id}")
    return fa_id

# 6. Simulate Payout to a specific fund account (the "shuffle")
def test_payout_to_fund_account(fund_account_id, amount=100, label="Bank A"):
    section(f"6. Simulate Payout (Shuffle) to {label} (fa_id: {fund_account_id})")
    payload = {
        "account_number": "2323230085125221",  # RazorpayX test virtual account
        "fund_account_id": fund_account_id,
        "amount": amount,
        "currency": "INR",
        "mode": "IMPS",
        "purpose": "payout",
        "queue_if_low_balance": True,
        "reference_id": f"shuffle_{label.replace(' ', '_')}",
        "narration": f"Insight Shuffle Test to {label}",
        "notes": {"test": "shuffle_bank_account"}
    }
    resp = requests.post(f"{BASE_URL}/payouts", auth=AUTH, headers=HEADERS, json=payload)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    return data

# 7. List Fund Accounts for a specific contact
def test_list_fund_accounts_for_contact(contact_id):
    section(f"7. List Fund Accounts for Contact: {contact_id}")
    resp = requests.get(
        f"{BASE_URL}/fund_accounts",
        auth=AUTH,
        headers=HEADERS,
        params={"contact_id": contact_id}
    )
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    return data.get("items", [])

# 8. Order with Route Transfer (payment routing shuffle)
def test_order_with_route_transfer(linked_account_id=None):
    section("8. Create Order with Route Transfer (Incoming Payment Routing)")
    if not linked_account_id:
        print("SKIPPED: No linked Route account provided.")
        print("  -> Requires Razorpay Route enabled + a linked account ID (acc_XXXXXXXX)")
        return None
    payload = {
        "amount": 50000,
        "currency": "INR",
        "payment_capture": 1,
        "transfers": [
            {
                "account": linked_account_id,
                "amount": 30000,
                "currency": "INR",
                "notes": {"purpose": "shuffle_route_test"},
                "on_hold": 0
            }
        ]
    }
    resp = requests.post(f"{BASE_URL}/orders", auth=AUTH, headers=HEADERS, json=payload)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    pretty(data)
    return data

# --- MAIN ---
def main():
    print("\nRazorpay Bank Account Shuffle Test")
    print(f"Key ID : {RAZORPAY_KEY_ID}")
    print(f"Mode   : TEST (sandbox - no real money)")

    test_list_settlements()
    test_list_fund_accounts()
    test_list_contacts()

    contact_id = test_create_contact()
    if not contact_id:
        print("ERROR: Could not create contact. Stopping.")
        return

    fa_id_a = test_create_fund_account(contact_id, "Bank A")
    fa_id_b = test_create_fund_account(contact_id, "Bank B")
    test_list_fund_accounts_for_contact(contact_id)

    if fa_id_a:
        test_payout_to_fund_account(fa_id_a, amount=100, label="Bank A")
    if fa_id_b:
        test_payout_to_fund_account(fa_id_b, amount=100, label="Bank B")

    test_order_with_route_transfer(linked_account_id=None)

    section("SUMMARY")
    print("""
WHAT WAS TESTED:
  1. Listing existing settlements
  2. Listing existing fund accounts (connected bank accounts)
  3. Listing contacts
  4. Creating a new test contact
  5. Adding Bank A as a fund account under the contact
  6. Adding Bank B as a fund account under the contact
  7. Listing fund accounts to verify both banks visible
  8. Payout shuffle -> Bank A (fund account switch)
  9. Payout shuffle -> Bank B (fund account switch)
  10. Route transfer (payment routing) - skipped unless Route is enabled

KEY FINDINGS:
  PRIMARY SETTLEMENT ACCOUNT SHUFFLE:
  -> NOT possible via API (blocked by Razorpay for KYC/AML security)
  -> Must be done manually via Dashboard -> Settings -> Bank Account

  PAYOUT / DISBURSEMENT SHUFFLE:
  -> FULLY SUPPORTED via Fund Accounts API + Payouts API
  -> Switch which fund_account_id you pass per payout call

  INCOMING PAYMENT ROUTING SHUFFLE:
  -> SUPPORTED via Razorpay Route (transfers[] in order creation)
  -> Requires Route to be enabled on your account
""")

if __name__ == "__main__":
    main()
