import os
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
import streamlit as st

try:
    import stripe
except Exception:
    stripe = None


APP_TITLE = "Manual Entry Checkout"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

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
    for path in candidates:
        if path.exists():
            return path
    return None


LOGO_PATH = resolve_logo_path()


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


def parse_numeric_input(text, fallback=0.0):
    try:
        return float(str(text).replace(",", "").strip() or 0)
    except Exception:
        return float(fallback)


def format_money(value):
    return f"${float(value or 0):,.2f}"


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


def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default


def reset_diag():
    st.session_state.manual_notification_diag = []


def add_diag(label, value):
    if "manual_notification_diag" not in st.session_state:
        st.session_state.manual_notification_diag = []
    st.session_state.manual_notification_diag.append((label, value))


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
    return api_key, api_secret, sender, base_url.rstrip("/") + "/messages"


def messagemedia_send_message(to_mobile, message, debug=False):
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

    if debug:
        add_diag("Sinch MessageMedia URL", url)
        add_diag("HTTP status", resp.status_code)
        add_diag("Response body", resp.text)
        add_diag("Payload", payload)

    resp.raise_for_status()
    body = resp.json()
    messages = body.get("messages") or []
    if not messages:
        return resp.text.strip()
    return str(messages[0].get("message_id") or resp.text.strip())


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


def init_state():
    defaults = {
        "manual_customer_name": "",
        "manual_customer_email": "",
        "manual_phone": "",
        "manual_sales_order": "",
        "manual_order_date": "",
        "manual_total_amount": 0.0,
        "manual_prepayment": 0.0,
        "manual_balance_due": 0.0,
        "manual_payment_mode": "balance",
        "manual_payment_amount": 0.0,
        "manual_payment_label": "Pay Balance Now",
        "manual_payment_link": "",
        "manual_stripe_session_id": "",
        "manual_notification_diag": [],
        "manual_templates": default_templates(),
        "manual_template_name": "Standard payment request",
        "manual_new_template_name": "",
        "manual_template_text": default_templates()["Standard payment request"],
        "manual_sms_status": "",
        "manual_sms_confirm_open": False,
        "manual_sms_confirm_name": "",
        "manual_sms_confirm_phone": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


st.set_page_config(page_title=APP_TITLE, layout="wide")
init_state()

top_nav_left, top_nav_right = st.columns([1, 5])
with top_nav_left:
    if st.button("Home", use_container_width=True):
        st.switch_page("main.py")
with top_nav_right:
    if LOGO_PATH:
        st.image(str(LOGO_PATH), width=220)

st.title(APP_TITLE)

if STRIPE_SECRET_KEY:
    st.caption("Stripe configured")
else:
    st.warning("Stripe secret missing.")

with st.form("manual_entry_form"):
    col_a, col_b, col_c = st.columns([24, 41, 35])
    customer_name = col_a.text_input("Customer", value=st.session_state["manual_customer_name"])
    customer_email = col_b.text_input("Email", value=st.session_state["manual_customer_email"])
    phone = col_c.text_input("Phone", value=st.session_state["manual_phone"])

    col_d, col_e, _row2_spacer = st.columns([20, 18, 62])
    sales_order = col_d.text_input("Sales order", value=st.session_state["manual_sales_order"])
    payment_amount = col_e.text_input("Payment amount", value=f"{float(st.session_state['manual_payment_amount']):.2f}")

    b1, b2, _button_spacer = st.columns([18, 18, 64])
    save_clicked = b1.form_submit_button("Apply Changes")
    create_link_clicked = b2.form_submit_button("Create Stripe Link")

if save_clicked:
    parsed_payment_amount = parse_numeric_input(payment_amount, st.session_state["manual_payment_amount"])
    if parsed_payment_amount < 0:
        parsed_payment_amount = 0.0

    st.session_state["manual_customer_name"] = customer_name
    st.session_state["manual_customer_email"] = customer_email
    st.session_state["manual_phone"] = normalize_mobile_au(phone)
    st.session_state["manual_sales_order"] = sales_order
    st.session_state["manual_payment_amount"] = parsed_payment_amount
    st.session_state["manual_payment_mode"] = "balance"
    st.session_state["manual_payment_label"] = "Pay Now"
    st.success("Changes applied")
    st.rerun()

if create_link_clicked:
    try:
        parsed_payment_amount = parse_numeric_input(payment_amount, st.session_state["manual_payment_amount"])
        if parsed_payment_amount <= 0:
            raise RuntimeError("Payment amount must be greater than 0")

        st.session_state["manual_customer_name"] = customer_name
        st.session_state["manual_customer_email"] = customer_email
        st.session_state["manual_phone"] = normalize_mobile_au(phone)
        st.session_state["manual_sales_order"] = sales_order
        st.session_state["manual_payment_mode"] = "balance"
        st.session_state["manual_payment_amount"] = parsed_payment_amount
        st.session_state["manual_payment_label"] = "Pay Now"

        link_result = create_stripe_checkout_link(
            customer_name=customer_name,
            customer_email=customer_email,
            sales_order=sales_order,
            amount=parsed_payment_amount,
            payment_label="Pay Now",
            phone=phone,
        )

        st.session_state["manual_payment_link"] = link_result["url"]
        st.session_state["manual_stripe_session_id"] = link_result["session_id"]
        st.session_state["manual_sms_status"] = ""

        st.success("Stripe payment link created")
        st.code(link_result["url"])
        st.rerun()
    except Exception as e:
        st.error(str(e))

if st.session_state["manual_payment_amount"] > 0:
    st.caption(f"Payment amount: {format_money(st.session_state['manual_payment_amount'])}")

if st.session_state["manual_payment_link"]:
    st.text_input("Payment link", value=st.session_state["manual_payment_link"], disabled=True)

st.markdown("---")
st.subheader("SMS Templates")

templates = st.session_state["manual_templates"]
template_names = list(templates.keys())

selected_template = st.selectbox(
    "Template",
    template_names,
    index=template_names.index(st.session_state["manual_template_name"])
    if st.session_state["manual_template_name"] in template_names else 0,
)

if selected_template != st.session_state["manual_template_name"]:
    st.session_state["manual_template_name"] = selected_template
    st.session_state["manual_template_text"] = templates[selected_template]
    st.rerun()

st.session_state["manual_template_text"] = st.text_area(
    "Template text",
    value=st.session_state["manual_template_text"],
    height=120,
    help="Placeholders: {customer_name}, {order_number}, {payment_amount}, {stripe_checkout_url}, {mobile}",
)

st.session_state["manual_templates"][st.session_state["manual_template_name"]] = st.session_state["manual_template_text"]

t1, t2, t3 = st.columns([2, 1, 1])

with t1:
    st.session_state["manual_new_template_name"] = st.text_input(
        "New template name",
        value=st.session_state["manual_new_template_name"],
    )

with t2:
    if st.button("Add Template", use_container_width=True):
        new_name = st.session_state["manual_new_template_name"].strip()
        if not new_name:
            st.error("Enter a template name.")
        elif new_name in st.session_state["manual_templates"]:
            st.error("A template with that name already exists.")
        else:
            st.session_state["manual_templates"][new_name] = (
                "Hi {customer_name}, payment for order {order_number} is now due. "
                "Amount payable: {payment_amount}. Please pay securely here: {stripe_checkout_url}"
            )
            st.session_state["manual_template_name"] = new_name
            st.session_state["manual_template_text"] = st.session_state["manual_templates"][new_name]
            st.session_state["manual_new_template_name"] = ""
            st.rerun()

with t3:
    if st.button("Delete Template", use_container_width=True):
        current = st.session_state["manual_template_name"]
        if len(st.session_state["manual_templates"]) == 1:
            st.error("At least one template must remain.")
        else:
            del st.session_state["manual_templates"][current]
            remaining = list(st.session_state["manual_templates"].keys())
            st.session_state["manual_template_name"] = remaining[0]
            st.session_state["manual_template_text"] = st.session_state["manual_templates"][remaining[0]]
            st.rerun()

st.caption("Available placeholders: {customer_name}, {order_number}, {payment_amount}, {stripe_checkout_url}, {mobile}")

preview_payload = {
    "customer_name": st.session_state["manual_customer_name"],
    "order_number": st.session_state["manual_sales_order"],
    "payment_amount": st.session_state["manual_payment_amount"],
    "stripe_checkout_url": st.session_state["manual_payment_link"],
    "mobile": st.session_state["manual_phone"],
}

if st.session_state["manual_payment_link"]:
    st.text_area(
        "SMS Preview",
        value=build_sms_message(preview_payload, st.session_state["manual_template_text"]),
        height=110,
        disabled=True,
    )

if True:
    if st.button("Send SMS to Customer", use_container_width=True):
        if not st.session_state["manual_payment_link"]:
            st.error("Create the Stripe payment link first.")
        elif not normalize_mobile_au(st.session_state["manual_phone"]):
            st.error("Customer phone is required.")
        else:
            st.session_state["manual_sms_confirm_name"] = st.session_state["manual_customer_name"]
            st.session_state["manual_sms_confirm_phone"] = normalize_mobile_au(st.session_state["manual_phone"])
            st.session_state["manual_sms_confirm_open"] = True


if st.session_state["manual_sms_confirm_open"]:
    with st.container(border=True):
        st.warning(
            f"About to send SMS to {st.session_state['manual_sms_confirm_name']} "
            f"({st.session_state['manual_sms_confirm_phone']})."
        )
        c1, c2 = st.columns(2)
        if c1.button("Confirm Send SMS", use_container_width=True):
            try:
                phone_value = normalize_mobile_au(st.session_state["manual_phone"])
                link_value = str(st.session_state["manual_payment_link"]).strip()

                if not phone_value:
                    raise RuntimeError("Customer phone is required.")
                if not link_value:
                    raise RuntimeError("Create the Stripe payment link first.")
                if float(st.session_state["manual_payment_amount"] or 0) <= 0:
                    raise RuntimeError("Payment amount must be greater than 0.")

                reset_diag()
                sms_message = build_sms_message(
                    {
                        "customer_name": st.session_state["manual_customer_name"],
                        "order_number": st.session_state["manual_sales_order"],
                        "payment_amount": st.session_state["manual_payment_amount"],
                        "stripe_checkout_url": st.session_state["manual_payment_link"],
                        "mobile": phone_value,
                    },
                    st.session_state["manual_template_text"],
                )
                message_id = messagemedia_send_message(phone_value, sms_message, debug=True)
                st.session_state["manual_sms_status"] = f"Sent ({message_id})"
                st.session_state["manual_sms_confirm_open"] = False
                st.success(f"SMS sent: {message_id}")
            except Exception as e:
                st.session_state["manual_sms_status"] = f"Failed ({e})"
                st.session_state["manual_sms_confirm_open"] = False
                st.error(str(e))
        if c2.button("Cancel", use_container_width=True):
            st.session_state["manual_sms_confirm_open"] = False
            st.rerun()

if st.session_state["manual_sms_status"]:
    st.text_input("SMS Status", value=st.session_state["manual_sms_status"], disabled=True)

with st.expander("Diagnostics"):
    if st.session_state["manual_notification_diag"]:
        for label, value in st.session_state["manual_notification_diag"]:
            st.write(f"**{label}:** {value}")