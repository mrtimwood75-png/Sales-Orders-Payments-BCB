import json
import os
import re
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
import streamlit as st

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import stripe
except Exception:
    stripe = None


APP_TITLE = "Add Logo & Bundle Attachments"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_FILES_DIR = PROJECT_ROOT / "assets" / "default-files"
TEMPLATE_FILE = PROJECT_ROOT / "bundle-sms-templates.json"

STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", "")).strip()
STRIPE_SUCCESS_URL = st.secrets.get("STRIPE_SUCCESS_URL", os.getenv("STRIPE_SUCCESS_URL", "")).strip()
STRIPE_CANCEL_URL = st.secrets.get("STRIPE_CANCEL_URL", os.getenv("STRIPE_CANCEL_URL", "")).strip()
STRIPE_CURRENCY = st.secrets.get("STRIPE_CURRENCY", os.getenv("STRIPE_CURRENCY", "aud")).strip().lower()


def resolve_logo_path():
    candidates = [
        PROJECT_ROOT / "assets" / "boconcept_logo.png",
        PROJECT_ROOT / "assets" / "boconcept_logo.PNG",
        PROJECT_ROOT / "assets" / "BoConcept_logo.png",
        PROJECT_ROOT / "assets" / "BoConcept_logo.PNG",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


LOGO_PATH = resolve_logo_path()


def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def safe_filename(value, fallback="customer"):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def parse_numeric_input(text, fallback=0.0):
    raw = str(text).strip()
    if not raw:
        return float(fallback)

    raw = raw.replace("$", "").replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")

    try:
        return float(raw)
    except Exception:
        return float(fallback)


def format_money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return str(value or "")


def normalize_mobile_au(mobile):
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


def get_default_attachments():
    attachments = []
    if not DEFAULT_FILES_DIR.exists() or not DEFAULT_FILES_DIR.is_dir():
        return attachments

    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    for path in sorted(DEFAULT_FILES_DIR.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in allowed_exts:
            attachments.append(
                {
                    "name": path.name,
                    "bytes": path.read_bytes(),
                    "locked": True,
                    "source": "default",
                }
            )
    return attachments


def initialise_default_attachments():
    st.session_state["bundle_only_attachments"] = get_default_attachments()


def default_templates():
    return {
        "Standard payment request": {
            "text": (
                "Hi {customer_name}, payment for order {order_number} is now due. "
                "Amount payable: {payment_amount}. Please pay securely here: {stripe_checkout_url}"
            )
        },
        "Friendly reminder": {
            "text": (
                "Hi {customer_name}, just a reminder that payment for order {order_number} "
                "of {payment_amount} is outstanding. Payment link: {stripe_checkout_url}"
            )
        },
        "Short version": {
            "text": "Hi {customer_name}, please pay {payment_amount} for order {order_number}: {stripe_checkout_url}"
        },
    }


def load_templates_from_file():
    if TEMPLATE_FILE.exists():
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    data = default_templates()
    save_templates_to_file(data)
    return data


def save_templates_to_file(data=None):
    TEMPLATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = data if data is not None else st.session_state.get("bundle_only_templates", default_templates())
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def reset_session():
    keys = [
        "bundle_only_order_pdf_name",
        "bundle_only_order_pdf_bytes",
        "bundle_only_attachments",
        "bundle_only_doc_type",
        "bundle_only_customer_name",
        "bundle_only_order_number",
        "bundle_only_order_total",
        "bundle_only_order_balance",
        "bundle_only_customer_address",
        "bundle_only_email",
        "bundle_only_phone",
        "bundle_only_payment_request",
        "bundle_only_sms_text",
        "bundle_only_sms_status",
        "bundle_only_sms_confirm_open",
        "bundle_only_sms_confirm_name",
        "bundle_only_sms_confirm_phone",
        "bundle_only_payment_link",
        "bundle_only_stripe_session_id",
        "bundle_only_template_name",
        "bundle_only_template_text",
        "bundle_only_new_template_name",
        "bundle_only_embed_link_in_pdf",
    ]
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]


def init_state():
    defaults = {
        "bundle_only_doc_type": "Confirmation",
        "bundle_only_customer_name": "",
        "bundle_only_order_number": "",
        "bundle_only_order_total": "",
        "bundle_only_order_balance": "",
        "bundle_only_customer_address": "",
        "bundle_only_email": "",
        "bundle_only_phone": "",
        "bundle_only_payment_request": "",
        "bundle_only_sms_text": "",
        "bundle_only_sms_status": "",
        "bundle_only_sms_confirm_open": False,
        "bundle_only_sms_confirm_name": "",
        "bundle_only_sms_confirm_phone": "",
        "bundle_only_payment_link": "",
        "bundle_only_stripe_session_id": "",
        "bundle_only_new_template_name": "",
        "bundle_only_embed_link_in_pdf": False,
        "bundle_only_attachment_notice": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "bundle_only_templates" not in st.session_state:
        st.session_state["bundle_only_templates"] = load_templates_from_file()

    if "bundle_only_template_name" not in st.session_state:
        st.session_state["bundle_only_template_name"] = list(st.session_state["bundle_only_templates"].keys())[0]

    if "bundle_only_template_text" not in st.session_state:
        selected = st.session_state["bundle_only_templates"][st.session_state["bundle_only_template_name"]]
        st.session_state["bundle_only_template_text"] = selected.get("text", "")


def get_page_text_left_margin(page):
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return 24

    candidates = []
    for block in blocks:
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[:5]
        text_clean = clean_text(text)
        if not text_clean:
            continue
        if y0 < 10:
            continue
        candidates.append(float(x0))

    if not candidates:
        return 24

    left = min(candidates)
    return max(18, min(left, 80))


def extract_text_from_page(doc, page_index):
    if page_index < 0 or page_index >= doc.page_count:
        return ""
    try:
        return doc[page_index].get_text("text")
    except Exception:
        return ""


def parse_amount_from_text(value):
    text = clean_text(value)
    if not text:
        return ""
    m = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})|[0-9]+[.,][0-9]{2})", text)
    return m.group(1) if m else text


def extract_sales_order_fields(pdf_bytes):
    fields = {
        "customer_name": "",
        "order_number": "",
        "order_total": "",
        "order_balance": "",
        "customer_address": "",
        "email": "",
        "phone": "",
        "payment_request": "",
    }

    if fitz is None:
        return fields

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return fields

    try:
        first_page_text = extract_text_from_page(doc, 0)
        last_page_text = extract_text_from_page(doc, doc.page_count - 1) if doc.page_count else ""
        second_last_text = extract_text_from_page(doc, doc.page_count - 2) if doc.page_count > 1 else ""
        all_text = "\n".join([first_page_text, second_last_text, last_page_text])

        lines = [clean_text(x) for x in first_page_text.splitlines() if clean_text(x)]

        for line in lines[:12]:
            if not re.search(
                r"sales order|date|phone|email|misc\. charges|gst|total|prepayment|balance due|confirmation|tax invoice|customer number|page",
                line,
                re.IGNORECASE,
            ):
                fields["customer_name"] = line
                break

        email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", all_text, re.IGNORECASE)
        if email_match:
            fields["email"] = email_match.group(0)

        phone_match = re.search(r"(?:mobile phone|phone)\s+([0-9][0-9 ]{7,})", all_text, re.IGNORECASE)
        if phone_match:
            fields["phone"] = clean_text(phone_match.group(1))

        if not fields["phone"]:
            phone_match = re.search(r"\b(0\d{8,10})\b", all_text)
            if phone_match:
                fields["phone"] = phone_match.group(1)

        order_patterns = [
            r"sales order\s*([A-Za-z0-9\-]+)",
            r"\b(os[- ]?\d+)\b",
        ]
        for pattern in order_patterns:
            m = re.search(pattern, all_text, re.IGNORECASE)
            if m:
                fields["order_number"] = clean_text(m.group(1) if m.lastindex else m.group(0))
                break

        address_lines = []
        capture = False
        for line in lines:
            lower = line.lower()
            if "delivery address" in lower:
                capture = True
                continue
            if capture:
                if re.search(
                    r"payment|terms of delivery|estimated date|our ref|customer requisition|currency|article|qty|description",
                    line,
                    re.IGNORECASE,
                ):
                    break
                address_lines.append(line)

        if address_lines:
            if fields["customer_name"] and clean_text(address_lines[0]).lower() == clean_text(fields["customer_name"]).lower():
                address_lines = address_lines[1:]
            fields["customer_address"] = "\n".join(address_lines).strip()

        balance_source = "\n".join([second_last_text, last_page_text])

        total_patterns = [
            r"order total\s*(?:aud)?\s*([0-9\.,]+)",
            r"total\s*(?:aud)?\s*([0-9\.,]+)",
        ]
        for pattern in total_patterns:
            m = re.search(pattern, balance_source, re.IGNORECASE)
            if m:
                fields["order_total"] = parse_amount_from_text(m.group(1))
                break

        balance_patterns = [
            r"balance due\s*(?:aud)?\s*([0-9\.,]+)",
            r"balance\s*(?:aud)?\s*([0-9\.,]+)",
        ]
        for pattern in balance_patterns:
            m = re.search(pattern, balance_source, re.IGNORECASE)
            if m:
                fields["order_balance"] = parse_amount_from_text(m.group(1))
                break

        fields["payment_request"] = fields["order_balance"]

    finally:
        doc.close()

    return fields


def seed_fields_from_pdf(fields):
    st.session_state["bundle_only_customer_name"] = fields.get("customer_name", "")
    st.session_state["bundle_only_order_number"] = fields.get("order_number", "")
    st.session_state["bundle_only_order_total"] = fields.get("order_total", "")
    st.session_state["bundle_only_order_balance"] = fields.get("order_balance", "")
    st.session_state["bundle_only_customer_address"] = fields.get("customer_address", "")
    st.session_state["bundle_only_email"] = fields.get("email", "")
    st.session_state["bundle_only_phone"] = fields.get("phone", "")
    st.session_state["bundle_only_payment_request"] = fields.get("payment_request", "") or fields.get("order_balance", "")

    st.session_state["bundle_only_sms_text"] = build_sms_message(
        {
            "customer_name": st.session_state["bundle_only_customer_name"],
            "order_number": st.session_state["bundle_only_order_number"],
            "payment_amount": parse_numeric_input(st.session_state["bundle_only_payment_request"], 0),
            "stripe_checkout_url": st.session_state.get("bundle_only_payment_link", ""),
            "mobile": normalize_mobile_au(st.session_state["bundle_only_phone"]),
        },
        st.session_state["bundle_only_template_text"],
    )


def add_extra_files_to_bundle(extra_files):
    if not extra_files:
        return 0

    if "bundle_only_attachments" not in st.session_state:
        initialise_default_attachments()

    existing_keys = {
        (att["name"], len(att["bytes"]), att.get("source", "user"))
        for att in st.session_state["bundle_only_attachments"]
    }

    added_count = 0
    for up in extra_files:
        up_bytes = up.getvalue()
        item_key = (up.name, len(up_bytes), "user")
        if item_key in existing_keys:
            continue

        st.session_state["bundle_only_attachments"].append(
            {
                "name": up.name,
                "bytes": up_bytes,
                "locked": False,
                "source": "user",
            }
        )
        existing_keys.add(item_key)
        added_count += 1

    return added_count


def find_confirmation_span(page):
    try:
        text_dict = page.get_text("dict")
    except Exception:
        return None

    candidates = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = clean_text(span.get("text", ""))
                if text.lower() == "confirmation":
                    bbox = span.get("bbox")
                    if not bbox:
                        continue
                    x0, y0, x1, y1 = bbox
                    candidates.append(
                        {
                            "rect": fitz.Rect(x0, y0, x1, y1),
                            "size": float(span.get("size", 18)),
                            "font": str(span.get("font", "")),
                        }
                    )

    if not candidates:
        return None

    candidates.sort(key=lambda s: (s["rect"].y0, -(s["rect"].width)))
    return candidates[0]


def choose_pymupdf_font(font_name):
    name = (font_name or "").lower()
    if "bold" in name:
        return "helvB"
    return "helv"


def overlay_tax_invoice_title(doc):
    if fitz is None or doc.page_count == 0:
        return

    page = doc[0]
    span = find_confirmation_span(page)

    if span:
        rect = span["rect"]
        fontname = choose_pymupdf_font(span.get("font"))
        fontsize = max(10, min(float(span.get("size", 18)), 24))

        expanded_width = max(rect.width + 90, 155)
        wipe_rect = fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x0 + expanded_width, rect.y1 + 2)

        page.draw_rect(wipe_rect, color=None, fill=(1, 1, 1), overlay=True)
        page.insert_text(
            fitz.Point(rect.x0, rect.y1 - 1),
            "Tax Invoice",
            fontsize=fontsize,
            fontname=fontname,
            color=(0, 0, 0),
            overlay=True,
        )
        return

    fallback_rect = fitz.Rect(300, 118, 470, 140)
    page.draw_rect(fallback_rect, color=None, fill=(1, 1, 1), overlay=True)
    page.insert_text(
        fitz.Point(fallback_rect.x0, fallback_rect.y1 - 1),
        "Tax Invoice",
        fontsize=18,
        fontname="helvB",
        color=(0, 0, 0),
        overlay=True,
    )


def add_payment_button_to_pdf(doc, payment_url):
    if fitz is None or not payment_url or doc.page_count == 0:
        return

    target_pages = [doc.page_count - 1]
    if doc.page_count > 1:
        target_pages.insert(0, doc.page_count - 2)

    label_priority = ["Balance due", "balance due", "Total", "total", "Amount", "amount"]
    placed = False

    for page_index in target_pages:
        page = doc[page_index]
        found = None

        for label in label_priority:
            try:
                rects = page.search_for(label)
            except Exception:
                rects = []
            if rects:
                found = rects[-1]
                break

        if found is None:
            continue

        button_w = 115
        button_h = 20

        x = min(found.x1 + 14, page.rect.width - button_w - 18)
        y = max(found.y0 - 2, 18)

        if x < found.x1 + 4:
            x = max(found.x0, 18)
            y = min(found.y1 + 8, page.rect.height - button_h - 18)

        button_rect = fitz.Rect(x, y, x + button_w, y + button_h)

        page.draw_rect(button_rect, color=(0, 0, 0), fill=(0, 0, 0), overlay=True)
        page.insert_textbox(
            button_rect,
            "Pay Now",
            fontname="helvB",
            fontsize=9,
            color=(1, 1, 1),
            align=1,
            overlay=True,
        )
        page.insert_link({"kind": fitz.LINK_URI, "from": button_rect, "uri": payment_url})
        placed = True
        break

    if not placed:
        page = doc[doc.page_count - 1]
        button_rect = fitz.Rect(page.rect.width - 133, page.rect.height - 44, page.rect.width - 18, page.rect.height - 24)
        page.draw_rect(button_rect, color=(0, 0, 0), fill=(0, 0, 0), overlay=True)
        page.insert_textbox(
            button_rect,
            "Pay Now",
            fontname="helvB",
            fontsize=9,
            color=(1, 1, 1),
            align=1,
            overlay=True,
        )
        page.insert_link({"kind": fitz.LINK_URI, "from": button_rect, "uri": payment_url})


def stamp_main_pdf_bytes(pdf_bytes, logo_path, doc_type, payment_url="", embed_payment_link=False):
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page in doc:
        if logo_path and Path(logo_path).exists():
            left_x = get_page_text_left_margin(page)
            logo_rect = fitz.Rect(left_x, 18, left_x + 126, 60)
            page.insert_image(
                logo_rect,
                filename=str(logo_path),
                keep_proportion=True,
                overlay=True,
            )

    if doc_type == "Tax Invoice":
        overlay_tax_invoice_title(doc)

    if embed_payment_link and payment_url:
        add_payment_button_to_pdf(doc, payment_url)

    output = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return output


def append_image_bytes_as_pdf_pages(bundle_doc, image_bytes):
    img_doc = fitz.open(stream=image_bytes)
    pdf_bytes = img_doc.convert_to_pdf()
    img_doc.close()

    img_pdf = fitz.open("pdf", pdf_bytes)
    bundle_doc.insert_pdf(img_pdf)
    img_pdf.close()


def append_file_bytes_to_pdf(bundle_doc, file_name, file_bytes):
    ext = Path(file_name).suffix.lower()

    if ext == ".pdf":
        src = fitz.open(stream=file_bytes, filetype="pdf")
        bundle_doc.insert_pdf(src)
        src.close()
        return

    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        append_image_bytes_as_pdf_pages(bundle_doc, file_bytes)
        return

    raise RuntimeError(f"Unsupported attachment type: {file_name}")


def build_single_bundle_pdf_bytes(main_pdf_bytes, attachments, logo_path, doc_type, payment_url="", embed_payment_link=False):
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed")

    stamped_main_bytes = stamp_main_pdf_bytes(
        main_pdf_bytes,
        logo_path,
        doc_type,
        payment_url=payment_url,
        embed_payment_link=embed_payment_link,
    )

    final_doc = fitz.open()

    main_doc = fitz.open(stream=stamped_main_bytes, filetype="pdf")
    final_doc.insert_pdf(main_doc)
    main_doc.close()

    for att in attachments:
        append_file_bytes_to_pdf(final_doc, att["name"], att["bytes"])

    output = final_doc.tobytes(garbage=4, deflate=True)
    final_doc.close()
    return output


def ensure_stripe_ready():
    if stripe is None:
        raise RuntimeError("Stripe package not installed")
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Missing STRIPE_SECRET_KEY in Streamlit secrets")
    if not STRIPE_SUCCESS_URL:
        raise RuntimeError("Missing STRIPE_SUCCESS_URL in Streamlit secrets")
    if not STRIPE_CANCEL_URL:
        raise RuntimeError("Missing STRIPE_CANCEL_URL in Streamlit secrets")
    stripe.api_key = STRIPE_SECRET_KEY


def create_stripe_checkout_link(customer_name, customer_email, sales_order, amount, payment_label, phone):
    amount_value = float(amount or 0)
    if amount_value <= 0:
        raise RuntimeError("Payment amount must be greater than 0")

    ensure_stripe_ready()

    unit_amount = int(round(amount_value * 100))
    order_ref = sales_order or "Order"

    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=STRIPE_SUCCESS_URL,
        cancel_url=STRIPE_CANCEL_URL,
        customer_email=customer_email or None,
        client_reference_id=order_ref,
        payment_method_types=["card"],
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": STRIPE_CURRENCY,
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


def get_messagemedia_config():
    api_key = str(
        get_secret("SINCH_MESSAGEMEDIA_API_KEY", "")
        or get_secret("MESSAGEMEDIA_API_KEY", "")
        or get_secret("DIRECTSMS_API_KEY", "")
        or os.getenv("SINCH_MESSAGEMEDIA_API_KEY", "")
        or os.getenv("MESSAGEMEDIA_API_KEY", "")
        or os.getenv("DIRECTSMS_API_KEY", "")
    ).strip()
    api_secret = str(
        get_secret("SINCH_MESSAGEMEDIA_API_SECRET", "")
        or get_secret("MESSAGEMEDIA_API_SECRET", "")
        or get_secret("DIRECTSMS_API_SECRET", "")
        or os.getenv("SINCH_MESSAGEMEDIA_API_SECRET", "")
        or os.getenv("MESSAGEMEDIA_API_SECRET", "")
        or os.getenv("DIRECTSMS_API_SECRET", "")
    ).strip()
    sender = str(
        get_secret("SINCH_MESSAGEMEDIA_SENDER_ID", "")
        or get_secret("MESSAGEMEDIA_SENDER", "")
        or get_secret("DIRECTSMS_SENDER", "")
        or get_secret("DIRECTSMS_SENDERID", "")
        or os.getenv("SINCH_MESSAGEMEDIA_SENDER_ID", "")
        or os.getenv("MESSAGEMEDIA_SENDER", "")
        or os.getenv("DIRECTSMS_SENDER", "")
        or os.getenv("DIRECTSMS_SENDERID", "")
    ).strip()
    base_url = str(
        get_secret("SINCH_MESSAGEMEDIA_BASE_URL", "")
        or get_secret("MESSAGEMEDIA_BASE_URL", "")
        or os.getenv("SINCH_MESSAGEMEDIA_BASE_URL", "")
        or os.getenv("MESSAGEMEDIA_BASE_URL", "https://api.messagemedia.com/v1")
    ).strip()

    if not api_key or not api_secret:
        raise ValueError("Missing Sinch MessageMedia API key or secret in Streamlit secrets.")

    base_url = base_url.strip().rstrip("/")
    if base_url.endswith("/v1"):
        url = f"{base_url}/messages"
    elif base_url.endswith("/messages"):
        url = base_url
    else:
        url = f"{base_url}/v1/messages"

    return api_key, api_secret, sender, url


def messagemedia_send_message(to_mobile, message):
    api_key, api_secret, sender, url = get_messagemedia_config()

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
    resp = requests.post(
        url,
        json=payload,
        auth=HTTPBasicAuth(api_key, api_secret),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )

    resp.raise_for_status()
    body = resp.json()
    messages = body.get("messages") or []
    if not messages:
        return resp.text.strip()
    return str(messages[0].get("message_id") or resp.text.strip())


def build_sms_message(payload, template_text):
    return template_text.format(
        customer_name=str(payload.get("customer_name", "")).strip(),
        order_number=str(payload.get("order_number", "")).strip(),
        payment_amount=format_money(payload.get("payment_amount", 0)),
        stripe_checkout_url=str(payload.get("stripe_checkout_url", "")).strip(),
        mobile=str(payload.get("mobile", "")).strip(),
    )


def render_download_button(button_label, bundle_bytes, bundle_name, file_count, doc_type, location_tag):
    st.download_button(
        button_label,
        data=bundle_bytes,
        file_name=bundle_name,
        mime="application/pdf",
        use_container_width=True,
        key=f"bundle_only_download_{location_tag}_{bundle_name}_{len(bundle_bytes)}_{doc_type}_{st.session_state.get('bundle_only_embed_link_in_pdf', False)}",
    )


init_state()
st.set_page_config(page_title=APP_TITLE, layout="wide")

top_nav_left, top_nav_right = st.columns([1, 5])
with top_nav_left:
    if st.button("Home", use_container_width=True):
        st.switch_page("main.py")
with top_nav_right:
    if LOGO_PATH:
        st.image(str(LOGO_PATH), width=220)

st.title(APP_TITLE)

top_a, top_b = st.columns([3, 1])
default_attachments = get_default_attachments()

if default_attachments:
    top_a.caption(f"Locked default bundle files: {len(default_attachments)}")
else:
    top_a.warning("No files found in assets/default-files")

if top_b.button("Reset Session", use_container_width=True):
    reset_session()
    st.rerun()

uploaded_pdf = st.file_uploader("Upload sales order PDF", type=["pdf"], key="bundle_only_orders_pdf")

if uploaded_pdf is not None:
    pdf_bytes = uploaded_pdf.getvalue()

    if (
        st.session_state.get("bundle_only_order_pdf_name") != uploaded_pdf.name
        or st.session_state.get("bundle_only_order_pdf_bytes") != pdf_bytes
    ):
        st.session_state["bundle_only_order_pdf_name"] = uploaded_pdf.name
        st.session_state["bundle_only_order_pdf_bytes"] = pdf_bytes

        extracted = extract_sales_order_fields(pdf_bytes)
        seed_fields_from_pdf(extracted)

        st.session_state["bundle_only_payment_link"] = ""
        st.session_state["bundle_only_stripe_session_id"] = ""
        st.session_state["bundle_only_sms_status"] = ""
        st.session_state["bundle_only_embed_link_in_pdf"] = False
        st.session_state["bundle_only_attachment_notice"] = ""

        initialise_default_attachments()

if st.session_state.get("bundle_only_order_pdf_bytes"):
    top_left, top_right = st.columns([2.2, 1.2])

    with top_left:
        st.text_input("Customer", key="bundle_only_customer_name")

    with top_right:
        st.radio(
            "Document type",
            ["Confirmation", "Tax Invoice"],
            horizontal=True,
            key="bundle_only_doc_type",
        )

    extra_files = st.file_uploader(
        "Upload extra PDF or image files",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="bundle_only_attachments_uploader",
    )

    if extra_files:
        added_count = add_extra_files_to_bundle(extra_files)
        if added_count:
            st.session_state["bundle_only_attachment_notice"] = f"{added_count} file(s) added automatically"
        else:
            st.session_state["bundle_only_attachment_notice"] = "Files already in bundle"

    if st.session_state.get("bundle_only_attachment_notice"):
        st.caption(st.session_state["bundle_only_attachment_notice"])

    attachments = st.session_state.get("bundle_only_attachments", [])
    file_count = len(attachments) + 1
    doc_type = st.session_state.get("bundle_only_doc_type", "Confirmation")

    st.markdown("### Captured order fields")
    f1, f2 = st.columns(2)

    with f1:
        st.text_input("Order number", key="bundle_only_order_number")
        st.text_input("Order total", key="bundle_only_order_total")
        st.text_input("Email", key="bundle_only_email")

    with f2:
        st.text_input("Order balance", key="bundle_only_order_balance")
        st.text_input("Phone", key="bundle_only_phone")
        st.text_input("Payment Request", key="bundle_only_payment_request")

    st.text_area("Customer address", key="bundle_only_customer_address", height=110)

    st.markdown("### Stripe payment link")
    p1, p2 = st.columns([1, 1.4])

    with p1:
        if st.button("Create Link", use_container_width=True):
            try:
                payment_amount = parse_numeric_input(st.session_state.get("bundle_only_payment_request", ""), 0)
                if payment_amount <= 0:
                    raise RuntimeError("Payment Request must be greater than 0")

                link_result = create_stripe_checkout_link(
                    customer_name=st.session_state.get("bundle_only_customer_name", ""),
                    customer_email=st.session_state.get("bundle_only_email", ""),
                    sales_order=st.session_state.get("bundle_only_order_number", ""),
                    amount=payment_amount,
                    payment_label="Payment Request",
                    phone=st.session_state.get("bundle_only_phone", ""),
                )

                st.session_state["bundle_only_payment_link"] = link_result["url"]
                st.session_state["bundle_only_stripe_session_id"] = link_result["session_id"]
                st.success("Stripe payment link created")
            except Exception as e:
                st.error(str(e))

    with p2:
        st.text_input(
            "Stripe Session ID",
            value=st.session_state.get("bundle_only_stripe_session_id", ""),
            disabled=True,
            key="bundle_only_stripe_session_id_display",
        )

    st.text_input(
        "Payment link",
        value=st.session_state.get("bundle_only_payment_link", ""),
        disabled=True,
        key="bundle_only_payment_link_display",
    )
    st.checkbox("Apply payment link button to PDF output", key="bundle_only_embed_link_in_pdf")

    bundle_bytes = None
    bundle_name = None

    try:
        customer_file_part = safe_filename(st.session_state.get("bundle_only_customer_name", ""), "customer")
        doc_suffix = "tax_invoice" if doc_type == "Tax Invoice" else "confirmation"
        bundle_name = f"{customer_file_part}_{doc_suffix}.pdf"

        bundle_bytes = build_single_bundle_pdf_bytes(
            main_pdf_bytes=st.session_state["bundle_only_order_pdf_bytes"],
            attachments=attachments,
            logo_path=LOGO_PATH,
            doc_type=doc_type,
            payment_url=st.session_state.get("bundle_only_payment_link", ""),
            embed_payment_link=bool(st.session_state.get("bundle_only_embed_link_in_pdf", False)),
        )
    except Exception as e:
        st.error(f"Bundle build failed: {e}")

    if bundle_bytes and bundle_name:
        st.markdown("### Quick download")
        q1, q2 = st.columns([2, 1])
        with q1:
            render_download_button(
                f"Combine & download PDF ({file_count} files)",
                bundle_bytes,
                bundle_name,
                file_count,
                doc_type,
                "top",
            )
        with q2:
            if st.session_state.get("bundle_only_embed_link_in_pdf", False):
                st.caption("Includes PDF payment link")

    st.markdown("### SMS payment request")

    template_names = list(st.session_state["bundle_only_templates"].keys())
    if st.session_state["bundle_only_template_name"] not in template_names:
        st.session_state["bundle_only_template_name"] = template_names[0]

    current_template = st.selectbox(
        "Template",
        template_names,
        index=template_names.index(st.session_state["bundle_only_template_name"]),
        key="bundle_only_template_select",
    )

    if current_template != st.session_state["bundle_only_template_name"]:
        st.session_state["bundle_only_template_name"] = current_template
        st.session_state["bundle_only_template_text"] = st.session_state["bundle_only_templates"][current_template]["text"]
        st.rerun()

    st.text_area(
        "Template text",
        key="bundle_only_template_text",
        height=110,
        help="Template only populates the SMS message. The SMS sends from the SMS message box below.",
    )

    t1, t2 = st.columns([1.2, 2.8])
    with t1:
        st.text_input("New template name", key="bundle_only_new_template_name")
    with t2:
        st.empty()

    a1, a2, a3, a4 = st.columns(4)

    with a1:
        if st.button("Load Template", use_container_width=True):
            st.session_state["bundle_only_sms_text"] = build_sms_message(
                {
                    "customer_name": st.session_state.get("bundle_only_customer_name", ""),
                    "order_number": st.session_state.get("bundle_only_order_number", ""),
                    "payment_amount": parse_numeric_input(st.session_state.get("bundle_only_payment_request", ""), 0),
                    "stripe_checkout_url": st.session_state.get("bundle_only_payment_link", ""),
                    "mobile": normalize_mobile_au(st.session_state.get("bundle_only_phone", "")),
                },
                st.session_state["bundle_only_template_text"],
            )
            st.rerun()

    with a2:
        if st.button("Save Template", use_container_width=True):
            name = st.session_state["bundle_only_template_name"].strip()
            if not name:
                st.error("Select a template first.")
            else:
                st.session_state["bundle_only_templates"][name] = {
                    "text": st.session_state.get("bundle_only_template_text", "").strip()
                }
                save_templates_to_file()
                st.success(f'Template "{name}" saved.')

    with a3:
        if st.button("Add Template", use_container_width=True):
            new_name = st.session_state["bundle_only_new_template_name"].strip()
            if not new_name:
                st.error("Enter a template name.")
            elif new_name in st.session_state["bundle_only_templates"]:
                st.error("A template with that name already exists.")
            else:
                st.session_state["bundle_only_templates"][new_name] = {
                    "text": st.session_state.get("bundle_only_template_text", "").strip()
                    or "Hi {customer_name}, payment for order {order_number} is now due. Amount payable: {payment_amount}. Please pay securely here: {stripe_checkout_url}"
                }
                save_templates_to_file()
                st.session_state["bundle_only_template_name"] = new_name
                st.session_state["bundle_only_new_template_name"] = ""
                st.success(f'Template "{new_name}" created.')
                st.rerun()

    with a4:
        if st.button("Delete Template", use_container_width=True):
            current = st.session_state["bundle_only_template_name"]
            if len(st.session_state["bundle_only_templates"]) == 1:
                st.error("At least one template must remain.")
            else:
                del st.session_state["bundle_only_templates"][current]
                save_templates_to_file()
                remaining = list(st.session_state["bundle_only_templates"].keys())
                st.session_state["bundle_only_template_name"] = remaining[0]
                st.session_state["bundle_only_template_text"] = st.session_state["bundle_only_templates"][remaining[0]]["text"]
                st.rerun()

    if st.button("Populate SMS message from current template", use_container_width=True):
        st.session_state["bundle_only_sms_text"] = build_sms_message(
            {
                "customer_name": st.session_state.get("bundle_only_customer_name", ""),
                "order_number": st.session_state.get("bundle_only_order_number", ""),
                "payment_amount": parse_numeric_input(st.session_state.get("bundle_only_payment_request", ""), 0),
                "stripe_checkout_url": st.session_state.get("bundle_only_payment_link", ""),
                "mobile": normalize_mobile_au(st.session_state.get("bundle_only_phone", "")),
            },
            st.session_state.get("bundle_only_template_text", ""),
        )
        st.rerun()

    sms_left, sms_right = st.columns([2.2, 1.1], gap="large")

    with sms_left:
        st.text_area(
            "SMS message",
            key="bundle_only_sms_text",
            height=180,
            help="Whatever is typed in this box is what will be sent.",
        )

    with sms_right:
        st.text_input(
            "SMS mobile",
            value=normalize_mobile_au(st.session_state.get("bundle_only_phone", "")),
            disabled=True,
            key="bundle_only_sms_mobile_display",
        )

        if st.button("Send SMS", use_container_width=True):
            mobile = normalize_mobile_au(st.session_state.get("bundle_only_phone", ""))
            if not mobile:
                st.error("No mobile number found.")
            elif not clean_text(st.session_state.get("bundle_only_sms_text", "")):
                st.error("SMS message is blank.")
            else:
                st.session_state["bundle_only_sms_confirm_name"] = st.session_state.get("bundle_only_customer_name", "")
                st.session_state["bundle_only_sms_confirm_phone"] = mobile
                st.session_state["bundle_only_sms_confirm_open"] = True
                st.rerun()

        st.text_input(
            "SMS status",
            value=st.session_state.get("bundle_only_sms_status", ""),
            disabled=True,
            key="bundle_only_sms_status_display",
        )

    if st.session_state.get("bundle_only_sms_confirm_open"):
        with st.container(border=True):
            mobile_fmt = st.session_state.get("bundle_only_sms_confirm_phone", "")
            st.warning(f"You are about to send an SMS to {mobile_fmt}")
            c1, c2 = st.columns(2)

            if c1.button("OK", use_container_width=True):
                try:
                    phone_value = normalize_mobile_au(st.session_state.get("bundle_only_phone", ""))
                    message = st.session_state.get("bundle_only_sms_text", "").strip()

                    if not phone_value:
                        raise RuntimeError("Customer phone is required.")
                    if not message:
                        raise RuntimeError("SMS message is blank.")

                    message_id = messagemedia_send_message(phone_value, message)
                    st.session_state["bundle_only_sms_status"] = f"Sent ({message_id})"
                    st.session_state["bundle_only_sms_confirm_open"] = False
                    st.success(f"SMS sent: {message_id}")
                    st.rerun()
                except Exception as e:
                    st.session_state["bundle_only_sms_status"] = f"Failed ({e})"
                    st.session_state["bundle_only_sms_confirm_open"] = False
                    st.error(str(e))

            if c2.button("Cancel", use_container_width=True):
                st.session_state["bundle_only_sms_confirm_open"] = False
                st.rerun()

    if bundle_bytes and bundle_name:
        st.markdown("### Final PDF")
        d1, d2 = st.columns([2, 1])

        with d1:
            render_download_button(
                f"Combine & download PDF ({file_count} files)",
                bundle_bytes,
                bundle_name,
                file_count,
                doc_type,
                "bottom",
            )

        with d2:
            if st.session_state.get("bundle_only_embed_link_in_pdf", False):
                st.caption("Includes PDF payment link")

    if attachments:
        st.caption("Bundle order:")
        for i, att in enumerate(attachments, start=1):
            r1, r2, r3 = st.columns([1, 7, 1])
            r1.write(i)
            suffix = " (default)" if att.get("locked") else ""
            r2.write(f"{att['name']}{suffix}")
            if att.get("locked"):
                r3.write("—")
            else:
                if r3.button("Remove", key=f"bundle_only_remove_att_{i}"):
                    attachments.pop(i - 1)
                    st.session_state["bundle_only_attachments"] = attachments
                    st.rerun()
else:
    st.info("Upload a sales order PDF to begin.")