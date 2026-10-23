"""Gmail: read, search, draft — sending is gated behind user confirmation."""
import base64
from email.mime.text import MIMEText

from . import ConfirmationRequired

_MAX_BODY_CHARS = 6000


def _service():
    from googleapiclient.discovery import build

    from ..google_auth import get_credentials

    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def _header(message, name):
    for h in message.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def search(query, max_results=10):
    svc = _service()
    resp = svc.users().messages().list(
        userId="me", q=query, maxResults=int(max_results)
    ).execute()
    ids = [m["id"] for m in resp.get("messages", [])]
    if not ids:
        return "No emails match {!r}.".format(query)
    lines = []
    for mid in ids:
        msg = svc.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        lines.append(
            "id: {}\nfrom: {}\nsubject: {}\ndate: {}\nsnippet: {}".format(
                mid,
                _header(msg, "From"),
                _header(msg, "Subject"),
                _header(msg, "Date"),
                msg.get("snippet", ""),
            )
        )
    return "\n\n".join(lines)


def _extract_text(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )
    for part in payload.get("parts", []) or []:
        text = _extract_text(part)
        if text:
            return text
    return ""


def read(message_id):
    svc = _service()
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    body = _extract_text(msg.get("payload", {})) or msg.get("snippet", "")
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n[truncated]"
    return "from: {}\nsubject: {}\ndate: {}\n\n{}".format(
        _header(msg, "From"), _header(msg, "Subject"), _header(msg, "Date"), body
    )


def create_draft(to, subject, body):
    svc = _service()
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    draft = svc.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return "Draft created (id {}) to {} — subject: {}. Not sent.".format(
        draft["id"], to, subject
    )


def send_draft(draft_id, _confirmed=False):
    svc = _service()
    draft = svc.users().drafts().get(userId="me", id=draft_id, format="metadata").execute()
    msg = draft.get("message", {})
    to = _header(msg, "To")
    subject = _header(msg, "Subject")
    if not _confirmed:
        raise ConfirmationRequired(
            "Send the email to {} with subject '{}'?".format(to or "unknown", subject)
        )
    svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    return "Email sent to {} — subject: {}.".format(to, subject)
