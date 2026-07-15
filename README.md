# Meeting to outreach bridge

Catches a Calendly "meeting booked" webhook, adds the booker to a Lemlist LinkedIn campaign, and hands their company domain off to Clay.

[See the full write-up](https://claude.ai/code/artifact/76511bf9-c4db-48a1-932e-74a56adc983d) for the short version of this README with the real payload and what to build in Clay.

## What it does, and what it doesn't

1. Someone books a call via Calendly. Calendly fires a webhook.
2. This app pulls out their email, name, LinkedIn URL, and company domain from that webhook.
3. It adds them to a Lemlist campaign (a LinkedIn connection-request campaign, for example).
4. It sends the domain (plus name/company) to a Clay webhook.

**What happens after that is entirely Clay's job, not this app's.** Finding director/VP-level growth, marketing, and sales people at that domain, and splitting them across multiple Lemlist campaigns for different senders, is configured inside Clay itself (enrichment columns, Clay's native Lemlist push). This repo's job ends the moment Clay receives a clean domain.

## What to set up in Clay

This app sends Clay one webhook payload per booking, shaped like:

```json
{
  "email": "jane@acme.co",
  "firstName": "Jane",
  "lastName": "Doe",
  "companyName": "Acme Corp",
  "linkedinUrl": "https://linkedin.com/in/janedoe",
  "domain": "acme.co"
}
```

Build one Clay table around that shape:

1. **Import source**: a Clay Webhook table. Grab its URL and put it in `CLAY_WEBHOOK_URL`. Each booking becomes one row, with `domain` as the key column you build off.
2. **Find people at the company**: add a "Find People at Company" (or equivalent people-search) enrichment on the `domain` column. This expands into multiple rows, one per person found at that company.
3. **Filter to the right stakeholders**: add filters (or a formula column) on the enriched rows for:
   - Seniority: Director or VP (exclude individual contributors and, usually, C-level)
   - Department: Growth, Marketing, or Sales
4. **Get each person's LinkedIn URL**: most people-search enrichments return it directly. If not, add a LinkedIn-lookup enrichment keyed on name + company.
5. **Push to Lemlist**: add a "Send to Lemlist" action on the filtered rows. Since you want multiple senders (you plus teammates) sending connection requests, point that action at more than one Lemlist campaign and split rows across them, either with a formula column that rotates a campaign ID per row, or by running the send action separately against each campaign for a slice of the rows. Each Lemlist campaign should be tied to a different sender's LinkedIn account.

The original booker (from step 3) and the stakeholders Clay finds (step 5 above) are two separate audiences hitting two different kinds of Lemlist campaigns, the booker gets a 1:1 warm-up campaign from you, the stakeholders get spread across the team's connection-request campaigns.

## Calendly setup

Calendly doesn't have built-in fields for "LinkedIn URL" or "company domain". Add them as custom questions on your booking form, e.g.:

- "LinkedIn profile URL"
- "Company website / domain"

The app matches these by scanning the question text for words like "linkedin", "domain", or "website", so the exact wording doesn't need to match perfectly, just contain one of those words.

To register the webhook: create a webhook subscription via the Calendly API (`POST /webhook_subscriptions`) pointing at your deployed `/webhook/booking` URL, scoped to the `invitee.created` event. Calendly gives you a signing key when you do this, that's your `CALENDLY_SIGNING_KEY`.

## Deploy it (Railway)

1. Fork or clone this repo.
2. On Railway, create a new project from this repo.
3. In Railway's variables tab, set:
   - `LEMLIST_API_KEY` — your Lemlist API key
   - `LEMLIST_CAMPAIGN_ID` — the campaign new leads get added to
   - `CLAY_WEBHOOK_URL` — the webhook URL from your Clay table
   - `CALENDLY_SIGNING_KEY` — the signing key Calendly gives you when you create the webhook subscription
4. Deploy. Railway gives you a public URL like `https://your-app.up.railway.app`.
5. Register that URL (`/webhook/booking`) as your Calendly webhook subscription endpoint.

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your keys, or leave CALENDLY_SIGNING_KEY blank to skip verification locally
python app.py
```

Test it with a payload shaped like a real Calendly webhook:

```bash
curl -X POST http://localhost:8080/webhook/booking \
  -H "Content-Type: application/json" \
  -d '{
    "event": "invitee.created",
    "payload": {
      "email": "test@example.com",
      "first_name": "Test",
      "last_name": "Booker",
      "questions_and_answers": [
        {"question": "LinkedIn profile URL", "answer": "https://linkedin.com/in/testbooker"},
        {"question": "Company website", "answer": "example.com"}
      ]
    }
  }'
```

## Notes

- If `LEMLIST_API_KEY` or `CLAY_WEBHOOK_URL` are blank, that step is skipped instead of failing the whole request, so you can wire up one integration at a time.
- If no domain question is answered, the app falls back to the domain from the booker's email address.
- If `CALENDLY_SIGNING_KEY` is blank, signature verification is skipped. Fine for local testing, set it in production so random requests can't hit your webhook.
