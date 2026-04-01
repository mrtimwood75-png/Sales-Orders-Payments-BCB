import re
from pathlib import Path

import streamlit as st

try:
    import fitz
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
    ]
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


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


def parse_sales_order_customer_name(pdf_bytes):
    if fitz is None:
        return ""

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        first_page = doc[0].get_text("text") if doc.page_count else ""
        doc.close()
    except Exception:
        return ""

    lines = [clean_text(x) for x in first_page.splitlines() if clean_text(x)]
    for line in lines[:12]:
        if not re.search(
            r"sales order|date|phone|email|misc\. charges|gst|total|prepayment|balance due",
            line,
            re.IGNORECASE,
        ):
            return line
    return ""


def stamp_main_pdf_bytes(pdf_bytes, logo_path):
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


def build_single_bundle_pdf_bytes(main_pdf_bytes, attachments, logo_path):
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed")

    stamped_main_bytes = stamp_main_pdf_bytes(main_pdf_bytes, logo_path)

    final_doc = fitz.open()

    main_doc = fitz.open(stream=stamped_main_bytes, filetype="pdf")
    final_doc.insert_pdf(main_doc)
    main_doc.close()

    for att in attachments:
        append_file_bytes_to_pdf(final_doc, att["name"], att["bytes"])

    output = final_doc.tobytes(garbage=4, deflate=True)
    final_doc.close()
    return output


def safe_filename(value, fallback="customer"):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


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
        st.session_state["bundle_only_customer_name"] = parse_sales_order_customer_name(pdf_bytes)
        initialise_default_attachments()

if st.session_state.get("bundle_only_order_pdf_bytes"):
    st.text_input("Customer", value=st.session_state.get("bundle_only_customer_name", ""), disabled=True)

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

            for up in extra_files:
                st.session_state["bundle_only_attachments"].append(
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

    attachments = st.session_state.get("bundle_only_attachments", [])

    file_count = len(attachments) + 1
    if a2.button(
        f"Download PDF ({file_count} files)",
        use_container_width=True,
        disabled=not st.session_state.get("bundle_only_order_pdf_bytes"),
    ):
        try:
            customer_file_part = safe_filename(st.session_state.get("bundle_only_customer_name", ""), "customer")
            bundle_name = f"{customer_file_part}.pdf"

            bundle_bytes = build_single_bundle_pdf_bytes(
                main_pdf_bytes=st.session_state["bundle_only_order_pdf_bytes"],
                attachments=attachments,
                logo_path=LOGO_PATH,
            )

            st.download_button(
                "Download PDF",
                data=bundle_bytes,
                file_name=bundle_name,
                mime="application/pdf",
                use_container_width=True,
                key=f"bundle_only_download_{bundle_name}_{len(bundle_bytes)}",
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
                if r3.button("Remove", key=f"bundle_only_remove_att_{i}"):
                    attachments.pop(i - 1)
                    st.session_state["bundle_only_attachments"] = attachments
                    st.rerun()
else:
    st.info("Upload a sales order PDF to begin.")