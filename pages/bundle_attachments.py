import io
import os
from pathlib import Path
from typing import List, Tuple

import streamlit as st
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


st.set_page_config(page_title="Logo and Bundle PDF App", layout="wide")


APP_TITLE = "Logo and Bundle PDF App"
DEFAULT_TERMS_FILENAMES = [
    "Terms & Conditions.pdf",
    "Terms and Conditions.pdf",
    "terms_and_conditions.pdf",
]


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def safe_filename(value: str) -> str:
    value = (value or "customer").strip().lower()
    cleaned = []
    for ch in value:
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in (" ", "-", "_"):
            cleaned.append("-")
    out = "".join(cleaned)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "customer"


def find_default_terms_file() -> Path | None:
    here = Path(".")
    for name in DEFAULT_TERMS_FILENAMES:
        p = here / name
        if p.exists() and p.is_file():
            return p
    return None


def create_cover_page_pdf(doc_type: str, customer_name: str, logo_bytes: bytes | None) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    if logo_bytes:
        try:
            img = Image.open(io.BytesIO(logo_bytes))
            img_width, img_height = img.size
            max_width = 180
            max_height = 80
            scale = min(max_width / img_width, max_height / img_height, 1)
            draw_w = img_width * scale
            draw_h = img_height * scale
            c.drawImage(
                ImageReader(img),
                56,
                height - 72 - draw_h,
                width=draw_w,
                height=draw_h,
                mask="auto",
            )
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 28)
    c.setFillColorRGB(0.07, 0.09, 0.15)
    c.drawString(56, height - 190, doc_type)

    c.setFont("Helvetica", 16)
    c.setFillColorRGB(0.27, 0.31, 0.36)
    c.drawString(56, height - 230, customer_name or "Customer")

    c.setStrokeColorRGB(0.86, 0.88, 0.90)
    c.setLineWidth(1)
    c.line(56, height - 252, width - 56, height - 252)

    c.setFont("Helvetica-Bold", 13)
    c.setFillColorRGB(0.07, 0.09, 0.15)
    c.drawString(56, height - 290, "Combined file bundle")

    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.42, 0.46, 0.50)
    c.drawString(56, height - 315, "Generated from Streamlit app")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def image_to_pdf_bytes(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    page_w, page_h = A4
    margin = 32
    max_w = page_w - margin * 2
    max_h = page_h - margin * 2

    img_w, img_h = img.size
    scale = min(max_w / img_w, max_h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    c.drawImage(ImageReader(img), x, y, width=draw_w, height=draw_h, mask="auto")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def append_pdf_bytes(writer: PdfWriter, pdf_bytes: bytes) -> None:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for page in reader.pages:
        writer.add_page(page)


def combine_bundle(
    doc_type: str,
    customer_name: str,
    logo_bytes: bytes | None,
    ordered_items: List[Tuple[str, bytes, str]],
) -> bytes:
    writer = PdfWriter()

    cover_pdf = create_cover_page_pdf(doc_type, customer_name, logo_bytes)
    append_pdf_bytes(writer, cover_pdf)

    for _, file_bytes, file_type in ordered_items:
        if file_type == "pdf":
            append_pdf_bytes(writer, file_bytes)
        elif file_type == "image":
            image_pdf = image_to_pdf_bytes(file_bytes)
            append_pdf_bytes(writer, image_pdf)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()


def init_state():
    if "bundle_items" not in st.session_state:
        st.session_state.bundle_items = []
    if "doc_type" not in st.session_state:
        st.session_state.doc_type = "Confirmation"


def add_uploaded_file(name: str, data: bytes, kind: str):
    existing_keys = {item["key"] for item in st.session_state.bundle_items}
    key = f"{name}-{len(data)}-{kind}"
    if key in existing_keys:
        return
    st.session_state.bundle_items.append(
        {
            "key": key,
            "name": name,
            "bytes": data,
            "type": kind,
            "size": len(data),
        }
    )


def move_item_up(idx: int):
    if idx <= 0:
        return
    items = st.session_state.bundle_items
    items[idx - 1], items[idx] = items[idx], items[idx - 1]


def move_item_down(idx: int):
    items = st.session_state.bundle_items
    if idx >= len(items) - 1:
        return
    items[idx + 1], items[idx] = items[idx], items[idx + 1]


def remove_item(idx: int):
    st.session_state.bundle_items.pop(idx)


init_state()

st.title(APP_TITLE)

left, right = st.columns([1.1, 0.9], gap="large")

with left:
    customer_name = st.text_input("Customer", placeholder="Enter customer name")

    st.session_state.doc_type = st.segmented_control(
        "Document type",
        options=["Confirmation", "Invoice"],
        default=st.session_state.doc_type,
        selection_mode="single",
    ) or "Confirmation"

    sales_order_pdf = st.file_uploader(
        "Upload sales order PDF",
        type=["pdf"],
        accept_multiple_files=False,
        key="sales_order_pdf",
    )

    extra_files = st.file_uploader(
        "Upload extra PDF or image files",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="extra_files",
    )

    logo_file = st.file_uploader(
        "Upload logo",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=False,
        key="logo_file",
    )

    if st.button("Add files to bundle", use_container_width=True):
        if sales_order_pdf is not None:
            add_uploaded_file(sales_order_pdf.name, sales_order_pdf.getvalue(), "pdf")

        if extra_files:
            for f in extra_files:
                ext = f.name.lower().split(".")[-1]
                kind = "pdf" if ext == "pdf" else "image"
                add_uploaded_file(f.name, f.getvalue(), kind)

        default_terms = find_default_terms_file()
        if default_terms is not None:
            already_present = any(
                item["name"] == default_terms.name for item in st.session_state.bundle_items
            )
            if not already_present:
                add_uploaded_file(default_terms.name, default_terms.read_bytes(), "pdf")

        st.success("Files added to bundle.")

    st.subheader("Bundle order")

    if not st.session_state.bundle_items:
        st.info("No files added yet.")
    else:
        for idx, item in enumerate(st.session_state.bundle_items):
            row = st.columns([0.08, 0.58, 0.12, 0.11, 0.11])
            row[0].write(f"{idx + 1}.")
            row[1].write(f"**{item['name']}**  \n{format_size(item['size'])}")
            if row[2].button("↑", key=f"up_{item['key']}", use_container_width=True):
                move_item_up(idx)
                st.rerun()
            if row[3].button("↓", key=f"down_{item['key']}", use_container_width=True):
                move_item_down(idx)
                st.rerun()
            if row[4].button("✕", key=f"del_{item['key']}", use_container_width=True):
                remove_item(idx)
                st.rerun()

    col_a, col_b = st.columns(2)
    if col_a.button("Reset bundle", use_container_width=True):
        st.session_state.bundle_items = []
        st.rerun()

    doc_type = st.session_state.doc_type
    output_name = f"{safe_filename(customer_name)}-{doc_type.lower()}.pdf"

    if st.session_state.bundle_items:
        combined_pdf_bytes = combine_bundle(
            doc_type=doc_type,
            customer_name=customer_name,
            logo_bytes=logo_file.getvalue() if logo_file else None,
            ordered_items=[
                (item["name"], item["bytes"], item["type"])
                for item in st.session_state.bundle_items
            ],
        )

        col_b.download_button(
            "Combine & download PDF",
            data=combined_pdf_bytes,
            file_name=output_name,
            mime="application/pdf",
            use_container_width=True,
        )

with right:
    st.subheader("Preview")
    st.markdown(f"## {st.session_state.doc_type}")
    st.write(customer_name or "Customer name")
    st.caption(f"{len(st.session_state.bundle_items)} bundled file(s)")

    st.markdown("### Included files")
    if not st.session_state.bundle_items:
        st.write("Your bundled files will appear here.")
    else:
        for idx, item in enumerate(st.session_state.bundle_items, start=1):
            st.write(f"{idx}. {item['name']} — {format_size(item['size'])}")

    st.markdown("### Logo")
    if logo_file:
        st.write(logo_file.name)
        try:
            st.image(logo_file.getvalue(), width=220)
        except Exception:
            pass
    else:
        st.write("No logo uploaded")