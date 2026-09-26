import os
import re
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from loguru import logger

try:
    import pymupdf as fitz
except ImportError:
    import fitz


class PDFDocumentType(str, Enum):
    DIGITAL_TEXT = "digital_text"          # Scientific papers, Word PDF exports, SOPs with selectable text
    FLATTENED_DESIGN = "flattened_design"  # PowerPoint / Canva Print-to-PDF, product brochures, catalogs
    SCANNED_IMAGE = "scanned_image"        # Physical scanner/camera, 1 full-page raster bitmap
    HYBRID = "hybrid"                      # Mixed pages (some text, some scanned)


class PDFAnalysisResult(BaseModel):
    file_name: str
    page_count: int
    total_pure_chars: int
    text_density: float          # avg pure text chars per page
    pages_with_fonts: int
    font_presence_ratio: float   # ratio of sample pages that contain digital font streams
    total_images: int
    avg_images_per_page: float
    total_drawings: int
    avg_drawings_per_page: float
    pdf_type: PDFDocumentType
    analysis_details: str


def clean_extracted_text(text: Optional[str]) -> str:
    """
    Removes markdown image tags, URLs, and HTML tags to calculate
    pure knowledge text content. Prevents image URL strings from
    being counted as knowledge text characters.
    """
    if not text:
        return ""
    # 1. Strip markdown image tags ![alt](url)
    cleaned = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 2. Strip standalone URLs
    cleaned = re.sub(r'https?://\S+|/api/storage/\S+', '', cleaned)
    # 3. Strip HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    return cleaned.strip()


def analyze_pdf_complexity(doc: fitz.Document, file_path: str = "") -> PDFAnalysisResult:
    """
    Lightweight document-level PDF complexity analyzer (< 20ms).
    Evaluates pure text characters, font existence, embedded image objects,
    and vector drawing paths across document sample pages to classify
    the PDF into DIGITAL_TEXT, FLATTENED_DESIGN, SCANNED_IMAGE, or HYBRID.
    """
    page_count = len(doc)
    sample_size = min(page_count, 5)
    sample_pages = doc[:sample_size]

    total_pure_chars = 0
    pages_with_fonts = 0
    pages_with_text = 0
    total_images = 0
    total_drawings = 0

    for page in sample_pages:
        raw_text = page.get_text("text") or ""
        pure = clean_extracted_text(raw_text)
        pure_len = len(pure)
        total_pure_chars += pure_len
        if pure_len > 30:
            pages_with_text += 1

        fonts = page.get_fonts()
        if fonts and len(fonts) > 0:
            pages_with_fonts += 1

        total_images += len(page.get_images(full=True))
        total_drawings += len(page.get_drawings())

    avg_chars = total_pure_chars / max(1, sample_size)
    font_ratio = pages_with_fonts / max(1, sample_size)
    avg_images = total_images / max(1, sample_size)
    avg_drawings = total_drawings / max(1, sample_size)

    # Document-Level Decision Logic
    # 1. DIGITAL_TEXT: High text density and digital fonts present
    if font_ratio >= 0.5 and avg_chars >= 80:
        pdf_type = PDFDocumentType.DIGITAL_TEXT
        details = f"Digital Text PDF: avg_chars={avg_chars:.1f}, font_ratio={font_ratio:.2f}"

    # 2. FLATTENED_DESIGN: Negligible/zero text or no fonts, but multiple graphics/drawings
    elif (font_ratio < 0.2 or avg_chars < 50) and (avg_images >= 2 or avg_drawings > 30):
        pdf_type = PDFDocumentType.FLATTENED_DESIGN
        details = (
            f"Flattened Design PDF: avg_chars={avg_chars:.1f}, font_ratio={font_ratio:.2f}, "
            f"avg_images={avg_images:.1f}, avg_drawings={avg_drawings:.1f}"
        )

    # 3. SCANNED_IMAGE: Negligible/zero text, 0-1 bitmap per page, minimal/no drawings
    elif (font_ratio < 0.2 or avg_chars < 50) and avg_drawings <= 10 and avg_images <= 1.5:
        pdf_type = PDFDocumentType.SCANNED_IMAGE
        details = (
            f"Scanned Image PDF: avg_chars={avg_chars:.1f}, font_ratio={font_ratio:.2f}, "
            f"avg_images={avg_images:.1f}"
        )

    # 4. HYBRID: Some text pages, some image-only pages
    elif 0 < pages_with_text < sample_size:
        pdf_type = PDFDocumentType.HYBRID
        details = f"Hybrid PDF: {pages_with_text}/{sample_size} pages have text"

    # Fallback
    elif total_pure_chars >= 50:
        pdf_type = PDFDocumentType.DIGITAL_TEXT
        details = f"Fallback Digital Text: total_chars={total_pure_chars}"
    else:
        pdf_type = PDFDocumentType.FLATTENED_DESIGN
        details = "Fallback Flattened Design (no selectable text detected)"

    file_name = os.path.basename(file_path) if file_path else "unknown.pdf"
    logger.info(f"📑 [PDF-ANALYZER] {file_name} -> {pdf_type.value} ({details})")

    return PDFAnalysisResult(
        file_name=file_name,
        page_count=page_count,
        total_pure_chars=total_pure_chars,
        text_density=avg_chars,
        pages_with_fonts=pages_with_fonts,
        font_presence_ratio=font_ratio,
        total_images=total_images,
        avg_images_per_page=avg_images,
        total_drawings=total_drawings,
        avg_drawings_per_page=avg_drawings,
        pdf_type=pdf_type,
        analysis_details=details
    )
