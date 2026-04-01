import base64
import json
import os
import re
import time
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

try:
    import fitz
except Exception:
    fitz = None

try:
    import stripe
except Exception:
    stripe = None

try:
    import jwt
except Exception:
    jwt = None


APP_TITLE = "Add Stripe Payment Link"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_FILES_DIR = PROJECT_ROOT / "assets" / "default-files"

STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", "")).strip()
STRIPE_SUCCESS_URL = st.secrets.get("STRIPE_SUCCESS_URL", os.getenv("STRIPE_SUCCESS_URL", "")).strip()
STRIPE_CANCEL_URL = st.secrets.get("STRIPE_CANCEL_URL", os.getenv("STRIPE_CANCEL_URL", "")).strip()
STRIPE_CURRENCY = st.secrets.get("STRIPE_CURRENCY", os.getenv("STRIPE_CURRENCY", "aud")).strip().lower()

DOCUSIGN_INTEGRATION_KEY = st.secrets.get("DOCUSIGN_INTEGRATION_KEY", os.getenv("DOCUSIGN_INTEGRATION_KEY", "")).strip()
DOCUSIGN_USER_ID = st.secrets.get("DOCUSIGN_USER_ID", os.getenv("DOCUSIGN_USER_ID", "")).strip()
DOCUSIGN_ACCOUNT_ID = st.secrets.get("DOCUSIGN_ACCOUNT_ID", os.getenv("DOCUSIGN_ACCOUNT_ID", "")).strip()
DOCUSIGN_PRIVATE_KEY = st.secrets.get("DOCUSIGN_PRIVATE_KEY", os.getenv("DOCUSIGN_PRIVATE_KEY", "")).strip()
DOCUSIGN_AUTH_SERVER = st.secrets.get("DOCUSIGN_AUTH_SERVER", os.getenv("DOCUSIGN_AUTH_SERVER", "account-d.docusign.com")).strip()
DOCUSIGN_BASE_URI = st.secrets.get("DOCUSIGN_BASE_URI", os.getenv("DOCUSIGN_BASE_URI", "")).strip()
DOCUSIGN_SIGN_X_POSITION = st.secrets.get("DOCUSIGN_SIGN_X_POSITION", os.getenv("DOCUSIGN_SIGN_X_POSITION", "360")).strip()
DOCUSIGN_SIGN_Y_POSITION = st.secrets.get("DOCUSIGN_SIGN_Y_POSITION", os.getenv("DOCUSIGN_SIGN_Y_POSITION", "650")).strip()
DOCUSIGN_SIGN_PAGE = st.secrets.get("DOCUSIGN_SIGN_PAGE", os.getenv("DOCUSIGN_SIGN_PAGE", "last")).strip().lower()


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


def reset_diag():
    st.session_state.so_diag = []


def add_diag(label, value):
    if "so_diag" not in st.session_state:
        st.session_state.so_diag = []
    st.session_state.so_diag.append((label, value))


def directsms_connect(debug=False):
    username = get_secret("DIRECTSMS_USERNAME")
    password = get_secret("DIRECTSMS_PASSWORD")

    if not username or not password:
        raise ValueError("Missing DIRECTSMS_USERNAME or DIRECTSMS_PASSWORD in Streamlit secrets.")

    url = "https://api.directsms.com.au/s3/http/connect"
    resp = requests.post(url, data={"username": username, "password": password}, timeout=30)

    if debug:
        add_diag("Connect URL", url)
        add_diag("Connect HTTP status", resp.status_code)
        add_diag("Connect response body", resp.text)

    resp.raise_for_status()
    text = resp.text.strip()

    if text.lower().startswith("err:"):
        raise ValueError(text)
    if not text.lower().startswith("id:"):
        raise ValueError(f"Unexpected directSMS response: {text}")

    return text.split(":", 1)[1].strip()


def directsms_send_message(to_mobile, message, debug=False):
    connectionid = directsms_connect(debug=debug)
    senderid = get_secret("DIRECTSMS_SENDERID", "").strip()

    if not senderid:
        raise ValueError("Missing DIRECTSMS_SENDERID in Streamlit secrets.")

    data = {
        "connectionid": connectionid,
        "message": message,
        "to": normalize_mobile_au(to_mobile),
        "senderid": senderid,
        "type": "1-way",
    }

    url = "https://api.directsms.com.au/s3/http/send_message"
    resp = requests.post(url, data=data, timeout=30)

    if debug:
        add_diag("directSMS URL", url)
        add_diag("HTTP status", resp.status_code)
        add_diag("Response body", resp.text)
        add_diag("Payload", data)

    resp.raise_for_status()
    text = resp.text.strip()

    if text.lower().startswith("err:"):
        raise ValueError(text)
    if not text.lower().startswith("id:"):
        raise ValueError(f"Unexpected directSMS response: {text}")

    return text.split(":", 1)[1].strip()


def default_templates():
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


def build_sms_message(payload, template_text):
    return template_text.format(
        customer_name=str(payload.get("customer_name", "")).strip(),
        order_number=str(payload.get("order_number", "")).strip(),
        payment_amount=format_money(payload.get("payment_amount", 0)),
        stripe_checkout_url=str(payload.get("stripe_checkout_url", "")).strip(),
        mobile=str(payload.get("mobile", "")).strip(),
    )


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


def reset_session():
    keys = [
        "order_pdf_name",
        "order_pdf_bytes",
        "attachments",
        "customer_name",
        "customer_email",
        "phone",
        "sales_order",
        "order_date",
        "total_amount",
        "prepayment",
        "balance_due",
        "payment_mode",
        "payment_amount",
        "payment_label",
        "payment_link",
        "stripe_session_id",
        "apply_link_to_pdf",
        "sms_templates",
        "sms_template_name",
        "sms_template_text",
        "sms_new_template_name",
        "sms_status",
        "sms_confirm_open",
        "sms_confirm_name",
        "sms_confirm_phone",
        "operator_selected_label",
        "operator_selected_email",
        "operator_selected_name",
        "operator_selected_phone",
        "docusign_status",
        "docusign_envelope_id",
        "docusign_confirm_open",
        "docusign_confirm_name",
        "docusign_confirm_email",
        "docusign_confirm_operator",
        "so_diag",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def initialise_default_attachments():
    st.session_state["attachments"] = get_default_attachments()


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_money(text):
    if text is None:
        return None

    text = str(text).strip()
    if not text:
        return None

    text = text.replace("$", "").replace("kr", "").replace("DKK", "").strip()
    text = re.sub(r"[^\d,.\-]", "", text)

    if not text:
        return None

    if "," in text:
        text = text.replace(".", "")
        text = text.replace(",", ".")
    else:
        if text.count(".") > 1:
            text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def format_money(value):
    if value is None:
        return "-"
    return f"${value:,.2f}"


def parse_numeric_input(text, fallback=0.0):
    try:
        return float(str(text).replace(",", "").strip() or 0)
    except Exception:
        return float(fallback)


def find_value(pattern, text, group=1):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(group).strip() if match else ""


def extract_amount_after_label(label, text):
    pattern = (
        rf"{re.escape(label)}\s*"
        r"([\d]{1,3}(?:\.[\d]{3})*(?:,\d{2})|[\d]+,\d{2}|[\d]+(?:\.\d{2})?)"
    )
    return find_value(pattern, text)


def extract_totals_block(text):
    money_pattern = r"[\d]{1,3}(?:\.[\d]{3})*(?:,\d{2})|[\d]+,\d{2}|[\d]+(?:\.\d{2})?"

    total_raw = extract_amount_after_label("Total", text)
    prepayment_raw = extract_amount_after_label("Prepayment", text)
    balance_raw = extract_amount_after_label("Balance due", text)

    if total_raw and prepayment_raw and balance_raw:
        return total_raw, prepayment_raw, balance_raw

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    total_candidates = []
    prepayment_candidates = []
    balance_candidates = []

    for line in lines:
        if re.search(r"\bTotal\b", line, re.IGNORECASE):
            total_candidates.extend(re.findall(money_pattern, line))
        if re.search(r"\bPrepayment\b", line, re.IGNORECASE):
            prepayment_candidates.extend(re.findall(money_pattern, line))
        if re.search(r"\bBalance\s+due\b", line, re.IGNORECASE):
            balance_candidates.extend(re.findall(money_pattern, line))

    if not total_raw and total_candidates:
        total_raw = total_candidates[-1]
    if not prepayment_raw and prepayment_candidates:
        prepayment_raw = prepayment_candidates[-1]
    if not balance_raw and balance_candidates:
        balance_raw = balance_candidates[-1]

    if total_raw and prepayment_raw and not balance_raw:
        total_num = parse_money(total_raw)
        prepay_num = parse_money(prepayment_raw)
        if total_num is not None and prepay_num is not None:
            balance_raw = f"{(total_num - prepay_num):.2f}"

    return total_raw, prepayment_raw, balance_raw


def parse_sales_order_pdf_bytes(pdf_bytes: bytes):
    default_result = {
        "customer_name": "",
        "customer_email": "",
        "phone": "",
        "sales_order": "",
        "order_date": "",
        "total_amount": 0.0,
        "prepayment": 0.0,
        "balance_due": 0.0,
        "payment_mode": "balance",
        "payment_amount": 0.0,
        "payment_label": "Pay Balance Now",
    }

    if fitz is None:
        return default_result

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text("text") for page in doc)
        first_page = doc[0].get_text("text") if doc.page_count else ""
        doc.close()
    except Exception:
        return default_result

    lines = [clean_text(x) for x in first_page.splitlines() if clean_text(x)]

    customer_name = ""
    for line in lines[:12]:
        if not re.search(
            r"sales order|date|phone|email|misc\. charges|gst|total|prepayment|balance due",
            line,
            re.IGNORECASE,
        ):
            customer_name = line
            break

    total_raw, prepayment_raw, balance_raw = extract_totals_block(text)

    total_amount = parse_money(total_raw) or 0.0
    prepayment = parse_money(prepayment_raw) or 0.0
    balance_due = parse_money(balance_raw)

    if balance_due is None:
        balance_due = max(total_amount - prepayment, 0.0)

    return {
        "customer_name": customer_name,
        "customer_email": find_value(r"(?:E-?mail|Email)\s*:?\s*([^\s]+@[^\s]+)", text),
        "phone": find_value(r"(?:Mobile phone|Mobile|Phone|Telephone)\s*:?\s*([+\d][\d\s]+)", text),
        "sales_order": find_value(r"Sales order\s*:?\s*([A-Za-z0-9\-\/]+)", text),
        "order_date": find_value(r"Date\s*:?\s*([\d]{1,2}[\/\-.][\d]{1,2}[\/\-.][\d]{2,4})", text),
        "total_amount": float(total_amount),
        "prepayment": float(prepayment),
        "balance_due": float(balance_due),
        "payment_mode": "balance",
        "payment_amount": float(balance_due),
        "payment_label": "Pay Balance Now",
    }


def payment_choice_to_values(choice: str, total_amount: float, balance_due: float):
    total = round(float(total_amount or 0), 2)
    balance = round(float(balance_due or 0), 2)

    if choice == "deposit":
        if total <= 0:
            return {
                "payment_mode": "balance",
                "payment_amount": balance,
                "payment_label": "Pay Balance Now",
            }
        return {
            "payment_mode": "deposit",
            "payment_amount": round(total * 0.50, 2),
            "payment_label": "Pay 50% Deposit Now",
        }

    return {
        "payment_mode": "balance",
        "payment_amount": balance,
        "payment_label": "Pay Balance Now",
    }


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


def find_balance_anchor_on_last_page(page):
    try:
        words = page.get_text("words")
    except Exception:
        words = []

    if not words:
        return None

    lines = {}
    for w in words:
        x0, y0, x1, y1, text, block_no, line_no, word_no = w
        key = (block_no, line_no)
        lines.setdefault(key, []).append((x0, y0, x1, y1, str(text)))

    best = None

    for items in lines.values():
        items = sorted(items, key=lambda t: t[0])
        joined = " ".join(t[4] for t in items).strip().lower()

        if "balance due" in joined:
            min_x = min(t[0] for t in items)
            min_y = min(t[1] for t in items)
            max_y = max(t[3] for t in items)
            if best is None or max_y > best[2]:
                best = (min_x, min_y, max_y)

    return best


def draw_pay_button(page, rect, url, label_text):
    outer = (0.97, 0.44, 0.06)
    fill_top = (1.00, 0.78, 0.14)
    fill_bottom = (1.00, 0.50, 0.00)
    glow = (0.98, 0.84, 0.14)

    shape = page.new_shape()
    shape.draw_round_rect(rect, radius=12)
    shape.finish(color=outer, fill=fill_bottom, width=4)
    shape.commit()

    highlight_rect = fitz.Rect(rect.x0 + 6, rect.y0 + 6, rect.x1 - 6, rect.y0 + ((rect.y1 - rect.y0) / 2))
    shape = page.new_shape()
    shape.draw_round_rect(highlight_rect, radius=8)
    shape.finish(color=fill_top, fill=fill_top, width=0)
    shape.commit()

    glow_rect = fitz.Rect(rect.x0 - 4, rect.y0 - 4, rect.x1 + 4, rect.y1 + 4)
    shape = page.new_shape()
    shape.draw_round_rect(glow_rect, radius=14)
    shape.finish(color=glow, fill=None, width=2)
    shape.commit()

    page.insert_textbox(
        rect,
        label_text,
        fontsize=18,
        fontname="helv",
        color=(1, 1, 1),
        align=1,
        overlay=True,
    )

    page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": url})


def stamp_main_pdf_bytes(pdf_bytes: bytes, logo_path, button_label=None, button_url=None):
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for i, page in enumerate(doc):
        page_width = page.rect.width

        if logo_path and Path(logo_path).exists():
            left_x = get_page_text_left_margin(page)
            logo_rect = fitz.Rect(left_x, 18, left_x + 126, 60)
            page.insert_image(
                logo_rect,
                filename=str(logo_path),
                keep_proportion=True,
                overlay=True,
            )

        if button_label and button_url and i == len(doc) - 1:
            anchor = find_balance_anchor_on_last_page(page)

            button_width = 230
            button_height = 46

            if anchor:
                left_x = anchor[0]
                button_x = min(max(left_x, 28), page_width - button_width - 28)
                button_y = anchor[1] - 54
            else:
                button_x = page_width - button_width - 42
                button_y = page.rect.height - 170

            if button_y < 28:
                button_y = 28

            button_rect = fitz.Rect(button_x, button_y, button_x + button_width, button_y + button_height)
            draw_pay_button(page, button_rect, button_url, "PAY NOW")

    output = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return output


def append_image_bytes_as_pdf_pages(bundle_doc, image_bytes: bytes):
    img_doc = fitz.open(stream=image_bytes)
    pdf_bytes = img_doc.convert_to_pdf()
    img_doc.close()

    img_pdf = fitz.open("pdf", pdf_bytes)
    bundle_doc.insert_pdf(img_pdf)
    img_pdf.close()


def append_file_bytes_to_pdf(bundle_doc, file_name: str, file_bytes: bytes):
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


def build_single_bundle_pdf_bytes(main_pdf_bytes: bytes, attachments, logo_path, button_label=None, button_url=None):
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed")

    stamped_main_bytes = stamp_main_pdf_bytes(
        pdf_bytes=main_pdf_bytes,
        logo_path=logo_path,
        button_label=button_label,
        button_url=button_url,
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


def safe_filename(value: str, fallback: str = "customer"):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def init_template_state():
    if "sms_templates" not in st.session_state:
        st.session_state["sms_templates"] = default_templates()
    if "sms_template_name" not in st.session_state:
        st.session_state["sms_template_name"] = "Standard payment request"
    if "sms_new_template_name" not in st.session_state:
        st.session_state["sms_new_template_name"] = ""
    if "sms_template_text" not in st.session_state:
        st.session_state["sms_template_text"] = st.session_state["sms_templates"][st.session_state["sms_template_name"]]
    if "sms_status" not in st.session_state:
        st.session_state["sms_status"] = ""
    if "sms_confirm_open" not in st.session_state:
        st.session_state["sms_confirm_open"] = False
    if "sms_confirm_name" not in st.session_state:
        st.session_state["sms_confirm_name"] = ""
    if "sms_confirm_phone" not in st.session_state:
        st.session_state["sms_confirm_phone"] = ""
    if "so_diag" not in st.session_state:
        st.session_state["so_diag"] = []
    if "operator_selected_label" not in st.session_state:
        st.session_state["operator_selected_label"] = ""
    if "operator_selected_email" not in st.session_state:
        st.session_state["operator_selected_email"] = ""
    if "operator_selected_name" not in st.session_state:
        st.session_state["operator_selected_name"] = ""
    if "operator_selected_phone" not in st.session_state:
        st.session_state["operator_selected_phone"] = ""
    if "docusign_status" not in st.session_state:
        st.session_state["docusign_status"] = ""
    if "docusign_envelope_id" not in st.session_state:
        st.session_state["docusign_envelope_id"] = ""
    if "docusign_confirm_open" not in st.session_state:
        st.session_state["docusign_confirm_open"] = False
    if "docusign_confirm_name" not in st.session_state:
        st.session_state["docusign_confirm_name"] = ""
    if "docusign_confirm_email" not in st.session_state:
        st.session_state["docusign_confirm_email"] = ""
    if "docusign_confirm_operator" not in st.session_state:
        st.session_state["docusign_confirm_operator"] = ""


def find_operator_file():
    candidates = [
        PROJECT_ROOT / "operators.xlsx",
        PROJECT_ROOT / "operator_details.xlsx",
        PROJECT_ROOT / "operators.xlsm",
        PROJECT_ROOT / "operators.xls",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _find_matching_column(columns, names):
    lowered = {str(col).strip().lower(): col for col in columns}
    for name in names:
        if name in lowered:
            return lowered[name]
    for col in columns:
        c = str(col).strip().lower()
        for name in names:
            if name in c:
                return col
    return None


def load_operator_options():
    path = find_operator_file()
    if path is None:
        return []

    df = pd.read_excel(path)

    if df.empty:
        return []

    name_col = _find_matching_column(df.columns, ["operator", "name", "display name", "operator name"])
    email_col = _find_matching_column(df.columns, ["email", "operator email", "notification email", "docusign email"])
    phone_col = _find_matching_column(df.columns, ["phone", "mobile", "telephone"])

    if name_col is None or email_col is None:
        raise RuntimeError("Operator Excel must contain name/operator and email columns.")

    options = []
    for _, row in df.iterrows():
        name_value = clean_text(row.get(name_col, ""))
        email_value = clean_text(row.get(email_col, ""))
        phone_value = normalize_mobile_au(row.get(phone_col, "")) if phone_col else ""

        if not name_value or not email_value:
            continue

        label = f"{name_value} ({email_value})"
        options.append(
            {
                "label": label,
                "name": name_value,
                "email": email_value,
                "phone": phone_value,
            }
        )

    return options


def ensure_docusign_ready():
    if jwt is None:
        raise RuntimeError("PyJWT package not installed")
    if not DOCUSIGN_INTEGRATION_KEY:
        raise RuntimeError("Missing DOCUSIGN_INTEGRATION_KEY in Streamlit secrets")
    if not DOCUSIGN_USER_ID:
        raise RuntimeError("Missing DOCUSIGN_USER_ID in Streamlit secrets")
    if not DOCUSIGN_ACCOUNT_ID:
        raise RuntimeError("Missing DOCUSIGN_ACCOUNT_ID in Streamlit secrets")
    if not DOCUSIGN_PRIVATE_KEY:
        raise RuntimeError("Missing DOCUSIGN_PRIVATE_KEY in Streamlit secrets")
    if not DOCUSIGN_BASE_URI:
        raise RuntimeError("Missing DOCUSIGN_BASE_URI in Streamlit secrets")


def docusign_get_access_token():
    ensure_docusign_ready()

    now = int(time.time())
    payload = {
        "iss": DOCUSIGN_INTEGRATION_KEY,
        "sub": DOCUSIGN_USER_ID,
        "aud": DOCUSIGN_AUTH_SERVER,
        "iat": now,
        "exp": now + 3600,
        "scope": "signature impersonation",
    }

    assertion = jwt.encode(payload, DOCUSIGN_PRIVATE_KEY, algorithm="RS256")

    token_url = f"https://{DOCUSIGN_AUTH_SERVER}/oauth/token"
    resp = requests.post(
        token_url,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=30,
    )

    add_diag("DocuSign token URL", token_url)
    add_diag("DocuSign token status", resp.status_code)

    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError("DocuSign access token was not returned")

    return data["access_token"]


def build_docusign_document_bytes():
    button_label = None
    button_url = None
    if st.session_state.get("apply_link_to_pdf") and st.session_state.get("payment_link"):
        button_label = st.session_state.get("payment_label") or "Pay Now"
        button_url = st.session_state.get("payment_link")

    return stamp_main_pdf_bytes(
        pdf_bytes=st.session_state["order_pdf_bytes"],
        logo_path=LOGO_PATH,
        button_label=button_label,
        button_url=button_url,
    )


def docusign_send_for_signature(customer_name, customer_email, operator_email):
    access_token = docusign_get_access_token()
    pdf_bytes = build_docusign_document_bytes()
    document_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    try:
        sign_x = str(int(float(DOCUSIGN_SIGN_X_POSITION)))
        sign_y = str(int(float(DOCUSIGN_SIGN_Y_POSITION)))
    except Exception:
        sign_x = "360"
        sign_y = "650"

    page_number = "1"
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if DOCUSIGN_SIGN_PAGE == "last":
                page_number = str(doc.page_count)
            else:
                page_number = str(max(int(DOCUSIGN_SIGN_PAGE), 1))
            doc.close()
        except Exception:
            page_number = "1"

    signer = {
        "email": customer_email,
        "name": customer_name,
        "recipientId": "1",
        "routingOrder": "1",
        "tabs": {
            "signHereTabs": [
                {
                    "documentId": "1",
                    "pageNumber": page_number,
                    "xPosition": sign_x,
                    "yPosition": sign_y,
                }
            ]
        },
    }

    carbon_copies = []
    if operator_email:
        carbon_copies.append(
            {
                "email": operator_email,
                "name": operator_email,
                "recipientId": "2",
                "routingOrder": "2",
            }
        )

    envelope_definition = {
        "emailSubject": f"Please sign BoConcept order {st.session_state.get('sales_order', '')}".strip(),
        "documents": [
            {
                "documentBase64": document_b64,
                "name": f"{st.session_state.get('sales_order', 'Sales Order')}.pdf",
                "fileExtension": "pdf",
                "documentId": "1",
            }
        ],
        "recipients": {
            "signers": [signer],
            "carbonCopies": carbon_copies,
        },
        "status": "sent",
    }

    url = f"{DOCUSIGN_BASE_URI.rstrip('/')}/restapi/v2.1/accounts/{DOCUSIGN_ACCOUNT_ID}/envelopes"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    add_diag("DocuSign envelope URL", url)

    resp = requests.post(url, headers=headers, data=json.dumps(envelope_definition), timeout=60)

    add_diag("DocuSign envelope status", resp.status_code)
    add_diag("DocuSign envelope response", resp.text)

    resp.raise_for_status()
    data = resp.json()

    envelope_id = data.get("envelopeId", "")
    if not envelope_id:
        raise RuntimeError("DocuSign envelopeId was not returned")

    return envelope_id


st.set_page_config(page_title=APP_TITLE, layout="wide")
init_template_state()

top_nav_left, top_nav_right = st.columns([1, 5])
with top_nav_left:
    if st.button("Home", use_container_width=True):
        st.switch_page("main.py")
with top_nav_right:
    if LOGO_PATH:
        st.image(str(LOGO_PATH), width=220)

st.title(APP_TITLE)

top_a, top_b = st.columns([3, 1])
if STRIPE_SECRET_KEY:
    top_a.caption("Stripe configured")
else:
    top_a.warning("Stripe secret missing.")

default_attachments = get_default_attachments()
if default_attachments:
    st.caption(f"Locked default bundle files: {len(default_attachments)}")
else:
    st.warning("No files found in assets/default-files")

operator_options = []
operator_error = ""
try:
    operator_options = load_operator_options()
except Exception as e:
    operator_error = str(e)

if operator_error:
    st.warning(operator_error)
elif not operator_options:
    st.warning("No operator file found or no operator records available.")

if top_b.button("Reset Session", use_container_width=True):
    reset_session()
    st.rerun()

st.caption("Session-only mode. Nothing is saved after reload.")

uploaded_pdf = st.file_uploader("Upload sales order PDF", type=["pdf"], key="orders_pdf")

if uploaded_pdf is not None:
    pdf_bytes = uploaded_pdf.getvalue()

    if (
        st.session_state.get("order_pdf_name") != uploaded_pdf.name
        or st.session_state.get("order_pdf_bytes") != pdf_bytes
    ):
        parsed = parse_sales_order_pdf_bytes(pdf_bytes)

        st.session_state["order_pdf_name"] = uploaded_pdf.name
        st.session_state["order_pdf_bytes"] = pdf_bytes
        initialise_default_attachments()
        st.session_state["payment_link"] = ""
        st.session_state["stripe_session_id"] = ""
        st.session_state["apply_link_to_pdf"] = True
        st.session_state["docusign_status"] = ""
        st.session_state["docusign_envelope_id"] = ""

        st.session_state["customer_name"] = parsed["customer_name"]
        st.session_state["customer_email"] = parsed["customer_email"]
        st.session_state["phone"] = parsed["phone"]
        st.session_state["sales_order"] = parsed["sales_order"]
        st.session_state["order_date"] = parsed["order_date"]
        st.session_state["total_amount"] = parsed["total_amount"]
        st.session_state["prepayment"] = parsed["prepayment"]
        st.session_state["balance_due"] = parsed["balance_due"]

        calc = payment_choice_to_values("balance", parsed["total_amount"], parsed["balance_due"])
        st.session_state["payment_mode"] = calc["payment_mode"]
        st.session_state["payment_amount"] = calc["payment_amount"]
        st.session_state["payment_label"] = calc["payment_label"]

if st.session_state.get("order_pdf_bytes"):
    st.markdown("### Current Order")

    current_total_for_options = float(st.session_state.get("total_amount", 0.0) or 0.0)
    payment_options = ["balance"] if current_total_for_options <= 0 else ["balance", "deposit"]
    current_mode = st.session_state.get("payment_mode", "balance")
    if current_mode not in payment_options:
        current_mode = "balance"

    selected_operator_index = 0
    current_operator_label = st.session_state.get("operator_selected_label", "")
    if operator_options and current_operator_label:
        matches = [i for i, x in enumerate(operator_options) if x["label"] == current_operator_label]
        if matches:
            selected_operator_index = matches[0]

    with st.form("order_form"):
        operator_choice = None
        if operator_options:
            operator_choice = st.selectbox(
                "Operator",
                options=operator_options,
                index=selected_operator_index,
                format_func=lambda x: x["label"],
            )
        else:
            st.text_input("Operator", value="No operator records available", disabled=True)

        col_a, col_b, col_c = st.columns(3)
        customer_name = col_a.text_input("Customer", value=st.session_state.get("customer_name", ""))
        customer_email = col_b.text_input("Email", value=st.session_state.get("customer_email", ""))
        phone = col_c.text_input("Phone", value=st.session_state.get("phone", ""))

        col_d, col_e, col_f = st.columns(3)
        sales_order = col_d.text_input("Sales order", value=st.session_state.get("sales_order", ""))
        order_date = col_e.text_input("Order date", value=st.session_state.get("order_date", ""))
        payment_choice = col_f.radio(
            "Payment type",
            options=payment_options,
            index=payment_options.index(current_mode),
            format_func=lambda x: "Balance" if x == "balance" else "Deposit 50%",
            horizontal=True,
        )

        col_g, col_h, col_i, col_j = st.columns(4)
        total_amount = col_g.text_input("Total", value=f"{float(st.session_state.get('total_amount', 0.0)):.2f}")
        prepayment = col_h.text_input("Prepayment", value=f"{float(st.session_state.get('prepayment', 0.0)):.2f}")
        balance_due = col_i.text_input("Balance due", value=f"{float(st.session_state.get('balance_due', 0.0)):.2f}")
        apply_link_to_pdf = col_j.checkbox("Apply link to PDF", value=st.session_state.get("apply_link_to_pdf", True))

        parsed_total_amount = parse_numeric_input(total_amount, st.session_state.get("total_amount", 0.0))
        parsed_prepayment = parse_numeric_input(prepayment, st.session_state.get("prepayment", 0.0))
        parsed_balance_due = parse_numeric_input(balance_due, st.session_state.get("balance_due", 0.0))

        payment_calc = payment_choice_to_values(payment_choice, parsed_total_amount, parsed_balance_due)

        payment_amount_input = st.text_input(
            "Payment amount",
            value=f"{float(st.session_state.get('payment_amount', payment_calc['payment_amount'])):.2f}",
        )
        overridden_payment_amount = parse_numeric_input(payment_amount_input, payment_calc["payment_amount"])
        effective_payment_label = "Pay 50% Deposit Now" if payment_choice == "deposit" else "Pay Balance Now"

        st.caption(
            f"{effective_payment_label}  |  "
            f"Balance due: {format_money(parsed_balance_due)}  |  "
            f"Payment amount: {format_money(overridden_payment_amount)}"
        )

        if st.session_state.get("payment_link"):
            st.text_input("Payment link", value=st.session_state.get("payment_link", ""), disabled=True)

        b1, b2, b3 = st.columns(3)
        save_clicked = b1.form_submit_button("Apply Changes")
        create_link_clicked = b2.form_submit_button("Create Stripe Link")
        send_docusign_clicked = b3.form_submit_button("Send to DocuSign")

    if operator_choice:
        st.session_state["operator_selected_label"] = operator_choice["label"]
        st.session_state["operator_selected_email"] = operator_choice["email"]
        st.session_state["operator_selected_name"] = operator_choice["name"]
        st.session_state["operator_selected_phone"] = operator_choice["phone"]

    if save_clicked:
        st.session_state["customer_name"] = customer_name
        st.session_state["customer_email"] = customer_email
        st.session_state["phone"] = normalize_mobile_au(phone)
        st.session_state["sales_order"] = sales_order
        st.session_state["order_date"] = order_date
        st.session_state["total_amount"] = parsed_total_amount
        st.session_state["prepayment"] = parsed_prepayment
        st.session_state["balance_due"] = parsed_balance_due
        st.session_state["payment_mode"] = payment_choice
        st.session_state["payment_amount"] = overridden_payment_amount
        st.session_state["payment_label"] = effective_payment_label
        st.session_state["apply_link_to_pdf"] = apply_link_to_pdf
        st.success("Changes applied to current session")
        st.rerun()

    if create_link_clicked:
        try:
            st.session_state["customer_name"] = customer_name
            st.session_state["customer_email"] = customer_email
            st.session_state["phone"] = normalize_mobile_au(phone)
            st.session_state["sales_order"] = sales_order
            st.session_state["order_date"] = order_date
            st.session_state["total_amount"] = parsed_total_amount
            st.session_state["prepayment"] = parsed_prepayment
            st.session_state["balance_due"] = parsed_balance_due
            st.session_state["payment_mode"] = payment_choice
            st.session_state["payment_amount"] = overridden_payment_amount
            st.session_state["payment_label"] = effective_payment_label
            st.session_state["apply_link_to_pdf"] = apply_link_to_pdf

            link_result = create_stripe_checkout_link(
                customer_name=customer_name,
                customer_email=customer_email,
                sales_order=sales_order,
                amount=overridden_payment_amount,
                payment_label=effective_payment_label,
                phone=phone,
            )

            st.session_state["payment_link"] = link_result["url"]
            st.session_state["stripe_session_id"] = link_result["session_id"]
            st.session_state["sms_status"] = ""

            st.success("Stripe payment link created")
            st.code(link_result["url"])
            st.rerun()
        except Exception as e:
            st.error(str(e))

    if send_docusign_clicked:
        st.session_state["customer_name"] = customer_name
        st.session_state["customer_email"] = customer_email
        st.session_state["phone"] = normalize_mobile_au(phone)
        st.session_state["sales_order"] = sales_order
        st.session_state["order_date"] = order_date
        st.session_state["total_amount"] = parsed_total_amount
        st.session_state["prepayment"] = parsed_prepayment
        st.session_state["balance_due"] = parsed_balance_due
        st.session_state["payment_mode"] = payment_choice
        st.session_state["payment_amount"] = overridden_payment_amount
        st.session_state["payment_label"] = effective_payment_label
        st.session_state["apply_link_to_pdf"] = apply_link_to_pdf

        if not st.session_state.get("customer_email", "").strip():
            st.error("Customer email is required.")
        elif not st.session_state.get("operator_selected_email", "").strip():
            st.error("Select an operator first.")
        else:
            st.session_state["docusign_confirm_name"] = st.session_state.get("customer_name", "")
            st.session_state["docusign_confirm_email"] = st.session_state.get("customer_email", "")
            st.session_state["docusign_confirm_operator"] = st.session_state.get("operator_selected_label", "")
            st.session_state["docusign_confirm_open"] = True

    if st.session_state.get("docusign_confirm_open"):
        with st.container(border=True):
            st.warning(
                f"About to send DocuSign to {st.session_state.get('docusign_confirm_name', '')} "
                f"({st.session_state.get('docusign_confirm_email', '')}) "
                f"with operator {st.session_state.get('docusign_confirm_operator', '')} copied."
            )
            c1, c2 = st.columns(2)
            if c1.button("Confirm Send to DocuSign", use_container_width=True, key="confirm_docusign_send"):
                try:
                    reset_diag()
                    envelope_id = docusign_send_for_signature(
                        customer_name=st.session_state.get("customer_name", ""),
                        customer_email=st.session_state.get("customer_email", ""),
                        operator_email=st.session_state.get("operator_selected_email", ""),
                    )
                    st.session_state["docusign_envelope_id"] = envelope_id
                    st.session_state["docusign_status"] = f"Sent ({envelope_id})"
                    st.session_state["docusign_confirm_open"] = False
                    st.success(f"DocuSign envelope sent: {envelope_id}")
                except Exception as e:
                    st.session_state["docusign_status"] = f"Failed ({e})"
                    st.session_state["docusign_confirm_open"] = False
                    st.error(str(e))
            if c2.button("Cancel", use_container_width=True, key="cancel_docusign_send"):
                st.session_state["docusign_confirm_open"] = False
                st.rerun()

    if st.session_state.get("docusign_status"):
        st.text_input("DocuSign Status", value=st.session_state.get("docusign_status", ""), disabled=True)

    st.markdown("### Additional Files")
    extra_files = st.file_uploader(
        "Upload extra PDF or image files",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="attachments_uploader",
    )

    a1, a2 = st.columns([2, 1])

    if a1.button("Add Files to Bundle"):
        if extra_files:
            if "attachments" not in st.session_state:
                initialise_default_attachments()

            for up in extra_files:
                st.session_state["attachments"].append(
                    {
                        "name": up.name,
                        "bytes": up.getvalue(),
                        "locked": False,
                        "source": "user",
                    }
                )

            st.success(f"Added {len(extra_files)} attachment file(s)")
            st.rerun()
        else:
            st.warning("Choose files first")

    attachments = st.session_state.get("attachments", [])

    file_count = len(attachments) + 1
    if a2.button(
        f"Download PDF ({file_count} files)",
        use_container_width=True,
        disabled=not st.session_state.get("order_pdf_bytes"),
    ):
        try:
            customer_file_part = safe_filename(st.session_state.get("customer_name", ""), "customer")
            bundle_name = f"{customer_file_part}.pdf"

            button_label = None
            button_url = None
            if st.session_state.get("apply_link_to_pdf") and st.session_state.get("payment_link"):
                button_label = st.session_state.get("payment_label") or "Pay Now"
                button_url = st.session_state.get("payment_link")

            bundle_bytes = build_single_bundle_pdf_bytes(
                main_pdf_bytes=st.session_state["order_pdf_bytes"],
                attachments=attachments,
                logo_path=LOGO_PATH,
                button_label=button_label,
                button_url=button_url,
            )

            st.download_button(
                "Download PDF",
                data=bundle_bytes,
                file_name=bundle_name,
                mime="application/pdf",
                use_container_width=True,
                key=f"sales_order_download_{bundle_name}_{len(bundle_bytes)}",
            )
            st.success("PDF ready for download")
        except Exception as e:
            st.error(f"Bundle build failed: {e}")

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
                if r3.button("Remove", key=f"remove_att_{i}"):
                    attachments.pop(i - 1)
                    st.session_state["attachments"] = attachments
                    st.rerun()

    st.markdown("---")
    st.subheader("SMS Templates")

    templates = st.session_state["sms_templates"]
    template_names = list(templates.keys())

    selected_template = st.selectbox(
        "Template",
        template_names,
        index=template_names.index(st.session_state["sms_template_name"])
        if st.session_state["sms_template_name"] in template_names else 0,
        key="so_template_select",
    )

    if selected_template != st.session_state["sms_template_name"]:
        st.session_state["sms_template_name"] = selected_template
        st.session_state["sms_template_text"] = templates[selected_template]
        st.rerun()

    st.session_state["sms_template_text"] = st.text_area(
        "Template text",
        value=st.session_state["sms_template_text"],
        height=120,
        key="so_template_text",
        help="Placeholders: {customer_name}, {order_number}, {payment_amount}, {stripe_checkout_url}, {mobile}",
    )

    st.session_state["sms_templates"][st.session_state["sms_template_name"]] = st.session_state["sms_template_text"]

    t1, t2, t3 = st.columns([2, 1, 1])

    with t1:
        st.session_state["sms_new_template_name"] = st.text_input(
            "New template name",
            value=st.session_state["sms_new_template_name"],
            key="so_new_template_name",
        )

    with t2:
        if st.button("Add Template", use_container_width=True, key="so_add_template"):
            new_name = st.session_state["sms_new_template_name"].strip()
            if not new_name:
                st.error("Enter a template name.")
            elif new_name in st.session_state["sms_templates"]:
                st.error("A template with that name already exists.")
            else:
                st.session_state["sms_templates"][new_name] = (
                    "Hi {customer_name}, payment for order {order_number} is now due. "
                    "Amount payable: {payment_amount}. Please pay securely here: {stripe_checkout_url}"
                )
                st.session_state["sms_template_name"] = new_name
                st.session_state["sms_template_text"] = st.session_state["sms_templates"][new_name]
                st.session_state["sms_new_template_name"] = ""
                st.rerun()

    with t3:
        if st.button("Delete Template", use_container_width=True, key="so_delete_template"):
            current = st.session_state["sms_template_name"]
            if len(st.session_state["sms_templates"]) == 1:
                st.error("At least one template must remain.")
            else:
                del st.session_state["sms_templates"][current]
                remaining = list(st.session_state["sms_templates"].keys())
                st.session_state["sms_template_name"] = remaining[0]
                st.session_state["sms_template_text"] = st.session_state["sms_templates"][remaining[0]]
                st.rerun()

    st.caption("Available placeholders: {customer_name}, {order_number}, {payment_amount}, {stripe_checkout_url}, {mobile}")

    preview_payload = {
        "customer_name": st.session_state.get("customer_name", ""),
        "order_number": st.session_state.get("sales_order", ""),
        "payment_amount": st.session_state.get("payment_amount", 0),
        "stripe_checkout_url": st.session_state.get("payment_link", ""),
        "mobile": st.session_state.get("phone", ""),
    }

    if st.session_state.get("payment_link"):
        st.text_area(
            "SMS Preview",
            value=build_sms_message(preview_payload, st.session_state["sms_template_text"]),
            height=110,
            disabled=True,
        )

    if st.button("Send SMS to Customer", use_container_width=True, key="so_open_confirm"):
        if not st.session_state.get("payment_link"):
            st.error("Create the Stripe payment link first.")
        elif not normalize_mobile_au(st.session_state.get("phone", "")):
            st.error("Customer phone is required.")
        else:
            st.session_state["sms_confirm_name"] = st.session_state.get("customer_name", "")
            st.session_state["sms_confirm_phone"] = normalize_mobile_au(st.session_state.get("phone", ""))
            st.session_state["sms_confirm_open"] = True

    if st.session_state.get("sms_confirm_open"):
        with st.container(border=True):
            st.warning(
                f"About to send SMS to {st.session_state.get('sms_confirm_name', '')} "
                f"({st.session_state.get('sms_confirm_phone', '')})."
            )
            c1, c2 = st.columns(2)
            if c1.button("Confirm Send SMS", use_container_width=True, key="so_confirm_send"):
                try:
                    reset_diag()
                    sms_message = build_sms_message(
                        {
                            "customer_name": st.session_state.get("customer_name", ""),
                            "order_number": st.session_state.get("sales_order", ""),
                            "payment_amount": st.session_state.get("payment_amount", 0),
                            "stripe_checkout_url": st.session_state.get("payment_link", ""),
                            "mobile": st.session_state.get("phone", ""),
                        },
                        st.session_state["sms_template_text"],
                    )
                    message_id = directsms_send_message(st.session_state.get("phone", ""), sms_message, debug=True)
                    st.session_state["sms_status"] = f"Sent ({message_id})"
                    st.session_state["sms_confirm_open"] = False
                    st.success(f"SMS sent: {message_id}")
                except Exception as e:
                    st.session_state["sms_status"] = f"Failed ({e})"
                    st.session_state["sms_confirm_open"] = False
                    st.error(str(e))
            if c2.button("Cancel", use_container_width=True, key="so_cancel_send"):
                st.session_state["sms_confirm_open"] = False
                st.rerun()

    if st.session_state.get("sms_status"):
        st.text_input("SMS Status", value=st.session_state.get("sms_status", ""), disabled=True)

    with st.expander("Diagnostics"):
        if st.session_state.get("so_diag"):
            for label, value in st.session_state["so_diag"]:
                st.write(f"**{label}:** {value}")
else:
    st.info("Upload a sales order PDF to begin.")