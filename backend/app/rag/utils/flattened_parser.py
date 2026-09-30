import os
import re
import time
from typing import List, Dict, Any, Optional
from loguru import logger

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from rapidocr.utils.typings import EngineType
from rapidocr.main import RapidOCR

from app.rag.utils.spatial_associator import SpatialImageTextAssociator
from app.rag.canonical import PDFContext, ImageDisplayPolicy, ImageProvenance
from app.services.storage import upload_image


import threading

_GLOBAL_OCR_LOCK = threading.Lock()
_SHARED_RAPID_OCR = None


def get_shared_rapid_ocr() -> RapidOCR:
    global _SHARED_RAPID_OCR
    if _SHARED_RAPID_OCR is None:
        logger.info("Initializing Shared RapidOCR instance (PyTorch CPU)...")
        params = {
            "Det.engine_type": EngineType.TORCH,
            "Cls.engine_type": EngineType.TORCH,
            "Rec.engine_type": EngineType.TORCH,
        }
        _SHARED_RAPID_OCR = RapidOCR(params=params)
    return _SHARED_RAPID_OCR


class FlattenedDesignParser:
    """
    Specialized, lightweight parser for FLATTENED_DESIGN_PDF and SCANNED_IMAGE_PDF.
    Uses PyMuPDF rendering (150 DPI) + RapidOCR (PyTorch CPU backend) + Spatial Image Association.
    Executes in ~10-15s per page with < 250MB RAM footprint (preventing heavy Docling OOM).
    Synchronized with _GLOBAL_OCR_LOCK to prevent CPU starvation on 2 vCPU servers.
    """

    def __init__(self):
        self.ocr = get_shared_rapid_ocr()
        self.associator = SpatialImageTextAssociator()

    def parse_pdf(
        self,
        file_path: str,
        document_id: str = "",
        max_pages: int = 50,
        pdf_context: PDFContext = PDFContext.FLATTENED_DESIGN
    ) -> List[Dict[str, Any]]:
        """
        Parses flattened design PDF pages:
        1. Renders page at 150 DPI.
        2. RapidOCR extracts text boxes with coordinates.
        3. Identifies embedded images and computes spatial association.
        4. Links product container photos with canonical product headings.
        5. Returns list of page dicts: [{'page': 1, 'text': '...', 'provenance': [...]}]
        """
        if not os.path.exists(file_path):
            logger.error(f"FlattenedDesignParser: file not found: {file_path}")
            return []

        with _GLOBAL_OCR_LOCK:
            t_lock_start = time.time()
            logger.info(f"🔒 [OCR-LOCK] Acquired dedicated OCR slot for '{file_path}' (single-flight on 2 vCPU)...")
            try:
                doc = fitz.open(file_path)
                total_pages = len(doc)
                pages_to_process = min(total_pages, max_pages)

                if total_pages > max_pages:
                    logger.warning(
                        f"[FLATTENED-PARSER] Document has {total_pages} pages, "
                        f"capping at {max_pages} pages for memory & latency stability."
                    )

                parsed_pages: List[Dict[str, Any]] = []

                for p_idx in range(pages_to_process):
                    page = doc[p_idx]
                    page_num = p_idx + 1
                    pw = page.rect.width
                    ph = page.rect.height

                    # 1. Render page to image at 150 DPI for fast & sharp OCR
                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")

                    # 2. Run RapidOCR
                    t0 = time.time()
                    ocr_out = self.ocr(img_bytes)
                    ocr_ms = int((time.time() - t0) * 1000)

                    ocr_blocks: List[Dict[str, Any]] = []
                    if hasattr(ocr_out, "txts") and ocr_out.txts:
                        # Coordinate scale factor: 150 DPI / 72 DPI ≈ 2.0833
                        scale_x = pw / max(1.0, pix.width)
                        scale_y = ph / max(1.0, pix.height)

                        for b_box, txt, score in zip(ocr_out.boxes, ocr_out.txts, ocr_out.scores):
                            # b_box is 4 corner points [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]
                            xs = [pt[0] * scale_x for pt in b_box]
                            ys = [pt[1] * scale_y for pt in b_box]
                            rect_box = [min(xs), min(ys), max(xs), max(ys)]
                            ocr_blocks.append({
                                "text": txt.strip(),
                                "bbox": rect_box,
                                "score": float(score)
                            })

                    logger.info(
                        f"🔍 [FLATTENED-PARSER] Page {page_num}: OCR extracted {len(ocr_blocks)} "
                        f"elements in {ocr_ms}ms"
                    )

                    # 3. Extract embedded image assets from page
                    embedded_imgs: List[Dict[str, Any]] = []
                    for img_info in page.get_images(full=True):
                        xref = img_info[0]
                        rects = page.get_image_rects(xref)
                        if not rects:
                            continue

                        rect = rects[0]
                        try:
                            base = doc.extract_image(xref)
                            w = base.get("width", int(abs(rect.x1 - rect.x0)))
                            h = base.get("height", int(abs(rect.y1 - rect.y0)))
                            raw_bytes = base.get("image", b"")
                            ext = base.get("ext", "jpeg")

                            # Upload embedded asset to MinIO
                            fname = f"pdf_flat_{document_id or 'doc'}_p{page_num}_{xref}.{ext}"
                            upload_res = upload_image(raw_bytes, fname, content_type=f"image/{ext}")
                            target_url = upload_res.get("image_url") or ""

                            embedded_imgs.append({
                                "xref": xref,
                                "rect": rect,
                                "width": w,
                                "height": h,
                                "target_url": target_url,
                                "source_document": os.path.basename(file_path),
                                "bytes": raw_bytes,
                                "ext": ext
                            })
                        except Exception as img_err:
                            logger.debug(f"Failed extracting image xref {xref} on page {page_num}: {img_err}")

                    # 4. Spatial Association & Provenance Evaluation
                    provenance_list = self.associator.associate_page_elements(
                        document_id=document_id,
                        page_num=page_num,
                        page_width=pw,
                        page_height=ph,
                        ocr_blocks=ocr_blocks,
                        embedded_images=embedded_imgs,
                        pdf_context=pdf_context
                    )

                    # 5. Assemble Clean Structured Markdown
                    assembled_markdown = self._assemble_catalog_markdown(
                        ocr_blocks=ocr_blocks,
                        provenance_list=provenance_list,
                        page_width=pw,
                        page_height=ph
                    )

                    image_urls = [
                        p.target_url for p in provenance_list if p.should_display() and p.target_url
                    ]

                    parsed_pages.append({
                        "page": page_num,
                        "text": assembled_markdown,
                        "image_urls": image_urls,
                        "image_url": image_urls[0] if image_urls else None,
                        "provenance": [p.to_dict() for p in provenance_list]
                    })

                doc.close()
                return parsed_pages
            finally:
                logger.info(f"🔓 [OCR-LOCK] Released dedicated OCR slot for '{file_path}' in {time.time() - t_lock_start:.2f}s.")

    def _assemble_catalog_markdown(
        self,
        ocr_blocks: List[Dict[str, Any]],
        provenance_list: List[ImageProvenance],
        page_width: float,
        page_height: float
    ) -> str:
        """
        Structures OCR blocks into human-readable catalog markdown with headings,
        product info, active ingredients, usage steps, and linked product image.
        Uses column and coordinate-based proximity clustering to prevent mixing left
        and right column text.
        """
        if not ocr_blocks:
            return ""

        from app.rag.utils.spatial_associator import PRODUCT_SEMANTIC_KEYWORDS, LOGO_KEYWORDS

        # Add center coordinates if missing
        for b in ocr_blocks:
            if "cx" not in b or "cy" not in b:
                bbox = b.get("bbox", [0, 0, 0, 0])
                b["cx"] = (bbox[0] + bbox[2]) / 2.0
                b["cy"] = (bbox[1] + bbox[3]) / 2.0

        # 1. Identify Primary Product Title
        title_candidate = None
        for b in ocr_blocks:
            txt = b["text"].strip()
            txt_l = txt.lower()
            if b["cy"] < (page_height * 0.40) and len(txt) > 5:
                has_brand = any(bw in txt_l for bw in LOGO_KEYWORDS)
                has_prod = any(pw in txt_l for pw in PRODUCT_SEMANTIC_KEYWORDS)
                if has_prod and not has_brand:
                    title_candidate = txt
                    break

        if not title_candidate:
            for b in ocr_blocks:
                txt = b["text"].strip()
                txt_l = txt.lower()
                if b["cy"] < (page_height * 0.40) and len(txt) > 5 and not any(bw in txt_l for bw in LOGO_KEYWORDS):
                    title_candidate = txt
                    break

        if not title_candidate and ocr_blocks:
            title_candidate = ocr_blocks[0]["text"]

        # 2. Identify Section Headers
        headers = {}
        for b in ocr_blocks:
            txt_l = b["text"].lower().strip()
            if "product information" in txt_l or "informasi produk" in txt_l:
                headers["info"] = b
            elif "cara pakai" in txt_l or "aturan pakai" in txt_l:
                headers["cara_pakai"] = b
            elif "bahan aktif" in txt_l or "active ingredient" in txt_l:
                headers["bahan_aktif"] = b

        # 3. Associate content blocks to sections by spatial proximity
        info_blocks = []
        cara_pakai_blocks = []
        bahan_aktif_blocks = []
        price_blocks = []
        status_blocks = []
        unassigned_blocks = []

        midpoint = page_width / 2.0

        for b in ocr_blocks:
            txt = b["text"].strip()
            txt_l = txt.lower()

            # Skip title repeat, clinic brand logos, glyphs
            if txt == title_candidate or any(h.get("text") == txt for h in headers.values()):
                continue
            if any(bw in txt_l for bw in ["aesthetic clinic", "naturally speaking"]):
                continue
            if txt in ["4", "口"]:
                continue

            # Price & Status Check
            if re.search(r"\b(idr|rp)\b\s*\d+", txt_l):
                price_blocks.append(txt)
                continue
            if "discontinue" in txt_l or "stok klinik habis" in txt_l:
                status_blocks.append(txt)
                continue

            # Skip text physically printed on the product bottle packaging label
            if (615 <= b["cx"] <= 745) and (160 <= b["cy"] <= 415):
                continue

            assigned = False

            # Column 1 (Left / Info): x < 330, between info header and bahan_aktif header
            if "info" in headers and not assigned:
                h = headers["info"]
                if b["cx"] < 330 and h["cy"] < b["cy"] < 340:
                    info_blocks.append(b)
                    assigned = True

            # Column 2 (Right / Cara Pakai): x between 360 and 615, y between 210 and 340
            if "cara_pakai" in headers and not assigned:
                h = headers["cara_pakai"]
                if 360 <= b["cx"] <= 615 and h["cy"] < b["cy"] < 340:
                    cara_pakai_blocks.append(b)
                    assigned = True

            # Section 3 (Bahan Aktif): below bahan_aktif header (y: 350 to 460)
            if "bahan_aktif" in headers and not assigned:
                h = headers["bahan_aktif"]
                if h["cy"] < b["cy"] < 460:
                    bahan_aktif_blocks.append(b)
                    assigned = True

            if not assigned:
                unassigned_blocks.append(b)

        # Sort blocks vertically within text sections
        info_blocks.sort(key=lambda b: b["cy"])
        cara_pakai_blocks.sort(key=lambda b: b["cy"])

        # Bahan aktif: pair label & description horizontally (|cy1 - cy2| < 15)
        bahan_aktif_blocks.sort(key=lambda b: (b["cy"], b["cx"]))
        ba_lines = []
        curr_line = []
        curr_cy = None
        for b in bahan_aktif_blocks:
            if curr_cy is None or abs(b["cy"] - curr_cy) < 15:
                curr_line.append(b)
                curr_cy = b["cy"]
            else:
                ba_lines.append(curr_line)
                curr_line = [b]
                curr_cy = b["cy"]
        if curr_line:
            ba_lines.append(curr_line)

        ba_text_lines = []
        for line in ba_lines:
            line.sort(key=lambda b: b["cx"])
            joined = " ".join(b["text"] for b in line)
            joined = re.sub(r"\s+:\s+", " : ", joined)
            ba_text_lines.append(joined.lstrip("-•●◦* "))

        # Assemble Structured Markdown
        lines = [f"## {title_candidate}"]

        # Attach linked product image directly below title if authorized
        included_images = [p for p in provenance_list if p.should_display() and p.target_url]
        if included_images:
            for p in included_images:
                label = p.linked_product or title_candidate
                lines.append(f"\n![{label}]({p.target_url})\n")

        if info_blocks:
            lines.append("### Product Information")
            lines.append(" ".join(b["text"] for b in info_blocks))

        if cara_pakai_blocks:
            lines.append("\n### Cara Pakai")
            lines.append(" ".join(b["text"] for b in cara_pakai_blocks))

        if ba_text_lines:
            lines.append("\n### Bahan Aktif")
            for item in ba_text_lines:
                lines.append(f"- {item}")

        if price_blocks or status_blocks:
            lines.append("\n### Detail Produk")
            for pr in price_blocks:
                lines.append(f"- **Harga**: {pr}")
            if status_blocks:
                lines.append(f"- **Status**: {' '.join(status_blocks)}")

        return "\n".join(lines).strip()
