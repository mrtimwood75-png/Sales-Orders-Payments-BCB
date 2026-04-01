from __future__ import annotations

import re
from typing import Any

import requests

from config.settings import (
    SINCH_MESSAGEMEDIA_API_KEY,
    SINCH_MESSAGEMEDIA_API_SECRET,
    SINCH_MESSAGEMEDIA_BASE_URL,
    SINCH_MESSAGEMEDIA_SENDER_ID,
)


class DirectSMSService:
    endpoint = f"{SINCH_MESSAGEMEDIA_BASE_URL.rstrip('/')}/v1/messages"

    def enabled(self) -> bool:
        return bool(SINCH_MESSAGEMEDIA_API_KEY and SINCH_MESSAGEMEDIA_API_SECRET)

    @staticmethod
    def normalize_mobile_au(number: str) -> str:
        raw = ''.join(ch for ch in str(number).strip() if ch.isdigit() or ch == '+')
        if not raw:
            return ''
        if raw.startswith('+61'):
            return raw
        if raw.startswith('61'):
            return f'+{raw}'
        if raw.startswith('04') and len(raw) >= 10:
            return f'+61{raw[1:]}'
        return raw

    @staticmethod
    def sender_payload(sender_id: str) -> dict[str, str]:
        sender = str(sender_id or '').strip()
        if not sender:
            return {}
        if sender.startswith('+') or sender.isdigit():
            return {
                'source_number': sender,
                'source_number_type': 'INTERNATIONAL',
            }
        cleaned = re.sub(r'[^A-Za-z0-9]', '', sender)
        if cleaned:
            return {
                'source_number': cleaned[:11],
                'source_number_type': 'ALPHANUMERIC',
            }
        return {}

    @staticmethod
    def _extract_message_id(payload: dict[str, Any]) -> str:
        messages = payload.get('messages') or []
        if messages and isinstance(messages[0], dict):
            return str(messages[0].get('message_id') or messages[0].get('messageId') or '').strip()
        return ''

    def send(self, to_number: str, message: str) -> str:
        if not self.enabled():
            return f'demo-sms-{str(to_number)[-4:]}'

        destination = self.normalize_mobile_au(to_number)
        if not destination:
            raise ValueError('Missing destination mobile number.')

        body = {
            'messages': [
                {
                    'content': str(message),
                    'destination_number': destination,
                    'format': 'SMS',
                    **self.sender_payload(SINCH_MESSAGEMEDIA_SENDER_ID),
                }
            ]
        }

        response = requests.post(
            self.endpoint,
            auth=(SINCH_MESSAGEMEDIA_API_KEY, SINCH_MESSAGEMEDIA_API_SECRET),
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': 'BoConcept-Ops-App/1.0',
            },
            json=body,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        message_id = self._extract_message_id(payload)
        if not message_id:
            raise ValueError(f'Unexpected Sinch MessageMedia response: {payload}')
        return message_id
