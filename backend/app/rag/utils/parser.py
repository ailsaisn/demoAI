import os
import time
from typing import Optional, Tuple
from loguru import logger


class ParseResult:
    """
    Unified parse result that can hold either a DoclingDocument (for OCR path)
    or a list of page-text dicts (for fast path).
    """
    def __init__(self, pages: list = None, docling_doc=None, method: str = "fast"):
        self.pages = pages or []       # [{"page": 1, "text": "..."}, ...]
        self.docling_doc = docling_doc  # DoclingDocument object (only for OCR path)
        self.method = method           # "fast" or "docling"

    @property
    def is_fast(self) -> bool:
        return self.method == "fast"

    @property
    def is_docling(self) -> bool:
        return self.method == "docling"


class DocumentParser:
    """
    Smart Document Parser with two extraction paths:
    
    1. FAST PATH (python-docx / pypdf / plain read):
       - For .docx, .txt, and PDF files that contain selectable digital text.
       - Extracts text in < 1 second.
       
    2. DOCLING OCR FALLBACK:
       - For scanned/image-based PDFs where no selectable text exists.
       - Uses Docling's deep layout + OCR model pipeline (~60-120s on CPU).
    """

    def __init__(self):
        logger.info("Initializing Smart DocumentParser (Fast + Docling Selective Fallback)...")
        self._docling_converter = None  # Lazy-loaded only when needed

    def _get_docling_converter(self):
        """Lazy-load Docling DocumentConverter only when OCR is actually needed."""
        if self._docling_converter is None:
            logger.info("Loading Docling DocumentConverter for OCR fallback (first use)...")
            from docling.document_converter import DocumentConverter
            self._docling_converter = DocumentConverter()
        return self._docling_converter

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: DOCX
    # -------------------------------------------------------------------------
    def _parse_docx_fast(self, file_path: str) -> ParseResult:
        """Extract text from .docx using python-docx with heading hierarchy, inline images, and table structure."""
        from docx import Document as DocxDocument
        import re
        import os

        doc = DocxDocument(file_path)
        pages = []
        current_page_text = []
        page_num = 1

        # 1. Pre-extract and upload embedded images from docx relationships
        rid_to_url = {}
        extracted_image_urls = []
        try:
            from app.services.storage import upload_image

            for rId, rel in doc.part.rels.items():
                if hasattr(rel, "target_ref") and "image" in str(rel.target_ref).lower() and hasattr(rel, "target_part"):
                    try:
                        img_bytes = rel.target_part.blob
                        img_ext = os.path.splitext(rel.target_ref)[1].lower().replace(".", "") or "png"
                        fname = f"docx_img_{rId}_{os.path.basename(rel.target_ref)}"
                        upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                        img_url = upload_res.get("image_url")
                        if img_url:
                            rid_to_url[rId] = img_url
                            extracted_image_urls.append(img_url)
                            logger.info(f"🖼️ Extracted and uploaded embedded DOCX image '{rel.target_ref}' (rId: {rId}) -> {img_url}")
                    except Exception as upload_err:
                        logger.debug(f"Failed uploading image for rId {rId}: {upload_err}")
        except Exception as img_init_err:
            logger.debug(f"DOCX rel image extraction error: {img_init_err}")

        # Fallback zip extraction if relationship extraction yielded nothing
        if not extracted_image_urls:
            try:
                import zipfile
                from app.services.storage import upload_image

                with zipfile.ZipFile(file_path, 'r') as z:
                    media_files = [f for f in z.namelist() if f.startswith('word/media/')]
                    for idx, media_name in enumerate(media_files, start=1):
                        img_bytes = z.read(media_name)
                        img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                        if img_ext in ["png", "jpg", "jpeg", "webp"]:
                            fname = f"docx_img_{idx}_{os.path.basename(media_name)}"
                            upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                            img_url = upload_res.get("image_url")
                            if img_url:
                                extracted_image_urls.append(img_url)
            except Exception as zip_err:
                logger.debug(f"DOCX zip fallback image extraction skipped: {zip_err}")

        # 2. Extract paragraphs with inline images
        for para in doc.paragraphs:
            text = para.text.strip()
            blips = para._element.xpath('.//a:blip/@r:embed')
            img_tags = [f"![Gambar]({rid_to_url[rId]})" for rId in blips if rId in rid_to_url]
            if img_tags:
                if text:
                    text = f"{text}\n\n" + "\n\n".join(img_tags)
                else:
                    text = "\n\n".join(img_tags)

            if not text:
                continue

            # Check for page break in paragraph runs
            has_page_break = False
            for run in para.runs:
                if run._element.xml and "w:br" in run._element.xml and 'w:type="page"' in run._element.xml:
                    has_page_break = True
                    break

            if has_page_break and current_page_text:
                pages.append({"page": page_num, "text": "\n\n".join(current_page_text)})
                current_page_text = []
                page_num += 1

            # Detect style-based headings or bold title lines
            style_name = para.style.name.lower() if para.style else ""
            is_bold_para = para.runs and all(run.bold for run in para.runs if run.text.strip()) and len(text) < 120

            if "title" in style_name:
                formatted_text = f"# {text}"
            elif "heading 1" in style_name:
                formatted_text = f"# {text}"
            elif "heading 2" in style_name:
                formatted_text = f"## {text}"
            elif "heading 3" in style_name or "heading 4" in style_name:
                formatted_text = f"### {text}"
            elif re.match(r"^\d+\.\d+\s+", text):
                formatted_text = f"### {text}"
            elif re.match(r"^\d+\.\s+[A-Z]", text) and len(text) < 80:
                formatted_text = f"## {text}"
            elif is_bold_para and not text.startswith("#"):
                formatted_text = f"### {text}"
            else:
                formatted_text = text

            current_page_text.append(formatted_text)

        # 3. Extract tables in docx as clean markdown tables (including embedded images in cells)
        for table in doc.tables:
            table_rows = []
            header_cells = [cell.text.strip() for cell in table.rows[0].cells] if table.rows else []
            for row in table.rows:
                row_cells = []
                for c_idx, cell in enumerate(row.cells):
                    c_text = cell.text.strip().replace("\n", " ")
                    blips = cell._element.xpath('.//a:blip/@r:embed')
                    if blips:
                        col_name = header_cells[c_idx] if c_idx < len(header_cells) and header_cells[c_idx] else "Gambar"
                        cell_img_tags = [f"![{col_name}]({rid_to_url[rId]})" for rId in blips if rId in rid_to_url]
                        if cell_img_tags:
                            if c_text:
                                c_text = f"{c_text} " + " ".join(cell_img_tags)
                            else:
                                c_text = " ".join(cell_img_tags)
                    row_cells.append(c_text)
                table_rows.append("| " + " | ".join(row_cells) + " |")
            if table_rows:
                if len(table_rows) >= 1:
                    col_count = len(table.columns)
                    delimiter = "| " + " | ".join(["---"] * col_count) + " |"
                    table_rows.insert(1, delimiter)
                current_page_text.append("\n".join(table_rows))

        # Flush remaining text
        if current_page_text:
            pages.append({"page": page_num, "text": "\n\n".join(current_page_text)})

        if extracted_image_urls and pages:
            pages[0]["image_urls"] = extracted_image_urls
            pages[0]["image_url"] = extracted_image_urls[0]

        return ParseResult(pages=pages, method="fast")

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: TXT
    # -------------------------------------------------------------------------
    def _parse_txt_fast(self, file_path: str) -> ParseResult:
        """Extract text from .txt file (instant)."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return ParseResult(pages=[{"page": 1, "text": content}], method="fast")

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: PDF (with scanned detection)
    # -------------------------------------------------------------------------
    def _parse_pdf_fast(self, file_path: str) -> Optional[ParseResult]:
        """
        Try to extract text from PDF using pypdf.
        Returns ParseResult if the PDF has sufficient digital text.
        Returns None if the PDF appears to be scanned/image-based (triggers Docling fallback).
        """
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        pages = []
        total_chars = 0
        pages_with_text = 0

        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            char_count = len(text)
            total_chars += char_count

            if char_count > 30:  # Meaningful text threshold per page
                pages_with_text += 1

            pages.append({"page": i + 1, "text": text})

        # Heuristic: if < 30% of pages have meaningful text, assume scanned PDF
        text_coverage = pages_with_text / max(total_pages, 1)
        avg_chars_per_page = total_chars / max(total_pages, 1)

        if text_coverage < 0.3 or avg_chars_per_page < 50:
            logger.warning(
                f"PDF detected as scanned/image-based "
                f"(text_coverage={text_coverage:.0%}, avg_chars={avg_chars_per_page:.0f}). "
                f"Falling back to Docling OCR..."
            )
            return None  # Signal to use Docling OCR

        # Try to extract embedded images from PDF pages and upload to MinIO in parallel
        try:
            import fitz  # PyMuPDF
            import re
            from app.services.storage import upload_images_parallel
            doc = fitz.open(file_path)
            upload_batch = []
            
            for i, page in enumerate(doc):
                img_infos = page.get_image_info(xrefs=True)
                if not img_infos:
                    raw_imgs = page.get_images()
                    img_infos = [{"xref": im[0], "bbox": [0, 0, 0, 0]} for im in raw_imgs if len(im) > 0]

                blocks = page.get_text("blocks")
                text_blocks = [b for b in blocks if len(b) >= 5 and b[4].strip() and (len(b) < 7 or b[6] == 0)]
                
                seen_xrefs = set()
                for img_idx, im in enumerate(img_infos):
                    xref = im.get("xref")
                    if not xref or xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    
                    base_img = doc.extract_image(xref)
                    img_bytes = base_img.get("image")
                    img_ext = base_img.get("ext", "png")
                    if not img_bytes or len(img_bytes) < 100:
                        continue
                        
                    bbox = im.get("bbox", [0, 0, 0, 0])
                    img_y_mid = (bbox[1] + bbox[3]) / 2.0
                    
                    best_block = None
                    best_dist = float("inf")
                    for b in text_blocks:
                        b_y_mid = (b[1] + b[3]) / 2.0
                        dist = abs(b_y_mid - img_y_mid)
                        if dist < best_dist:
                            best_dist = dist
                            best_block = b
                            
                    prod_label = ""
                    if best_block and best_dist <= 80:
                        lines = [l.strip() for l in best_block[4].splitlines() if l.strip()]
                        for l in lines:
                            if l.lower() in ("foto produk", "nama produk", "brand", "kategori", "ukuran", "deskripsi", "no", "action", "gambar"):
                                continue
                            prod_label = l
                            break
                            
                    if not prod_label:
                        prod_label = f"Image p{i+1}_{img_idx+1}"
                        
                    clean_fname = re.sub(r'[^a-zA-Z0-9_\-]', '_', prod_label)[:40].strip('_')
                    if not clean_fname:
                        clean_fname = f"pdf_img_p{i+1}_{img_idx+1}"
                    else:
                        clean_fname = f"pdf_img_p{i+1}_{img_idx+1}_{clean_fname}"
                        
                    fname = f"{clean_fname}.{img_ext}"
                    
                    upload_batch.append({
                        "content": img_bytes,
                        "filename": fname,
                        "content_type": f"image/{img_ext}",
                        "page_index": i,
                        "img_fname": fname,
                        "product_name": prod_label
                    })
            
            if upload_batch:
                results = upload_images_parallel(upload_batch)
                for item, res in zip(upload_batch, results):
                    img_url = res.get("image_url")
                    p_idx = item["page_index"]
                    fname = item["img_fname"]
                    prod_name = item.get("product_name") or fname
                    if img_url and p_idx < len(pages):
                        if "image_urls" not in pages[p_idx]:
                            pages[p_idx]["image_urls"] = []
                        if "images" not in pages[p_idx]:
                            pages[p_idx]["images"] = []
                        pages[p_idx]["image_urls"].append(img_url)
                        pages[p_idx]["images"].append({
                            "id": f"img_p{p_idx+1}_{len(pages[p_idx]['images'])+1}",
                            "url": img_url,
                            "product_name": prod_name,
                            "caption": prod_name,
                            "role": "PRODUCT_PACKAGING"
                        })
                        # Embed image tag into page text near the product if found, else append
                        if prod_name and prod_name in pages[p_idx]["text"]:
                            pattern = re.compile(rf'(^.*{re.escape(prod_name)}.*$)', re.MULTILINE)
                            if pattern.search(pages[p_idx]["text"]):
                                pages[p_idx]["text"] = pattern.sub(rf'\1\n![{prod_name}]({img_url})', pages[p_idx]["text"], count=1)
                            else:
                                pages[p_idx]["text"] += f"\n\n![{prod_name}]({img_url})"
                        else:
                            pages[p_idx]["text"] += f"\n\n![{prod_name}]({img_url})"
                            
                for i in range(len(pages)):
                    if pages[i].get("image_urls"):
                        pages[i]["image_url"] = pages[i]["image_urls"][0]
        except Exception as img_err:
            logger.warning(f"PDF embedded image extraction failed: {img_err}", exc_info=True)

        # Apply Structure Reconstruction / Document Normalization on each page's extracted text
        from app.rag.utils.normalizer import normalize_document_text
        for p in pages:
            if p.get("text"):
                p["text"] = normalize_document_text(p["text"])

        return ParseResult(pages=pages, method="fast")

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: EXCEL & CSV (.xlsx, .xls, .csv)
    # -------------------------------------------------------------------------
    def _parse_excel_fast(self, file_path: str) -> ParseResult:
        """Extract text and markdown tables from .xlsx, .xls, and .csv files using pandas."""
        import pandas as pd

        ext = os.path.splitext(file_path)[1].lower()
        pages = []
        extracted_image_urls = []

        # Extract embedded images from .xlsx/.xlsm media parts and upload to MinIO first
        if ext in [".xlsx", ".xlsm"]:
            try:
                import zipfile
                from app.services.storage import upload_images_parallel

                with zipfile.ZipFile(file_path, 'r') as z:
                    media_files = [f for f in z.namelist() if f.startswith('xl/media/')]
                    # Collect all image data first
                    upload_batch = []
                    for idx, media_name in enumerate(media_files, start=1):
                        img_bytes = z.read(media_name)
                        img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                        if img_ext in ["png", "jpg", "jpeg", "webp"]:
                            upload_batch.append({
                                "content": img_bytes,
                                "filename": f"excel_img_{idx}_{os.path.basename(media_name)}",
                                "content_type": f"image/{img_ext}"
                            })

                    # Upload all images in parallel (1x client init, concurrent put_object)
                    if upload_batch:
                        results = upload_images_parallel(upload_batch)
                        for res in results:
                            img_url = res.get("image_url")
                            if img_url:
                                extracted_image_urls.append(img_url)
                        logger.info(f"Parallel upload: {len(extracted_image_urls)} Excel images uploaded to MinIO.")
            except Exception as img_err:
                logger.debug(f"Excel embedded image extraction skipped: {img_err}")

        try:
            def _df_to_markdown_safe(dataframe) -> str:
                try:
                    return dataframe.to_markdown(index=False)
                except Exception:
                    headers = [str(c) for c in dataframe.columns]
                    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                    for _, row in dataframe.iterrows():
                        row_vals = ["" if pd.isna(v) else str(v).replace("\n", " ").strip() for v in row]
                        lines.append("| " + " | ".join(row_vals) + " |")
                    return "\n".join(lines)

            if ext == ".csv":
                df = pd.read_csv(file_path)
                df = df.dropna(how="all")
                md_table = _df_to_markdown_safe(df)
                pages.append({
                    "page": 1,
                    "text": f"### CSV Data Table\n\n{md_table}"
                })
            else:
                with pd.ExcelFile(file_path) as excel_file:
                    for page_idx, sheet_name in enumerate(excel_file.sheet_names, start=1):
                        df = pd.read_excel(excel_file, sheet_name=sheet_name)
                        if df.empty:
                            continue
                        df = df.dropna(how="all")

                        # If Excel has an image/photo column, inject extracted image URLs row-by-row
                        if extracted_image_urls:
                            photo_col = None
                            for col in df.columns:
                                col_str = str(col).lower()
                                if any(k in col_str for k in ["foto", "gambar", "photo", "image", "picture"]):
                                    photo_col = col
                                    break
                            
                            if photo_col is not None:
                                img_idx = 0
                                new_col_vals = []
                                for r_idx in range(len(df)):
                                    if img_idx < len(extracted_image_urls):
                                        prod_name = ""
                                        for name_col in df.columns:
                                            if any(nk in str(name_col).lower() for nk in ["nama", "product", "title", "item"]):
                                                val = str(df.at[df.index[r_idx], name_col])
                                                if val and val != "nan":
                                                    prod_name = val
                                                    break
                                        img_alt = prod_name or f"Foto Produk {img_idx+1}"
                                        new_col_vals.append(f"![{img_alt}]({extracted_image_urls[img_idx]})")
                                        img_idx += 1
                                    else:
                                        val_existing = str(df.at[df.index[r_idx], photo_col])
                                        new_col_vals.append("" if val_existing == "nan" else val_existing)
                                df[photo_col] = new_col_vals

                        md_table = _df_to_markdown_safe(df)
                        sheet_text = f"### Sheet: {sheet_name}\n\n{md_table}"
                        pages.append({
                            "page": page_idx,
                            "text": sheet_text,
                            "image_urls": extracted_image_urls,
                            "image_url": extracted_image_urls[0] if extracted_image_urls else None
                        })

            if not pages:
                pages = [{"page": 1, "text": "Dokumen spreadsheet kosong."}]

            if extracted_image_urls and pages:
                pages[0]["image_urls"] = extracted_image_urls
                pages[0]["image_url"] = extracted_image_urls[0]

            return ParseResult(pages=pages, method="fast")
        except Exception as e:
            logger.warning(f"Fast pandas Excel parse failed for {file_path}: {e}. Falling back to text extraction...")
            return ParseResult(pages=[{"page": 1, "text": f"Error parsing spreadsheet: {e}"}], method="fast")

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: POWERPOINT (.pptx, .ppt)
    # -------------------------------------------------------------------------
    def _parse_pptx_fast(self, file_path: str) -> ParseResult:
        """Extracts text, slide titles, tables, and notes from PowerPoint (.pptx, .ppt) presentations."""
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            pages = []
            any_shape_has_image = False

            for slide_idx, slide in enumerate(prs.slides, start=1):
                slide_texts = []
                slide_image_urls = []
                slide_title = f"Slide {slide_idx}"

                # Extract title if present
                if slide.shapes.title and slide.shapes.title.text:
                    slide_title = slide.shapes.title.text.strip()
                    slide_texts.append(f"## {slide_title}")

                # 1. Detect spatial Before / After text labels on this slide
                before_labels = []
                after_labels = []
                for s in slide.shapes:
                    if s.has_text_frame:
                        s_text = s.text_frame.text.strip().upper()
                        if any(w in s_text for w in ["SEBELUM", "BEFORE"]):
                            before_labels.append((s.left, s.top, s_text))
                        elif any(w in s_text for w in ["SESUDAH", "AFTER", "SETELAH"]):
                            after_labels.append((s.left, s.top, s_text))

                # 2. Collect and classify image shapes spatially
                img_shapes_on_slide = [s for s in slide.shapes if hasattr(s, "image")]
                classified_images = []

                if img_shapes_on_slide:
                    any_shape_has_image = True
                    if before_labels and after_labels and len(img_shapes_on_slide) >= 2:
                        # Spatial proximity matching: match each image to closest label on X axis
                        scored_shapes = []
                        for s in img_shapes_on_slide:
                            dist_before = min(abs(s.left - bl[0]) for bl in before_labels)
                            dist_after = min(abs(s.left - al[0]) for al in after_labels)
                            scored_shapes.append((s, dist_before, dist_after))

                        # Shape with smallest distance to Before label is BEFORE
                        # Shape with smallest distance to After label is AFTER
                        # Sort so that BEFORE comes first (0), AFTER comes second (1)
                        scored_shapes.sort(key=lambda item: item[1] - item[2])
                        for idx, (s, d_b, d_a) in enumerate(scored_shapes):
                            role = "CLINICAL_BEFORE" if idx == 0 else "CLINICAL_AFTER"
                            classified_images.append((s, role))
                    else:
                        # Standard reading order: top-to-bottom, left-to-right
                        sorted_shapes = sorted(img_shapes_on_slide, key=lambda s: (round(s.top / 100000), s.left))
                        for s in sorted_shapes:
                            classified_images.append((s, "IMAGE"))

                # 3. Process non-image shapes (text & tables)
                for shape in slide.shapes:
                    if shape == slide.shapes.title or hasattr(shape, "image"):
                        continue
                    # Extract text frames
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            text = paragraph.text.strip()
                            if text:
                                slide_texts.append(f"- {text}")

                    # Extract tables in slides
                    elif shape.has_table:
                        table_rows = []
                        table = shape.table
                        for row in table.rows:
                            row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                            table_rows.append("| " + " | ".join(row_cells) + " |")
                        if table_rows:
                            if len(table_rows) >= 1:
                                col_count = len(table.columns)
                                delimiter = "| " + " | ".join(["---"] * col_count) + " |"
                                table_rows.insert(1, delimiter)
                            slide_texts.append("\n".join(table_rows))

                # 4. Upload and append classified image shapes in deterministic order (BEFORE first, then AFTER)
                for img_idx, (shape, role) in enumerate(classified_images, start=1):
                    try:
                        from app.services.storage import upload_image
                        img_obj = shape.image
                        img_bytes = img_obj.blob
                        img_ext = img_obj.ext
                        role_tag = "before" if role == "CLINICAL_BEFORE" else ("after" if role == "CLINICAL_AFTER" else f"img_{img_idx}")
                        fname = f"pptx_s{slide_idx}_{role_tag}.{img_ext}"
                        upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                        img_url = upload_res.get("image_url")
                        if img_url:
                            slide_image_urls.append(img_url)
                            if role == "CLINICAL_BEFORE":
                                slide_texts.append(f"![Foto Sebelum Perawatan - {slide_title}]({img_url})")
                            elif role == "CLINICAL_AFTER":
                                slide_texts.append(f"![Foto Sesudah Perawatan - {slide_title}]({img_url})")
                            else:
                                slide_texts.append(f"![{slide_title} Image]({img_url})")
                    except Exception as shape_img_err:
                        logger.debug(f"PPTX slide image shape extraction skipped: {shape_img_err}")

                # Extract speaker notes if any
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        slide_texts.append(f"**Notes:** {notes}")

                if slide_texts:
                    full_slide_content = f"### Slide {slide_idx}: {slide_title}\n\n" + "\n".join(slide_texts)
                    pages.append({
                        "page": slide_idx,
                        "text": full_slide_content,
                        "image_urls": slide_image_urls,
                        "image_url": slide_image_urls[0] if slide_image_urls else None
                    })

            if not pages:
                pages = [{"page": 1, "text": "Presentasi PowerPoint kosong."}]

            # Extract embedded images from .pptx media parts zip fallback ONLY if NO shapes had images
            if not any_shape_has_image:
                try:
                    import zipfile
                    from app.services.storage import upload_images_parallel

                    with zipfile.ZipFile(file_path, 'r') as z:
                        media_files = [f for f in z.namelist() if f.startswith('ppt/media/')]
                        upload_batch = []
                        for idx, media_name in enumerate(media_files, start=1):
                            img_bytes = z.read(media_name)
                            img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                            if img_ext in ["png", "jpg", "jpeg", "webp"]:
                                fname = f"pptx_img_{idx}_{os.path.basename(media_name)}"
                                upload_batch.append({
                                    "content": img_bytes,
                                    "filename": fname,
                                    "content_type": f"image/{img_ext}"
                                })
                        
                        if upload_batch:
                            results = upload_images_parallel(upload_batch)
                            extracted_image_urls = [r["image_url"] for r in results if r.get("image_url")]
                            if extracted_image_urls and pages:
                                existing_urls = pages[0].get("image_urls", [])
                                combined_urls = list(dict.fromkeys(existing_urls + extracted_image_urls))
                                pages[0]["image_urls"] = combined_urls
                                pages[0]["image_url"] = combined_urls[0]
                            logger.info(f"⚡ [ASYNC BATCH] Uploaded {len(extracted_image_urls)} embedded PPTX images to MinIO in parallel.")
                except Exception as img_err:
                    logger.debug(f"PPTX embedded image extraction skipped: {img_err}")

            return ParseResult(pages=pages, method="fast")
        except Exception as e:
            logger.warning(f"Fast PPTX parse failed for {file_path}: {e}. Falling back to Docling...")
            return self._parse_with_docling(file_path)

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: LEGACY DOC (.doc)
    # -------------------------------------------------------------------------
    def _parse_doc_fast(self, file_path: str) -> ParseResult:
        """Extract text from legacy .doc files using Docling OCR / parser."""
        return self._parse_with_docling(file_path)

    def _parse_standalone_image(self, file_path: str) -> ParseResult:
        """
        Uploads standalone image file to MinIO S3 and extracts structured knowledge using 
        Generic Image Knowledge Extraction Vision LLM (with Docling OCR fallback)
        so it can be indexed in PGVector/BM25 and displayed by frontend during chatbot recommendations.
        """
        import base64
        import json
        from app.services.storage import upload_image

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower().replace(".", "")
        content_type = f"image/{ext}" if ext in ["png", "jpg", "jpeg", "webp"] else "image/png"

        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()

            upload_res = upload_image(image_bytes, file_name, content_type=content_type)
            image_url = upload_res.get("image_url", "")
            s3_key = upload_res.get("s3_key", "")

            extracted_text = ""
            extracted_meta = {
                "s3_key": s3_key,
                "storage_key": s3_key,
                "image_url": image_url,
                "image_reference": image_url,
            }

            # --- Multimodal Vision LLM Extraction ---
            try:
                from app.rag.config import settings
                from openai import OpenAI

                b64_img = base64.b64encode(image_bytes).decode("utf-8")
                data_uri = f"data:{content_type};base64,{b64_img}"

                db_api_key = None
                db_model_name = None
                db_base_url = None

                try:
                    from sqlalchemy import create_engine, text
                    from app.rag.config import settings
                    from app.core.security import decrypt_api_key
                    
                    sync_conn_str = settings.pg_conn_str.replace("+asyncpg", "")
                    engine = create_engine(sync_conn_str)
                    with engine.connect() as conn:
                        res = conn.execute(text("SELECT key, value FROM app_config WHERE key IN ('LLM_API_KEY', 'LLM_ACTIVE_MODEL_NAME', 'LLM_BASE_URL')")).fetchall()
                        config_map = {row[0]: row[1] for row in res if row[1]}
                        
                        if "LLM_API_KEY" in config_map:
                            try:
                                db_api_key = decrypt_api_key(config_map["LLM_API_KEY"])
                            except Exception:
                                db_api_key = config_map["LLM_API_KEY"]
                        db_model_name = config_map.get("LLM_ACTIVE_MODEL_NAME")
                        db_base_url = config_map.get("LLM_BASE_URL")
                except Exception as db_cfg_err:
                    logger.debug(f"Sync DB config fetch failed: {db_cfg_err}")

                api_key = db_api_key or os.getenv("OPENAI_API_KEY") or getattr(settings, "openai_api_key", None)
                if api_key and not api_key.startswith("sk-"):
                    env_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "openai_api_key", None)
                    if env_key and env_key.startswith("sk-"):
                        api_key = env_key

                base_url = db_base_url or os.getenv("OPENAI_BASE_URL") or getattr(settings, "openai_base_url", None)
                model_name = db_model_name or os.getenv("VISION_MODEL_NAME") or getattr(settings, "openai_model_name", None) or "gpt-5.4-mini"

                # Guard against mismatched OpenAI vs Gemini model name / base_url
                if api_key and api_key.startswith("sk-"):
                    if not model_name or "gemini" in model_name.lower() or not any(model_name.startswith(p) for p in ["gpt-", "o1", "o3", "chatgpt"]):
                        model_name = "gpt-5.4-mini"
                    if base_url and "googleapis.com" in base_url:
                        base_url = None

                if api_key:
                    logger.info(f"🔍 Running Generic Image Knowledge Extraction for '{file_name}' using model '{model_name}'...")
                    client_kwargs = {
                        "api_key": api_key,
                        "timeout": 30.0
                    }
                    if base_url:
                        client_kwargs["base_url"] = base_url

                    client = OpenAI(**client_kwargs)
                    prompt_text = (
                        "You are an expert product recognition system for PT Arya Noble (ERHA) Knowledge Base.\n\n"
                        "Your task is to identify the EXACT PRODUCT NAME shown on the product packaging or image.\n\n"
                        "## STRICT RULES (MANDATORY):\n"
                        "1. **IDENTIFY PRODUCT NAME ONLY**: Recognize and extract ONLY the official Product Name printed on the packaging (e.g., 'Exfoliating Cleansing Scrub', 'Acne Act Acne Spot Gel').\n"
                        "2. **DO NOT EXTRACT PACKAGING DETAILS**: Do NOT generate, OCR, or invent packaging text such as Brand, SKU, Net Weight, instructions, benefits, or 'Informasi Tertera pada Kemasan'. Generating packaging text is strictly forbidden to prevent false detections.\n"
                        "3. **PRESERVE RETRIEVAL CONTEXT**: Provide the clean product name and a clean 1-line Indonesian context so this image has full context and can be retrieved accurately in search and RAG answers.\n"
                        "4. **Clinical / Before-After Photos**: If this is a clinical photo of skin/face (not product packaging), identify the treatment or clinical condition (e.g., 'Acne Vulgaris - Before Treatment') and state whether it is BEFORE or AFTER.\n\n"
                        "## Output Format (Valid JSON ONLY):\n"
                        "{\n"
                        '  "title": "Exact Visible Product Name",\n'
                        '  "product_name": "Exact Visible Product Name",\n'
                        '  "image_role": "PRODUCT_PACKAGING",\n'
                        '  "caption": "Foto produk Exact Visible Product Name",\n'
                        '  "document_type": "PRODUCT",\n'
                        '  "summary_markdown": "# Exact Visible Product Name\\n\\n![Exact Visible Product Name](IMAGE_URL_PLACEHOLDER)\\n\\nDokumen visual produk resmi ERHA: Exact Visible Product Name."\n'
                        "}"
                    )

                    completion_kwargs = {
                        "model": model_name,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt_text},
                                    {"type": "image_url", "image_url": {"url": data_uri}}
                                ]
                            }
                        ],
                        "temperature": 0.0
                    }
                    try:
                        response = client.chat.completions.create(
                            **completion_kwargs,
                            max_completion_tokens=2000
                        )
                    except Exception as tok_err:
                        err_str = str(tok_err).lower()
                        if "max_completion_tokens" in err_str or "unsupported" in err_str:
                            response = client.chat.completions.create(
                                **completion_kwargs,
                                max_tokens=2000
                            )
                        else:
                            raise tok_err
                    if response.choices and len(response.choices) > 0:
                        raw_content = (response.choices[0].message.content or "").strip()
                        try:
                            clean_json = raw_content
                            if "```" in clean_json:
                                lines = clean_json.split("\n")
                                if lines[0].startswith("```"):
                                    lines = lines[1:]
                                if lines and lines[-1].startswith("```"):
                                    lines = lines[:-1]
                                clean_json = "\n".join(lines).strip()
                            data = json.loads(clean_json, strict=False)

                            img_title = data.get("title") or data.get("product_name") or os.path.splitext(file_name)[0]
                            p_name = data.get("product_name") or img_title
                            brand = data.get("brand") or "PT Arya Noble"
                            active_ing = []
                            clean_sku = None

                            # Infer or extract image role
                            img_role = data.get("image_role")
                            valid_roles = ["PRODUCT_PACKAGING", "CLINICAL_BEFORE", "CLINICAL_AFTER", "TREATMENT_PROCEDURE", "GENERAL"]
                            if not img_role or img_role not in valid_roles:
                                lower_fname = file_name.lower()
                                lower_text = (data.get("summary_markdown") or "").lower()
                                if any(k in lower_fname or k in lower_text for k in ["before", "sebelum"]):
                                    img_role = "CLINICAL_BEFORE"
                                elif any(k in lower_fname or k in lower_text for k in ["after", "sesudah", "setelah"]):
                                    img_role = "CLINICAL_AFTER"
                                elif any(k in lower_fname or k in lower_text for k in ["kemasan", "packaging", "bottle", "box", "produk"]):
                                    img_role = "PRODUCT_PACKAGING"
                                else:
                                    img_role = "PRODUCT_PACKAGING" if data.get("document_type") == "PRODUCT" else "GENERAL"

                            caption = data.get("caption") or f"Foto produk {p_name}"

                            extracted_meta.update({
                                "title": img_title,
                                "product_name": p_name,
                                "brand": brand,
                                "sku": None,
                                "active_ingredients": [],
                                "image_role": img_role,
                                "caption": caption
                            })

                            # Clean structured markdown with product name and image context only (zero packaging hallucination)
                            clean_markdown = f"# {img_title}\n\n![{img_title}]({image_url})\n\nDokumen visual resmi: {p_name}."
                            extracted_text = clean_markdown

                        except Exception as json_err:
                            logger.warning(f"Could not parse Vision LLM JSON response for '{file_name}': {json_err}. Using raw output.")
                            clean_title = os.path.splitext(file_name)[0]
                            extracted_text = f"![{clean_title}]({image_url})\n\n{raw_content}"

            except Exception as vision_err:
                logger.warning(f"Vision LLM extraction skipped/failed for '{file_name}': {vision_err}. Falling back to OCR.")

            # If Vision LLM was not available or produced empty text, fallback to Docling OCR
            if not extracted_text:
                try:
                    ocr_res = self._parse_with_docling(file_path)
                    if ocr_res and ocr_res.docling_doc:
                        ocr_md = ocr_res.docling_doc.export_to_markdown()
                        clean_title = os.path.splitext(file_name)[0]
                        extracted_text = f"![{clean_title}]({image_url})\n\n{ocr_md}"
                except Exception as ocr_err:
                    logger.warning(f"Docling OCR fallback failed for '{file_name}': {ocr_err}")

            if not extracted_text:
                clean_title = os.path.splitext(file_name)[0]
                extracted_text = f"### Image Asset: {clean_title}\n\n![{clean_title}]({image_url})\n\nStorage Key: `{s3_key}`."

            import uuid
            img_id = f"img_{uuid.uuid4().hex[:8]}"
            clean_title = os.path.splitext(file_name)[0]
            current_role = img_role if 'img_role' in locals() and img_role else ("PRODUCT_PACKAGING" if any(k in file_name.lower() for k in ["produk", "bottle", "box"]) else "GENERAL")
            current_caption = caption if 'caption' in locals() and caption else f"Foto {clean_title}"
            current_pname = p_name if 'p_name' in locals() and p_name else clean_title

            image_asset = {
                "id": img_id,
                "url": image_url,
                "s3_key": s3_key,
                "role": current_role,
                "product_name": current_pname,
                "caption": current_caption
            }

            page_data = {
                "page": 1,
                "text": extracted_text,
                "image_id": img_id,
                "image_urls": [image_url] if image_url else [],
                "image_url": image_url,
                "images": [image_asset],
                "s3_key": s3_key,
                "storage_key": s3_key,
                "image_reference": image_url,
                "clinics": ["all"],
                "doctor_types": ["all"],
                "doctors": ["all"],
                "visibility_settings": {
                    "clinics": ["all"],
                    "doctor_types": ["all"],
                    "doctors": ["all"]
                }
            }
            page_data.update(extracted_meta)

            logger.info(f"🖼️ Standalone image '{file_name}' processed via Generic Image Knowledge Extraction (chars={len(extracted_text)}, s3_key={s3_key}, image_url={image_url})")
            return ParseResult(pages=[page_data], method="fast")
        except Exception as e:
            logger.warning(f"Standalone image processing failed for {file_path}: {e}")
            return self._parse_with_docling(file_path)

    # -------------------------------------------------------------------------
    # DOCLING OCR FALLBACK (Heavy / Scanned PDFs & Standalone Images)
    # -------------------------------------------------------------------------
    def _parse_with_docling(self, file_path: str) -> Optional[ParseResult]:
        """Full Docling OCR parse for scanned/image PDFs and standalone images."""
        import io
        from docling_core.types.io import DocumentStream

        converter = self._get_docling_converter()
        file_name = os.path.basename(file_path)

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        stream = io.BytesIO(file_bytes)
        doc_stream = DocumentStream(name=file_name, stream=stream)

        result = converter.convert(doc_stream)
        doc = result.document
        return ParseResult(docling_doc=doc, method="docling")

    # -------------------------------------------------------------------------
    # MAIN ENTRY POINT
    # -------------------------------------------------------------------------
    def parse_file(self, file_path: str) -> Optional[ParseResult]:
        """
        Smart parse: tries fast extraction first for docx, doc, pptx, ppt, txt, pdf, xlsx, xls, csv.
        Falls back to Docling OCR for scanned PDFs & image files.
        Returns a ParseResult object.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        ext = os.path.splitext(file_path)[1].lower()
        start_time = time.time()

        try:
            if ext == ".docx":
                logger.info(f"⚡ Fast DOCX extraction: {file_path}")
                result = self._parse_docx_fast(file_path)

            elif ext == ".doc":
                logger.info(f"📄 Legacy DOC extraction: {file_path}")
                result = self._parse_doc_fast(file_path)

            elif ext in [".pptx", ".ppt"]:
                logger.info(f"📊 Fast PowerPoint extraction: {file_path}")
                result = self._parse_pptx_fast(file_path)

            elif ext == ".txt":
                logger.info(f"⚡ Fast TXT extraction: {file_path}")
                result = self._parse_txt_fast(file_path)

            elif ext in [".xlsx", ".xls", ".csv"]:
                logger.info(f"📊 Fast Excel/CSV extraction: {file_path}")
                result = self._parse_excel_fast(file_path)

            elif ext == ".pdf":
                logger.info(f"⚡ Attempting fast PDF extraction: {file_path}")
                result = self._parse_pdf_fast(file_path)

                if result is None:
                    # Scanned PDF detected → Docling OCR fallback
                    logger.info(f"🔬 Docling OCR fallback for scanned PDF: {file_path}")
                    result = self._parse_with_docling(file_path)
            elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
                logger.info(f"🖼️ Standalone image extraction & MinIO upload: {file_path}")
                result = self._parse_standalone_image(file_path)
            else:
                # Unknown extension → try Docling as universal fallback
                logger.info(f"🔬 Docling universal parse for {ext}: {file_path}")
                result = self._parse_with_docling(file_path)

            elapsed = time.time() - start_time
            if result:
                method_label = "Fast" if result.is_fast else "Docling OCR"
                page_count = len(result.pages) if result.is_fast else "N/A"
                logger.info(
                    f"✅ Parsed {file_path} via {method_label} in {elapsed:.2f}s "
                    f"(pages={page_count})"
                )
            return result

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Error parsing {file_path} after {elapsed:.2f}s: {e}")
            return None
