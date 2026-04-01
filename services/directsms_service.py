from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth

from config.settings import MESSAGEMEDIA_API_KEY, MESSAGEMEDIA_API_SECRET, MESSAGEMEDIA_BASE_URL, MESSAGEMEDIA_SENDER


class DirectSMSService:
    endpoint = f"{MESSAGEMEDIA_BASE_URL.rstrip('/')}/messages"

    def enabled(self) -> bool:
        return bool(MESSAGEMEDIA_API_KEY and MESSAGEMEDIA_API_SECRET)

    def send(self, to_number: str, message: str) -> str:
        if not self.enabled():
            return f"demo-sms-{to_number[-4:]}"

        msg = {
            'content': message,
            'destination_number': to_number,
            'format': 'SMS',
            'delivery_report': True,
        }
        sender = (MESSAGEMEDIA_SENDER or '').strip()
        if sender:
            msg['source_number'] = sender
            msg['source_number_type'] = 'ALPHANUMERIC' if not sender.lstrip('+').isdigit() else 'INTERNATIONAL'

        payload = {'messages': [msg]}
        response = requests.post(
            self.endpoint,
            json=payload,
            auth=HTTPBasicAuth(MESSAGEMEDIA_API_KEY, MESSAGEMEDIA_API_SECRET),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        messages = body.get('messages') or []
        if not messages:
            return response.text.strip()
        return str(messages[0].get('message_id') or response.text.strip())
