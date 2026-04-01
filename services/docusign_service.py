from __future__ import annotations

from pathlib import Path
from typing import Optional

from config.settings import DOCUSIGN_ACCOUNT_ID, DOCUSIGN_BASE_URL, DOCUSIGN_TEMPLATE_ID


class DocusignService:
    def enabled(self) -> bool:
        return all([DOCUSIGN_BASE_URL, DOCUSIGN_ACCOUNT_ID, DOCUSIGN_TEMPLATE_ID])

    def send_envelope(
        self,
        pdf_path: str | Path,
        signer_name: str,
        signer_email: str,
        sales_order: str,
        payment_link: str = '',
    ) -> str:
        if self.enabled():
            # Implement JWT auth and real createEnvelope call here.
            # Returning placeholder until credentials are configured.
            return f'live-envelope-{sales_order}'
        return f'demo-envelope-{sales_order}'
