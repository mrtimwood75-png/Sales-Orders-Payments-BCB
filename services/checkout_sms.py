from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Callable

import requests
from requests.auth import HTTPBasicAuth


def normalize_mobile_au(mobile: str) -> str:
    mobile = str(mobile).strip()
    allowed = []
    for ch in mobile:
        if ch.isdigit() or ch == "+":
            allowed.append(ch)
    mobile = "".join(allowed)

    if not mobile:
        return ""
    if mobile.startswith("+61"):
        return mobile
    if mobile.startswith("61"):
        return "+" + mobile
    if mobile.startswith("04") and len(mobile) >= 10:
        return "+61" + mobile[1:]
    return mobile


def default_sms_templates() -> dict[str, str]:
    return {
        "Standard payment request": (
            "Hi {customer_name}, payment for order {order_number} is now due. "
            "Amount payable: {payment_amount}. Please pay securely here: {stripe_checkout_url}"
        ),
        "Friendly reminder": (
            "Hi {customer_name}, just a reminder that payment for order {order_number} "
            "of {payment_amount} is outstanding. Payment link: {stripe_checkout_url}"
        ),
        "Short version": (
            "Hi {customer_name}, please pay {payment_amount} for order {order_number}: {stripe_checkout_url}"
        ),
    }


def _coerce_templates(raw_data) -> dict[str, str]:
    if not isinstance(raw_data, dict):
        return {}

    templates: dict[str, str] = {}
    for name, value in raw_data.items():
        key = str(name).strip()
        if not key:
            continue

        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, dict):
            text = str(value.get("text", "")).strip()
        else:
            text = str(value).strip()

        if text:
            templates[key] = text

    return templates


def load_shared_sms_templates(project_root: Path | str, filename: str = "bundle-sms-templates.json") -> dict[str, str]:
    path = Path(project_root) / filename
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                templates = _coerce_templates(json.load(f))
            if templates:
                return templates
        except Exception:
            pass

    templates = default_sms_templates()
    save_shared_sms_templates(project_root, templates, filename=filename)
    return templates


def save_shared_sms_templates(
    project_root: Path | str,
    templates: dict[str, str],
    filename: str = "bundle-sms-templates.json",
) -> None:
    path = Path(project_root) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _coerce_templates(templates)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def build_sms_message(payload: dict, template_text: str, format_money_fn: Callable[[float], str]) -> str:
    return template_text.format(
        customer_name=str(payload.get("customer_name", "")).strip(),
        order_number=str(payload.get("order_number", "")).strip(),
        payment_amount=format_money_fn(payload.get("payment_amount", 0)),
        stripe_checkout_url=str(payload.get("stripe_checkout_url", "")).strip(),
        mobile=str(payload.get("mobile", "")).strip(),
    )


def _get_secret(secrets, name: str, default: str = "") -> str:
    try:
        return str(secrets[name])
    except Exception:
        return str(default)


def get_messagemedia_config(secrets) -> tuple[str, str, str, str]:
    api_key = (
        _get_secret(secrets, "SINCH_MESSAGEMEDIA_API_KEY")
        or _get_secret(secrets, "MESSAGEMEDIA_API_KEY")
        or _get_secret(secrets, "DIRECTSMS_API_KEY")
        or os.getenv("SINCH_MESSAGEMEDIA_API_KEY", "")
        or os.getenv("MESSAGEMEDIA_API_KEY", "")
        or os.getenv("DIRECTSMS_API_KEY", "")
    ).strip()
    api_secret = (
        _get_secret(secrets, "SINCH_MESSAGEMEDIA_API_SECRET")
        or _get_secret(secrets, "MESSAGEMEDIA_API_SECRET")
        or _get_secret(secrets, "DIRECTSMS_API_SECRET")
        or os.getenv("SINCH_MESSAGEMEDIA_API_SECRET", "")
        or os.getenv("MESSAGEMEDIA_API_SECRET", "")
        or os.getenv("DIRECTSMS_API_SECRET", "")
    ).strip()
    sender = (
        _get_secret(secrets, "SINCH_MESSAGEMEDIA_SENDER_ID")
        or _get_secret(secrets, "MESSAGEMEDIA_SENDER")
        or _get_secret(secrets, "DIRECTSMS_SENDER")
        or _get_secret(secrets, "DIRECTSMS_SENDERID")
        or os.getenv("SINCH_MESSAGEMEDIA_SENDER_ID", "")
        or os.getenv("MESSAGEMEDIA_SENDER", "")
        or os.getenv("DIRECTSMS_SENDER", "")
        or os.getenv("DIRECTSMS_SENDERID", "")
    ).strip()
    base_url = (
        _get_secret(secrets, "SINCH_MESSAGEMEDIA_BASE_URL")
        or _get_secret(secrets, "MESSAGEMEDIA_BASE_URL")
        or os.getenv("SINCH_MESSAGEMEDIA_BASE_URL", "")
        or os.getenv("MESSAGEMEDIA_BASE_URL", "https://api.messagemedia.com/v1")
    ).strip()

    if not api_key or not api_secret:
        raise ValueError("Missing Sinch MessageMedia API key or secret in Streamlit secrets.")

    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        url = f"{base_url}/messages"
    elif base_url.endswith("/messages"):
        url = base_url
    else:
        url = f"{base_url}/v1/messages"

    return api_key, api_secret, sender, url


def messagemedia_send_message(to_mobile: str, message: str, secrets, debug_callback: Callable[[str, object], None] | None = None) -> str:
    api_key, api_secret, sender, url = get_messagemedia_config(secrets)

    sms = {
        "content": message,
        "destination_number": normalize_mobile_au(to_mobile),
        "format": "SMS",
        "delivery_report": True,
    }
    if sender:
        sms["source_number"] = sender
        sms["source_number_type"] = "ALPHANUMERIC" if not sender.lstrip("+").isdigit() else "INTERNATIONAL"

    payload = {"messages": [sms]}
    response = requests.post(
        url,
        json=payload,
        auth=HTTPBasicAuth(api_key, api_secret),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )

    if debug_callback:
        debug_callback("Sinch MessageMedia URL", url)
        debug_callback("HTTP status", response.status_code)
        debug_callback("Response body", response.text)
        debug_callback("Payload", payload)

    response.raise_for_status()
    body = response.json()
    messages = body.get("messages") or []
    if not messages:
        return response.text.strip()
    return str(messages[0].get("message_id") or response.text.strip())


def create_stripe_checkout_link(
    stripe_module,
    stripe_secret_key: str,
    stripe_success_url: str,
    stripe_cancel_url: str,
    stripe_currency: str,
    customer_name: str,
    customer_email: str,
    sales_order: str,
    amount: float,
    payment_label: str,
    phone: str,
) -> dict[str, str]:
    if stripe_module is None:
        raise RuntimeError("Stripe package not installed")
    if not stripe_secret_key:
        raise RuntimeError("Missing STRIPE_SECRET_KEY in Streamlit secrets")
    if not stripe_success_url:
        raise RuntimeError("Missing STRIPE_SUCCESS_URL in Streamlit secrets")
    if not stripe_cancel_url:
        raise RuntimeError("Missing STRIPE_CANCEL_URL in Streamlit secrets")

    amount_value = float(amount or 0)
    if amount_value <= 0:
        raise RuntimeError("Payment amount must be greater than 0")

    stripe_module.api_key = stripe_secret_key
    unit_amount = int(round(amount_value * 100))
    order_ref = sales_order or "Order"

    session = stripe_module.checkout.Session.create(
        mode="payment",
        success_url=stripe_success_url,
        cancel_url=stripe_cancel_url,
        customer_email=customer_email or None,
        client_reference_id=order_ref,
        payment_method_types=["card"],
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": stripe_currency,
                    "unit_amount": unit_amount,
                    "product_data": {
                        "name": payment_label,
                        "description": f"BoConcept order {order_ref}",
                    },
                },
            }
        ],
        metadata={
            "sales_order": order_ref,
            "customer_name": customer_name or "",
            "customer_email": customer_email or "",
            "payment_label": payment_label,
            "payment_amount": f"{amount_value:.2f}",
            "mobile": normalize_mobile_au(phone),
        },
    )
    return {"url": session.url, "session_id": session.id}
