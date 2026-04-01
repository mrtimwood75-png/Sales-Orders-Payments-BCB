import re
from pathlib import Path

import streamlit as st
import requests

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None


APP_TITLE = "Add Logo & Bundle Attachments"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_FILES_DIR = PROJECT_ROOT / "assets" / "default-files"


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


def messagemedia_config():
    api_key = get_secret("MESSAGEMEDIA_API_KEY")
    api_secret = get_secret("MESSAGEMEDIA_API_SECRET")
    sender_id = get_secret("MESSAGEMEDIA_SENDER_ID", "").strip()
    base_url = get_secret("MESSAGEMEDIA_BASE_URL", "https://api.messagemedia.com").strip().rstrip("/")

    if not api_key or not api_secret:
        raise ValueError("Missing MESSAGEMEDIA_API_KEY or MESSAGEMEDIA_API_SECRET in Streamlit secrets.")

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "sender_id": sender_id,
        "base_url": base_url,
    }


def messagemedia_send_message(to_mobile, message):
    cfg = messagemedia_config()

    payload = {
        "messages": [
            {
                "content": message,
                "destination_number": normalize_mobile_au(to_mobile),
                "format": "SMS",
            }
        ]
    }

    if cfg["sender_id"]:
        payload["messages"][0]["source_number"] = cfg["sender_id"]

    url = f"{cfg['base_url']}/v1/messages"

    resp = requests.post(
        url,
        json=payload,
        auth=(cfg["api_key"], cfg["api_secret"]),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()

    body = resp.json()
    messages = body.get("messages") or []
    if not messages:
        raise ValueError(f"Unexpected MessageMedia response: {body}")

    message_id = messages[0].get("message_id") or messages[0].get("messageId")
    if not message_id:
        raise ValueError(f"MessageMedia response missing message_id: {body}")

    return str(message_id)


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


def reset_session():
    keys = [
        "bundle_only_order_pdf_name",
        "bundle_only_order_pdf_bytes",
        "bundle_only_attachments",
        "bundle_only_customer_name",
        "bundle_only_doc_type",
        "bundle_only_order_fields",
        "bundle_only_payment_request",
        "bundle_only_sms_text",
        "bundle_only_sms_status",
    ]
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def safe_filename(value, fallback="customer"):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def format_amount_au(value):
    try:
        num = float(str(value).replace(",", ""))
        return f"${num:,.2f}"
    except Exception:
        return str(value or "")


def parse_amount_from_text(value):
    text = clean_text(value)
    if not text:
        return ""
    m = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})|[0-9]+[.,][0-9]{2})", text)
    return m.group(1) if m else text


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

    finally:
        doc.close()

    return fields


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
        rect = fitz.Rect(span["rect"].x0 - 3, span["rect"].y0 - 2, span["rect"].x1 + 3, span["rect"].y1 + 2)
        fontname = choose_pymupdf_font(span.get("font"))
        font_size = max(12, min(span.get("size", 18), 22))

        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        test_rect = fitz.Rect(rect.x0, rect.y0, rect.x1 + 70, rect.y1)
        inserted = 0
        while font_size >= 10:
            inserted = page.insert_textbox(
                test_rect,
                "Tax Invoice",
                fontsize=font_size,
                fontname=fontname,
                align=0,
                color=(0, 0, 0),
                overlay=True,
            )
            if inserted >= 0:
                break
            font_size -= 0.5

        return

    fallback_rect = fitz.Rect(300, 118, 470, 140)
    page.draw_rect(fallback_rect, color=None, fill=(1, 1, 1), overlay=True)
    page.insert_textbox(
        fallback_rect,
        "Tax Invoice",
        fontsize=18,
        fontname="helvB",
        align=0,
        color=(0, 0, 0),
        overlay=True,
    )


def stamp_main_pdf_bytes(pdf_bytes, logo_path, doc_type):
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


def build_single_bundle_pdf_bytes(main_pdf_bytes, attachments, logo_path, doc_type):
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed")

    stamped_main_bytes = stamp_main_pdf_bytes(main_pdf_bytes, logo_path, doc_type)

    final_doc = fitz.open()

    main_doc = fitz.open(stream=stamped_main_bytes, filetype="pdf")
    final_doc.insert_pdf(main_doc)
    main_doc.close()

    for att in attachments:
        append_file_bytes_to_pdf(final_doc, att["name"], att["bytes"])

    output = final_doc.tobytes(garbage=4, deflate=True)
    final_doc.close()
    return output


def build_sms_text(fields, payment_request):
    customer_name = clean_text(fields.get("customer_name", "Customer"))
    order_number = clean_text(fields.get("order_number", ""))
    amount_text = format_amount_au(payment_request) if payment_request else ""
    if order_number and amount_text:
        return f"Hi {customer_name}, a payment of {amount_text} is requested for order {order_number}. Please contact us if you have any questions."
    if amount_text:
        return f"Hi {customer_name}, a payment of {amount_text} is requested. Please contact us if you have any questions."
    return f"Hi {customer_name}, please contact us regarding your order."


st.set_page_config(page_title=APP_TITLE, layout="wide")

if "bundle_only_doc_type" not in st.session_state:
    st.session_state["bundle_only_doc_type"] = "Confirmation"
if "bundle_only_payment_request" not in st.session_state:
    st.session_state["bundle_only_payment_request"] = ""
if "bundle_only_sms_text" not in st.session_state:
    st.session_state["bundle_only_sms_text"] = ""
if "bundle_only_sms_status" not in st.session_state:
    st.session_state["bundle_only_sms_status"] = ""

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

uploaded_pdf = st.file_uploader(
    "Upload sales order PDF",
    type=["pdf"],
    key="bundle_only_orders_pdf",
)

if uploaded_pdf is not None:
    pdf_bytes = uploaded_pdf.getvalue()

    if (
        st.session_state.get("bundle_only_order_pdf_name") != uploaded_pdf.name
        or st.session_state.get("bundle_only_order_pdf_bytes") != pdf_bytes
    ):
        st.session_state["bundle_only_order_pdf_name"] = uploaded_pdf.name
        st.session_state["bundle_only_order_pdf_bytes"] = pdf_bytes

        fields = extract_sales_order_fields(pdf_bytes)
        st.session_state["bundle_only_order_fields"] = fields
        st.session_state["bundle_only_customer_name"] = fields.get("customer_name", "")
        st.session_state["bundle_only_payment_request"] = fields.get("order_balance", "")
        st.session_state["bundle_only_sms_text"] = build_sms_text(fields, fields.get("order_balance", ""))

        initialise_default_attachments()

if st.session_state.get("bundle_only_order_pdf_bytes"):
    left_col, right_col = st.columns([2.2, 1.2])

    with left_col:
        st.text_input(
            "Customer",
            value=st.session_state.get("bundle_only_customer_name", ""),
            disabled=True,
        )

    with right_col:
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

    a1, a2 = st.columns([2, 1])

    if a1.button("Add Files to Bundle", use_container_width=True):
        if extra_files:
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
                added_count += 1

            if added_count:
                st.success(f"Added {added_count} attachment file(s)")
            else:
                st.info("No new files were added")
            st.rerun()
        else:
            st.warning("Choose files first")

    attachments = st.session_state.get("bundle_only_attachments", [])
    file_count = len(attachments) + 1
    doc_type = st.session_state.get("bundle_only_doc_type", "Confirmation")

    try:
        fields = st.session_state.get("bundle_only_order_fields", {})
        customer_file_part = safe_filename(
            fields.get("customer_name", "") or st.session_state.get("bundle_only_customer_name", ""),
            "customer",
        )
        doc_suffix = "tax_invoice" if doc_type == "Tax Invoice" else "confirmation"
        bundle_name = f"{customer_file_part}_{doc_suffix}.pdf"

        bundle_bytes = build_single_bundle_pdf_bytes(
            main_pdf_bytes=st.session_state["bundle_only_order_pdf_bytes"],
            attachments=attachments,
            logo_path=LOGO_PATH,
            doc_type=doc_type,
        )

        a2.download_button(
            f"Combine & download PDF ({file_count} files)",
            data=bundle_bytes,
            file_name=bundle_name,
            mime="application/pdf",
            use_container_width=True,
            key=f"bundle_only_download_{bundle_name}_{len(bundle_bytes)}_{doc_type}",
        )
    except Exception as e:
        a2.button(
            f"Combine & download PDF ({file_count} files)",
            use_container_width=True,
            disabled=True,
        )
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
                if r3.button("Remove", key=f"bundle_only_remove_att_{i}"):
                    attachments.pop(i - 1)
                    st.session_state["bundle_only_attachments"] = attachments
                    st.rerun()

    fields = st.session_state.get("bundle_only_order_fields", {})

    st.markdown("### Captured order fields")
    cf1, cf2 = st.columns(2)
    with cf1:
        st.text_input("Order number", value=fields.get("order_number", ""), disabled=True)
        st.text_input("Order total", value=fields.get("order_total", ""), disabled=True)
        st.text_input("Email", value=fields.get("email", ""), disabled=True)
    with cf2:
        st.text_input("Order balance", value=fields.get("order_balance", ""), disabled=True)
        st.text_input("Phone", value=fields.get("phone", ""), disabled=True)
        st.text_input("Payment Request", key="bundle_only_payment_request")

    st.text_area(
        "Customer address",
        value=fields.get("customer_address", ""),
        disabled=True,
        height=120,
    )

    st.markdown("### SMS payment request")
    sms_col1, sms_col2 = st.columns([2, 1])

    with sms_col1:
        if st.button("Build SMS from payment request", use_container_width=True):
            st.session_state["bundle_only_sms_text"] = build_sms_text(
                fields,
                st.session_state.get("bundle_only_payment_request", ""),
            )
            st.rerun()

        st.text_area(
            "SMS message",
            key="bundle_only_sms_text",
            height=140,
        )

    with sms_col2:
        st.text_input(
            "SMS mobile",
            value=normalize_mobile_au(fields.get("phone", "")),
            disabled=True,
        )

        if st.button("Send SMS", use_container_width=True):
            try:
                mobile = normalize_mobile_au(fields.get("phone", ""))
                message = clean_text(st.session_state.get("bundle_only_sms_text", ""))

                if not mobile:
                    raise ValueError("No mobile number found.")
                if not message:
                    raise ValueError("SMS message is blank.")

                message_id = messagemedia_send_message(mobile, message)
                st.session_state["bundle_only_sms_status"] = f"Sent ({message_id})"
                st.success(f"SMS sent: {message_id}")
            except Exception as e:
                st.session_state["bundle_only_sms_status"] = f"Failed ({e})"
                st.error(f"SMS failed: {e}")

        st.text_input(
            "SMS status",
            value=st.session_state.get("bundle_only_sms_status", ""),
            disabled=True,
        )
else:
    st.info("Upload a sales order PDF to begin.")