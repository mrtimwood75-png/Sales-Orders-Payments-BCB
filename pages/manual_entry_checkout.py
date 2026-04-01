import os
from pathlib import Path

import requests
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


def directsms_connect(debug=False):
    username = get_secret("DIRECTSMS_USERNAME")
    password = get_secret("DIRECTSMS_PASSWORD")

    if not username or not password:
        raise ValueError("Missing DIRECTSMS_USERNAME or DIRECTSMS_PASSWORD in Streamlit secrets.")

    url = "https://api.directsms.com.au/s3/http/connect"
    resp = requests.post(
        url,
        data={"username": username, "password": password},
        timeout=30,
    )

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


def directsms_get_balance(debug=False):
    connectionid = directsms_connect(debug=debug)
    url = "https://api.directsms.com.au/s3/http/get_balance"

    resp = requests.post(url, data={"connectionid": connectionid}, timeout=30)

    if debug:
        add_diag("Balance URL", url)
        add_diag("Balance HTTP status", resp.status_code)
        add_diag("Balance response body", resp.text)

    resp.raise_for_status()
    text = resp.text.strip()

    if text.lower().startswith("err:"):
        raise ValueError(text)

    return text


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

current_total_for_options = float(st.session_state["manual_total_amount"] or 0.0)
payment_options = ["balance"] if current_total_for_options <= 0 else ["balance", "deposit"]
current_mode = st.session_state["manual_payment_mode"]
if current_mode not in payment_options:
    current_mode = "balance"

with st.form("manual_entry_form"):
    col_a, col_b, col_c = st.columns(3)
    customer_name = col_a.text_input("Customer", value=st.session_state["manual_customer_name"])
    customer_email = col_b.text_input("Email", value=st.session_state["manual_customer_email"])
    phone = col_c.text_input("Phone", value=st.session_state["manual_phone"])

    col_d, col_e, col_f = st.columns(3)
    sales_order = col_d.text_input("Sales order", value=st.session_state["manual_sales_order"])
    order_date = col_e.text_input("Order date", value=st.session_state["manual_order_date"])
    payment_choice = col_f.radio(
        "Payment type",
        options=payment_options,
        index=payment_options.index(current_mode),
        format_func=lambda x: "Balance" if x == "balance" else "Deposit 50%",
        horizontal=True,
    )

    col_g, col_h, col_i, col_j = st.columns(4)
    total_amount = col_g.text_input("Total", value=f"{float(st.session_state['manual_total_amount']):.2f}")
    prepayment = col_h.text_input("Prepayment", value=f"{float(st.session_state['manual_prepayment']):.2f}")
    col_i.text_input("Balance due", value=f"{float(st.session_state['manual_balance_due']):.2f}", disabled=True)
    col_j.text_input("Payment amount", value=f"{float(st.session_state['manual_payment_amount']):.2f}", disabled=True)

    if float(st.session_state["manual_total_amount"] or 0) <= 0:
        st.caption("Deposit 50% becomes available once Total is greater than 0.")

    b1, b2 = st.columns(2)
    save_clicked = b1.form_submit_button("Apply Changes")
    create_link_clicked = b2.form_submit_button("Create Stripe Link")

if save_clicked:
    parsed_total_amount = parse_numeric_input(total_amount, st.session_state["manual_total_amount"])
    parsed_prepayment = parse_numeric_input(prepayment, st.session_state["manual_prepayment"])
    parsed_balance_due = round(parsed_total_amount - parsed_prepayment, 2)
    if parsed_balance_due < 0:
        parsed_balance_due = 0.0

    effective_choice = payment_choice if parsed_total_amount > 0 else "balance"
    payment_calc = payment_choice_to_values(effective_choice, parsed_total_amount, parsed_balance_due)

    st.session_state["manual_customer_name"] = customer_name
    st.session_state["manual_customer_email"] = customer_email
    st.session_state["manual_phone"] = normalize_mobile_au(phone)
    st.session_state["manual_sales_order"] = sales_order
    st.session_state["manual_order_date"] = order_date
    st.session_state["manual_total_amount"] = parsed_total_amount
    st.session_state["manual_prepayment"] = parsed_prepayment
    st.session_state["manual_balance_due"] = parsed_balance_due
    st.session_state["manual_payment_mode"] = payment_calc["payment_mode"]
    st.session_state["manual_payment_amount"] = payment_calc["payment_amount"]
    st.session_state["manual_payment_label"] = payment_calc["payment_label"]
    st.success("Changes applied")
    st.rerun()

if create_link_clicked:
    try:
        parsed_total_amount = parse_numeric_input(total_amount, st.session_state["manual_total_amount"])
        parsed_prepayment = parse_numeric_input(prepayment, st.session_state["manual_prepayment"])
        parsed_balance_due = round(parsed_total_amount - parsed_prepayment, 2)
        if parsed_balance_due < 0:
            parsed_balance_due = 0.0

        effective_choice = payment_choice if parsed_total_amount > 0 else "balance"
        payment_calc = payment_choice_to_values(effective_choice, parsed_total_amount, parsed_balance_due)

        st.session_state["manual_customer_name"] = customer_name
        st.session_state["manual_customer_email"] = customer_email
        st.session_state["manual_phone"] = normalize_mobile_au(phone)
        st.session_state["manual_sales_order"] = sales_order
        st.session_state["manual_order_date"] = order_date
        st.session_state["manual_total_amount"] = parsed_total_amount
        st.session_state["manual_prepayment"] = parsed_prepayment
        st.session_state["manual_balance_due"] = parsed_balance_due
        st.session_state["manual_payment_mode"] = payment_calc["payment_mode"]
        st.session_state["manual_payment_amount"] = payment_calc["payment_amount"]
        st.session_state["manual_payment_label"] = payment_calc["payment_label"]

        link_result = create_stripe_checkout_link(
            customer_name=customer_name,
            customer_email=customer_email,
            sales_order=sales_order,
            amount=payment_calc["payment_amount"],
            payment_label=payment_calc["payment_label"],
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
    st.caption(
        f"{st.session_state['manual_payment_label']}  |  "
        f"Balance due: {format_money(st.session_state['manual_balance_due'])}  |  "
        f"Payment amount: {format_money(st.session_state['manual_payment_amount'])}"
    )

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

sms_col1, sms_col2 = st.columns([1, 1])

with sms_col1:
    if st.button("Send SMS to Customer", use_container_width=True):
        if not st.session_state["manual_payment_link"]:
            st.error("Create the Stripe payment link first.")
        elif not normalize_mobile_au(st.session_state["manual_phone"]):
            st.error("Customer phone is required.")
        else:
            st.session_state["manual_sms_confirm_name"] = st.session_state["manual_customer_name"]
            st.session_state["manual_sms_confirm_phone"] = normalize_mobile_au(st.session_state["manual_phone"])
            st.session_state["manual_sms_confirm_open"] = True

with sms_col2:
    test_balance_clicked = st.button("Test SMS Balance", use_container_width=True)

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
                message_id = directsms_send_message(phone_value, sms_message, debug=True)
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

if test_balance_clicked:
    try:
        reset_diag()
        balance_result = directsms_get_balance(debug=True)
        st.success(f"directSMS balance response: {balance_result}")
    except Exception as e:
        st.error(str(e))

if st.session_state["manual_sms_status"]:
    st.text_input("SMS Status", value=st.session_state["manual_sms_status"], disabled=True)

with st.expander("Diagnostics"):
    if st.session_state["manual_notification_diag"]:
        for label, value in st.session_state["manual_notification_diag"]:
            st.write(f"**{label}:** {value}")