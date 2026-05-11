"""
Prian Outreach Agent — autonomous outreach via Chatwoot.
Ingests enriched contacts, creates Chatwoot contacts/conversations, sends messages.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

DB_DSN = "postgresql://aiserver@localhost/avito_parser"

CHATWOOT_URL = os.environ.get("CHATWOOT_URL", "").rstrip("/")
CHATWOOT_TOKEN = os.environ.get("CHATWOOT_TOKEN", "")
CHATWOOT_ACCOUNT_ID = os.environ.get("CHATWOOT_ACCOUNT_ID", "")
CHATWOOT_WHATSAPP_INBOX = os.environ.get("CHATWOOT_WHATSAPP_INBOX", "")

CONTACT_STATUSES = ("new", "outreach_sent", "responded", "in_progress", "closed_won", "closed_lost")
CONVERSATION_STAGES = ("initial", "greeting_sent", "awaiting_response", "negotiating", "proposal_sent", "closed")

DEFAULT_GREETING = (
    "Hi {manager_name}! 👋\n\n"
    "My name is Victor, I'm reaching out from a real estate investment firm.\n\n"
    "We are interested in properties from {company_name} and would like to learn more about your current listings.\n\n"
    "Could you please share more details about available properties and your cooperation terms?\n\n"
    "Looking forward to hearing from you!\n\n"
    "Best regards,\n"
    "Victor"
)

FOLLOWUP_MESSAGES = [
    "Hi! Just following up on our previous message about {company_name}. Are you available to discuss the properties?",
    "Hello! I understand you might be busy. If you have a moment, we'd love to discuss potential cooperation.",
    "Hi! This is our final follow-up. If {company_name} is still interested, please let us know. Otherwise, we wish you success!",
]


def _cw_request(method: str, path: str, data: dict = None, params: dict = None) -> dict:
    url = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "api_access_token": CHATWOOT_TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
        except Exception:
            err = {"error": raw[:500]}
        err["status_code"] = e.code
        return err
    except Exception as e:
        return {"error": str(e)}


def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def extract_wa_number(wa_url: str) -> str:
    if not wa_url:
        return ""
    m = re.search(r'wa\.me/(\d+)', wa_url)
    if m:
        return "+" + m.group(1)
    return ""


def extract_tg_username(tg_url: str) -> str:
    if not tg_url:
        return ""
    m = re.search(r't\.me/([^\s?]+)', tg_url)
    if m:
        return m.group(1)
    return ""


class OutreachAgent:
    def __init__(self, cw_url: str = "", cw_token: str = "", cw_account_id: str = "", cw_inbox_id: str = ""):
        self.cw_url = cw_url or CHATWOOT_URL
        self.cw_token = cw_token or CHATWOOT_TOKEN
        self.cw_account_id = cw_account_id or CHATWOOT_ACCOUNT_ID
        self.cw_inbox_id = cw_inbox_id or CHATWOOT_WHATSAPP_INBOX
        self._db = None

    @property
    def chatwoot_configured(self) -> bool:
        return bool(self.cw_url and self.cw_token and self.cw_account_id)

    @property
    def db(self):
        if self._db is None or self._db.closed:
            self._db = psycopg2.connect(DB_DSN)
        return self._db

    def close(self):
        if self._db and not self._db.closed:
            self._db.close()

    def ingest_contacts(self, companies: list) -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        inserted = 0
        updated = 0
        skipped = 0

        for c in companies:
            cid = c.get("company_id", "")
            if not cid:
                m = re.search(r'/company/([^/.]+)\.html', c.get("company_url", ""))
                cid = m.group(1) if m else ""

            if not cid:
                skipped += 1
                continue

            phones = c.get("phones", []) or []
            if isinstance(phones, str):
                phones = [p.strip() for p in phones.split(",") if p.strip()]

            emails = c.get("emails", []) or []
            if isinstance(emails, str):
                emails = [e.strip() for e in emails.split(",") if e.strip()]

            countries = c.get("countries", []) or []
            if isinstance(countries, str):
                countries = [countries]

            has_contact = bool(phones) or bool(emails) or c.get("whatsapp") or c.get("telegram")
            priority = "high" if has_contact else "low"

            try:
                cur.execute("""
                    INSERT INTO prian_contacts (company_id, company_name, company_url, total_objects, countries,
                        manager_name, manager_position, manager_languages, phones, emails,
                        whatsapp, telegram, description, priority)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (company_id) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        total_objects = EXCLUDED.total_objects,
                        countries = EXCLUDED.countries,
                        manager_name = EXCLUDED.manager_name,
                        manager_position = EXCLUDED.manager_position,
                        manager_languages = EXCLUDED.manager_languages,
                        phones = EXCLUDED.phones,
                        emails = EXCLUDED.emails,
                        whatsapp = EXCLUDED.whatsapp,
                        telegram = EXCLUDED.telegram,
                        description = EXCLUDED.description,
                        priority = EXCLUDED.priority,
                        updated_at = NOW()
                """, (
                    cid,
                    c.get("company_name", ""),
                    c.get("company_url", ""),
                    c.get("total_objects", 0) or 0,
                    countries,
                    c.get("manager_name", ""),
                    c.get("manager_position", ""),
                    c.get("manager_languages", ""),
                    phones,
                    emails,
                    c.get("whatsapp", ""),
                    c.get("telegram", ""),
                    c.get("description", ""),
                    priority,
                ))
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                logger.error(f"Error inserting contact {cid}: {e}")
                skipped += 1

        self.db.commit()
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def get_contacts(self, status: str = None, has_phone: bool = None, limit: int = 50) -> list:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        query = "SELECT * FROM prian_contacts WHERE 1=1"
        params = []
        if status:
            query += " AND status = %s"
            params.append(status)
        if has_phone:
            query += " AND array_length(phones, 1) > 0"
        query += " ORDER BY priority DESC, total_objects DESC NULLS LAST LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]

    def get_contact(self, contact_id: str) -> Optional[dict]:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM prian_contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_stats(self) -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT status, COUNT(*) as cnt,
                   SUM(total_objects) as total_objs
            FROM prian_contacts GROUP BY status ORDER BY cnt DESC
        """)
        by_status = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) as total FROM prian_contacts")
        total = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(*) as cnt FROM prian_contacts WHERE array_length(phones, 1) > 0")
        with_phones = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM prian_contacts WHERE whatsapp IS NOT NULL AND whatsapp != ''")
        with_wa = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM prian_contacts WHERE telegram IS NOT NULL AND telegram != ''")
        with_tg = cur.fetchone()["cnt"]
        return {"total": total, "with_phones": with_phones, "with_whatsapp": with_wa, "with_telegram": with_tg, "by_status": by_status}

    def create_conversation(self, contact_id: str, channel: str = "whatsapp") -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            INSERT INTO prian_conversations (contact_id, channel, status)
            VALUES (%s, %s, 'pending')
            RETURNING *
        """, (contact_id, channel))
        self.db.commit()
        return dict(cur.fetchone())

    def get_conversations(self, status: str = None, limit: int = 50) -> list:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT c.*, ct.company_name, ct.manager_name, ct.phones, ct.whatsapp, ct.telegram,
                   ct.total_objects, ct.countries, ct.chatwoot_id
            FROM prian_conversations c
            JOIN prian_contacts ct ON c.contact_id = ct.id
            WHERE 1=1
        """
        params = []
        if status:
            query += " AND c.status = %s"
            params.append(status)
        query += " ORDER BY c.created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]

    def update_conversation(self, conv_id: str, stage: str = None, status: str = None, next_followup=None) -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        parts = ["updated_at = NOW()"]
        params = []
        if stage:
            parts.append("stage = %s")
            params.append(stage)
        if status:
            parts.append("status = %s")
            params.append(status)
        if next_followup:
            parts.append("next_followup = %s")
            params.append(next_followup)
        params.append(conv_id)
        cur.execute(f"UPDATE prian_conversations SET {', '.join(parts)} WHERE id = %s RETURNING *", params)
        self.db.commit()
        return dict(cur.fetchone())

    def save_message(self, conv_id: str, direction: str, text: str, template_name: str = None,
                     ai_generated: bool = True, chatwoot_msg_id: str = None) -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            INSERT INTO prian_messages (conversation_id, direction, text, template_name, ai_generated, twilio_sid)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (conv_id, direction, text, template_name, ai_generated, chatwoot_msg_id))
        self.db.commit()
        return dict(cur.fetchone())

    def get_messages(self, conv_id: str, limit: int = 50) -> list:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM prian_messages WHERE conversation_id = %s ORDER BY sent_at ASC LIMIT %s
        """, (conv_id, limit))
        return [dict(r) for r in cur.fetchall()]

    def _ensure_conversation(self, contact_id: str, channel: str) -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM prian_conversations WHERE contact_id = %s AND channel = %s ORDER BY created_at DESC LIMIT 1
        """, (contact_id, channel))
        conv = cur.fetchone()
        if conv:
            return dict(conv)
        return self.create_conversation(contact_id, channel)

    def _generate_greeting(self, contact: dict) -> str:
        name = contact.get("manager_name", "") or "there"
        company = contact.get("company_name", "") or "your company"
        return DEFAULT_GREETING.format(
            manager_name=name,
            company_name=company,
        )

    def chatwoot_create_contact(self, contact: dict) -> dict:
        if not self.chatwoot_configured:
            raise Exception("Chatwoot not configured. Set CHATWOOT_URL, CHATWOOT_TOKEN, CHATWOOT_ACCOUNT_ID env vars.")

        phones = contact.get("phones", []) or []
        emails = contact.get("emails", []) or []
        wa_number = extract_wa_number(contact.get("whatsapp", ""))
        tg_username = extract_tg_username(contact.get("telegram", ""))

        phone_numbers = []
        for p in phones:
            phone_numbers.append(normalize_phone(p))
        if wa_number and wa_number not in phone_numbers:
            phone_numbers.insert(0, wa_number)

        custom_attributes = {
            "company_url": contact.get("company_url", ""),
            "total_objects": contact.get("total_objects", 0) or 0,
            "countries": ", ".join(contact.get("countries", []) or []),
            "manager_position": contact.get("manager_position", ""),
            "manager_languages": contact.get("manager_languages", ""),
            "source": "prian.ru",
        }

        payload = {
            "name": contact.get("manager_name", "") or contact.get("company_name", "Unknown"),
            "phone_number": phone_numbers[0] if phone_numbers else "",
            "email": emails[0] if emails else "",
            "custom_attributes": custom_attributes,
        }
        if contact.get("company_name"):
            payload["company_name"] = contact["company_name"]

        result = _cw_request("POST", "/contacts", data=payload)
        if "error" in result:
            if result.get("status_code") == 422:
                existing = _cw_request("GET", "/contacts/search", params={"q": phone_numbers[0] if phone_numbers else ""})
                if existing.get("payload") and existing["payload"].get("contacts"):
                    cw_id = existing["payload"]["contacts"][0]["id"]
                    cur = self.db.cursor()
                    cur.execute("UPDATE prian_contacts SET chatwoot_id = %s WHERE id = %s", (str(cw_id), str(contact["id"])))
                    self.db.commit()
                    return {"id": cw_id, "existing": True}
            logger.error(f"Chatwoot contact create error: {result}")
            raise Exception(f"Chatwoot error: {result.get('error', str(result)[:200])}")

        cw_contact = result.get("payload", {}).get("contact", result)
        cw_id = cw_contact.get("id") or result.get("id")
        if cw_id and str(contact.get("id")):
            cur = self.db.cursor()
            cur.execute("UPDATE prian_contacts SET chatwoot_id = %s WHERE id = %s", (str(cw_id), str(contact["id"])))
            self.db.commit()

        if emails and phone_numbers and cw_id:
            _cw_request("POST", f"/contacts/{cw_id}/phone_numbers", data={"phone_number": phone_numbers[0], "label": "work"})
            if len(phone_numbers) > 1:
                for extra in phone_numbers[1:]:
                    _cw_request("POST", f"/contacts/{cw_id}/phone_numbers", data={"phone_number": extra, "label": "other"})

        return {"id": cw_id, "name": payload["name"]}

    def chatwoot_create_conversation(self, contact_id: str, inbox_id: str = None) -> dict:
        if not self.chatwoot_configured:
            raise Exception("Chatwoot not configured")

        contact = self.get_contact(contact_id)
        if not contact:
            raise Exception(f"Contact {contact_id} not found")

        cw_contact = self.chatwoot_create_contact(contact)

        inbox = inbox_id or self.cw_inbox_id
        if not inbox:
            inboxes = _cw_request("GET", "/inboxes")
            if isinstance(inboxes, list) and inboxes:
                wa_inboxes = [i for i in inboxes if i.get("channel_type") in ("Channel::Whatsapp", "Channel::Sms", "Channel::Telegram")]
                if wa_inboxes:
                    inbox = str(wa_inboxes[0]["id"])
            if not inbox:
                raise Exception("No WhatsApp inbox found in Chatwoot. Configure one first.")

        payload = {
            "source_id": contact.get("company_id", ""),
            "inbox_id": inbox,
            "contact_id": cw_contact["id"],
            "status": "open",
        }

        result = _cw_request("POST", "/conversations", data=payload)
        if "error" in result:
            raise Exception(f"Chatwoot conversation error: {result.get('error', str(result)[:200])}")

        conv = self._ensure_conversation(contact_id, "whatsapp")
        cur = self.db.cursor()
        cur.execute("""
            UPDATE prian_conversations SET chatwoot_conv_id = %s, stage = 'greeting_sent',
                status = 'sent', updated_at = NOW() WHERE id = %s
        """, (str(result.get("id", "")), conv["id"]))
        self.db.commit()

        return {"id": result.get("id"), "cw_contact_id": cw_contact["id"], "local_conv_id": conv["id"]}

    def chatwoot_send_message(self, conv_id: str, text: str = None, template: str = None) -> dict:
        if not self.chatwoot_configured:
            raise Exception("Chatwoot not configured")

        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM prian_conversations WHERE id = %s", (conv_id,))
        conv = dict(cur.fetchone())
        contact_id = conv["contact_id"]
        contact = self.get_contact(str(contact_id))

        msg_text = text or self._generate_greeting(contact)

        cw_conv_id = conv.get("chatwoot_conv_id")
        if not cw_conv_id:
            cw_result = self.chatwoot_create_conversation(str(contact_id))
            cw_conv_id = cw_result.get("id")
            if not cw_conv_id:
                cur2 = self.db.cursor(cursor_factory=RealDictCursor)
                cur2.execute("SELECT * FROM prian_conversations WHERE id = %s", (conv_id,))
                conv = dict(cur2.fetchone())
                cw_conv_id = conv.get("chatwoot_conv_id")

        payload = {"content": msg_text, "message_type": "outgoing", "private": False}
        if template:
            payload["content_type"] = "template"

        result = _cw_request("POST", f"/conversations/{cw_conv_id}/messages", data=payload)

        msg_id = str(result.get("id", ""))
        self.save_message(conv_id, "outgoing", msg_text, template_name=template, chatwoot_msg_id=msg_id)

        cur3 = self.db.cursor()
        cur3.execute("""
            UPDATE prian_contacts SET status = 'outreach_sent', updated_at = NOW() WHERE id = %s
        """, (str(contact_id),))
        self.db.commit()

        return {"message_id": msg_id, "text": msg_text, "conversation_id": cw_conv_id}

    def send_message(self, contact_id: str, text: str = None, channel: str = "whatsapp") -> dict:
        contact = self.get_contact(contact_id)
        if not contact:
            raise Exception(f"Contact {contact_id} not found")

        conv = self._ensure_conversation(contact_id, channel)
        return self.chatwoot_send_message(conv["id"], text=text)

    def get_or_create_chatwoot_contact(self, contact_id: str) -> dict:
        contact = self.get_contact(contact_id)
        if not contact:
            raise Exception(f"Contact {contact_id} not found")

        if contact.get("chatwoot_id"):
            result = _cw_request("GET", f"/contacts/{contact['chatwoot_id']}")
            if "error" not in result:
                return result

        return self.chatwoot_create_contact(contact)

    def get_due_followups(self) -> list:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT c.*, ct.company_name, ct.manager_name, ct.phones, ct.whatsapp, ct.telegram,
                   ct.total_objects, ct.countries, ct.status as contact_status, ct.chatwoot_id
            FROM prian_conversations c
            JOIN prian_contacts ct ON c.contact_id = ct.id
            WHERE c.status IN ('pending', 'sent')
              AND (c.next_followup IS NULL OR c.next_followup <= NOW())
              AND c.followup_count < 3
            ORDER BY ct.priority DESC, ct.total_objects DESC NULLS LAST
        """)
        return [dict(r) for r in cur.fetchall()]

    def process_followup(self, conv_id: str) -> dict:
        cur = self.db.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM prian_conversations WHERE id = %s", (conv_id,))
        conv = dict(cur.fetchone())
        contact_id = conv["contact_id"]
        contact = self.get_contact(str(contact_id))

        followup_idx = min(conv.get("followup_count", 0), len(FOLLOWUP_MESSAGES) - 1)
        company = contact.get("company_name", "") or "ваша компания"
        msg_text = FOLLOWUP_MESSAGES[followup_idx].format(company_name=company)

        result = self.chatwoot_send_message(conv_id, text=msg_text, template=f"followup_{followup_idx}")

        followup_count = (conv.get("followup_count") or 0) + 1
        next_followup = datetime.now() + timedelta(days=2)

        cur2 = self.db.cursor()
        cur2.execute("""
            UPDATE prian_conversations SET followup_count = %s, next_followup = %s,
                stage = 'awaiting_response', status = 'sent', updated_at = NOW() WHERE id = %s
        """, (followup_count, next_followup, conv_id))
        self.db.commit()

        return {"sent": True, "followup_number": followup_count, "next_followup": next_followup.isoformat(), **result}