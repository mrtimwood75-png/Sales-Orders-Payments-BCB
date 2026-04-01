import streamlit as st
from pathlib import Path

APP_TITLE = "Salesorder & Quote Apps"
BASE_DIR = Path(__file__).resolve().parent


def resolve_logo_path():
    candidates = [
        BASE_DIR / "assets" / "boconcept_logo.png",
        BASE_DIR / "assets" / "boconcept_logo.PNG",
        BASE_DIR / "assets" / "BoConcept_logo.png",
        BASE_DIR / "assets" / "BoConcept_logo.PNG",
        BASE_DIR / "assets" / "boconcept_logo.jpg",
        BASE_DIR / "assets" / "boconcept_logo.jpeg",
        BASE_DIR / "assets" / "BoConcept_logo.jpg",
        BASE_DIR / "assets" / "BoConcept_logo.jpeg",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


LOGO_PATH = resolve_logo_path()

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    """
    <style>
        header[data-testid="stHeader"] {
            display: none;
        }

        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1280px;
        }

        .app-card {
            border: 1px solid #D9D9D9;
            border-radius: 14px;
            padding: 22px 20px;
            background: #FFFFFF;
            box-shadow: 0 2px 10px rgba(0,0,0,0.04);
            min-height: 190px;
        }

        .app-title {
            font-size: 1.15rem;
            font-weight: 600;
            margin-bottom: 0.35rem;
            color: #111111;
        }

        .app-text {
            font-size: 0.95rem;
            color: #4A4A4A;
            margin-bottom: 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

if LOGO_PATH:
    logo_col, _ = st.columns([1.2, 4.8])
    with logo_col:
        st.image(str(LOGO_PATH), width=220)

st.title(APP_TITLE)
st.write("Choose an app below.")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        """
        <div class="app-card">
            <div class="app-title">Add Stripe Payment Link</div>
            <div class="app-text">Upload a sales order PDF, create a Stripe checkout link, apply a payment button to the PDF, send the link by SMS, and bundle attachments into one PDF.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Add Stripe Payment Link", use_container_width=True, key="open_sales_order_modifier"):
        st.switch_page("pages/sales_order_modifier.py")

with col2:
    st.markdown(
        """
        <div class="app-card">
            <div class="app-title">Add Logo & Bundle Attachments</div>
            <div class="app-text">Upload a sales order PDF, stamp the BoConcept logo, and bundle attachments without generating any Stripe link.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Add Logo & Bundle Attachments", use_container_width=True, key="open_bundle_attachments"):
        st.switch_page("pages/bundle_attachments.py")

with col3:
    st.markdown(
        """
        <div class="app-card">
            <div class="app-title">Manual Entry Checkout</div>
            <div class="app-text">Enter order details manually, generate a Stripe checkout link, and send the link to the customer by SMS.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Manual Entry Checkout", use_container_width=True, key="open_manual_entry_checkout"):
        st.switch_page("pages/manual_entry_checkout.py")