import hashlib
import hmac
import logging
import os

from flask import Flask, request, jsonify
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LEMLIST_API_KEY = os.environ.get("LEMLIST_API_KEY")
LEMLIST_CAMPAIGN_ID = os.environ.get("LEMLIST_CAMPAIGN_ID")
CLAY_WEBHOOK_URL = os.environ.get("CLAY_WEBHOOK_URL")
CALENDLY_SIGNING_KEY = os.environ.get("CALENDLY_SIGNING_KEY")

# Matched case-insensitively against each Calendly custom question's text,
# since Calendly has no fixed field name for custom form questions.
LINKEDIN_QUESTION_HINTS = ("linkedin",)
DOMAIN_QUESTION_HINTS = ("domain", "website", "company url")
COMPANY_QUESTION_HINTS = ("company", "organization", "organisation")


def verify_calendly_signature(raw_body: bytes, signature_header: str) -> bool:
    if not CALENDLY_SIGNING_KEY:
        return True
    if not signature_header:
        return False

    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    timestamp, signature = parts.get("t"), parts.get("v1")
    if not timestamp or not signature:
        return False

    signed_payload = f"{timestamp}.{raw_body.decode('utf-8')}"
    expected = hmac.new(CALENDLY_SIGNING_KEY.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_answers(questions_and_answers):
    # Each question fills at most one field, checked in this priority order,
    # so a question like "Company website" (matches both "company" and
    # "website") is treated as the domain question and not double-counted
    # as the company-name question too.
    linkedin_url = domain = company_name = None
    for qa in questions_and_answers:
        question = (qa.get("question") or "").lower()
        answer = qa.get("answer")
        if linkedin_url is None and any(h in question for h in LINKEDIN_QUESTION_HINTS):
            linkedin_url = answer
        elif domain is None and any(h in question for h in DOMAIN_QUESTION_HINTS):
            domain = answer
        elif company_name is None and any(h in question for h in COMPANY_QUESTION_HINTS):
            company_name = answer
    return linkedin_url, domain, company_name


def extract_lead(calendly_payload: dict) -> dict:
    email = calendly_payload.get("email")
    qas = calendly_payload.get("questions_and_answers") or []

    linkedin_url, domain, company_name = extract_answers(qas)

    if not domain and email and "@" in email:
        domain = email.split("@", 1)[1]

    return {
        "email": email,
        "firstName": calendly_payload.get("first_name"),
        "lastName": calendly_payload.get("last_name"),
        "companyName": company_name,
        "linkedinUrl": linkedin_url,
        "domain": domain,
    }


def add_to_lemlist(lead: dict) -> None:
    if not (LEMLIST_API_KEY and LEMLIST_CAMPAIGN_ID):
        logger.warning("Lemlist not configured, skipping")
        return
    email = lead["email"]
    url = f"https://api.lemlist.com/api/campaigns/{LEMLIST_CAMPAIGN_ID}/leads/{email}"
    body = {k: v for k, v in lead.items() if k not in ("email", "domain") and v}
    resp = requests.post(url, auth=("", LEMLIST_API_KEY), json=body, timeout=10)
    resp.raise_for_status()
    logger.info("Added %s to Lemlist campaign %s", email, LEMLIST_CAMPAIGN_ID)


def send_to_clay(lead: dict) -> None:
    if not CLAY_WEBHOOK_URL:
        logger.warning("Clay webhook not configured, skipping")
        return
    resp = requests.post(CLAY_WEBHOOK_URL, json=lead, timeout=10)
    resp.raise_for_status()
    logger.info("Sent domain %s to Clay", lead.get("domain"))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/webhook/booking", methods=["POST"])
def booking_webhook():
    raw_body = request.get_data()
    signature_header = request.headers.get("Calendly-Webhook-Signature", "")

    if not verify_calendly_signature(raw_body, signature_header):
        return jsonify({"error": "invalid signature"}), 401

    body = request.get_json(silent=True) or {}
    event_type = body.get("event")
    calendly_payload = body.get("payload") or body  # falls back to a flat body for local testing

    if event_type and event_type != "invitee.created":
        return jsonify({"status": "ignored", "event": event_type}), 200

    lead = extract_lead(calendly_payload)

    if not lead["email"]:
        return jsonify({"error": "no email found in payload"}), 400

    errors = {}
    try:
        add_to_lemlist(lead)
    except requests.RequestException as e:
        logger.exception("Lemlist call failed")
        errors["lemlist"] = str(e)

    try:
        send_to_clay(lead)
    except requests.RequestException as e:
        logger.exception("Clay call failed")
        errors["clay"] = str(e)

    if errors:
        return jsonify({"status": "partial_failure", "errors": errors}), 502

    return jsonify({"status": "ok", "lead": lead})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
