from __future__ import annotations

import base64
import requests

from config.settings import DIRECTSMS_API_KEY, DIRECTSMS_API_SECRET, DIRECTSMS_SENDER


class DirectSMSService:
    endpoint = 'https://api.directsms.com.au/s3/http/send.php'

    def enabled(self) -> bool:
        return bool(DIRECTSMS_API_KEY and DIRECTSMS_API_SECRET)

    def send(self, to_number: str, message: str) -> str:
        if self.enabled():
            auth = base64.b64encode(f'{DIRECTSMS_API_KEY}:{DIRECTSMS_API_SECRET}'.encode()).decode()
            headers = {'Authorization': f'Basic {auth}'}
            payload = {
                'to': to_number,
                'message': message,
                'from': DIRECTSMS_SENDER,
            }
            response = requests.post(self.endpoint, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            return response.text.strip()
        return f'demo-sms-{to_number[-4:]}'
