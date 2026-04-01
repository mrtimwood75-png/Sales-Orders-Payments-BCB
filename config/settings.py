from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / '.env')

APP_TITLE = os.getenv('APP_TITLE', 'BoConcept Ops App')
DATA_DIR = Path(os.getenv('DATA_DIR', BASE_DIR / 'data')).resolve()
DB_PATH = Path(os.getenv('DB_PATH', DATA_DIR / 'logs.db')).resolve()
SHAREPOINT_INBOX = Path(os.getenv('SHAREPOINT_INBOX', DATA_DIR / 'incoming')).resolve()

DOCUSIGN_BASE_URL = os.getenv('DOCUSIGN_BASE_URL', '')
DOCUSIGN_ACCOUNT_ID = os.getenv('DOCUSIGN_ACCOUNT_ID', '')
DOCUSIGN_INTEGRATION_KEY = os.getenv('DOCUSIGN_INTEGRATION_KEY', '')
DOCUSIGN_USER_ID = os.getenv('DOCUSIGN_USER_ID', '')
DOCUSIGN_PRIVATE_KEY_PATH = os.getenv('DOCUSIGN_PRIVATE_KEY_PATH', '')
DOCUSIGN_TEMPLATE_ID = os.getenv('DOCUSIGN_TEMPLATE_ID', '')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_SUCCESS_URL = os.getenv('STRIPE_SUCCESS_URL', 'https://example.com/success')
STRIPE_CANCEL_URL = os.getenv('STRIPE_CANCEL_URL', 'https://example.com/cancel')

MESSAGEMEDIA_API_KEY = os.getenv('SINCH_MESSAGEMEDIA_API_KEY', os.getenv('MESSAGEMEDIA_API_KEY', os.getenv('DIRECTSMS_API_KEY', '')))
MESSAGEMEDIA_API_SECRET = os.getenv('SINCH_MESSAGEMEDIA_API_SECRET', os.getenv('MESSAGEMEDIA_API_SECRET', os.getenv('DIRECTSMS_API_SECRET', '')))
MESSAGEMEDIA_SENDER = os.getenv('SINCH_MESSAGEMEDIA_SENDER_ID', os.getenv('MESSAGEMEDIA_SENDER', os.getenv('DIRECTSMS_SENDER', '')))
MESSAGEMEDIA_BASE_URL = os.getenv('SINCH_MESSAGEMEDIA_BASE_URL', os.getenv('MESSAGEMEDIA_BASE_URL', 'https://api.messagemedia.com/v1'))
BRAND_LOGO_PATH = Path(os.getenv('BRAND_LOGO_PATH', BASE_DIR / 'assets' / 'logo.png')).resolve()

for path in [DATA_DIR, SHAREPOINT_INBOX, DB_PATH.parent]:
    path.mkdir(parents=True, exist_ok=True)
