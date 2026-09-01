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
        """Extract text from .docx using python-docx with heading hierarchy and table structure."""
        from docx import Document as DocxDocument
        import re

        doc = DocxDocument(file_path)
        pages = []
        current_page_text = []
        page_num = 1

        for para in doc.paragraphs:
            text = para.text.strip()
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

        # Extract tables in docx as clean markdown tables
        for table in doc.tables:
            table_rows = []
            for row in table.rows:
                row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
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

        # Extract embedded images from .docx media parts and upload to MinIO
        try:
            import zipfile
            from app.services.storage import upload_image

            with zipfile.ZipFile(file_path, 'r') as z:
                media_files = [f for f in z.namelist() if f.startswith('word/media/')]
                extracted_image_urls = []
                for idx, media_name in enumerate(media_files, start=1):
                    img_bytes = z.read(media_name)
                    img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                    if img_ext in ["png", "jpg", "jpeg", "webp"]:
                        fname = f"docx_img_{idx}_{os.path.basename(media_name)}"
                        upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                        img_url = upload_res.get("image_url")
                        if img_url:
                            extracted_image_urls.append(img_url)
                            logger.info(f"🖼️ Extracted and uploaded embedded DOCX image #{idx} '{media_name}' to MinIO -> {img_url}")
                
                if extracted_image_urls and pages:
                    pages[0]["image_urls"] = extracted_image_urls
                    pages[0]["image_url"] = extracted_image_urls[0]
        except Exception as img_err:
            logger.debug(f"DOCX embedded image extraction skipped: {img_err}")

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

        # Try to extract embedded images from PDF pages and upload to MinIO
        try:
            import fitz  # PyMuPDF
            from app.services.storage import upload_image
            doc = fitz.open(file_path)
            for i, page in enumerate(doc):
                img_list = page.get_images()
                page_image_urls = []
                img_markdowns = []
                for img_idx, img_info in enumerate(img_list):
                    xref = img_info[0]
                    base_img = doc.extract_image(xref)
                    img_bytes = base_img.get("image")
                    img_ext = base_img.get("ext", "png")
                    if img_bytes:
                        fname = f"pdf_p{i+1}_img{img_idx+1}.{img_ext}"
                        upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                        img_url = upload_res.get("image_url")
                if img_markdowns and i < len(pages):
                    pages[i]["text"] += "\n\n" + "\n".join(img_markdowns)
                    pages[i]["image_urls"] = page_image_urls
                    pages[i]["image_url"] = page_image_urls[0] if page_image_urls else None
        except Exception as img_err:
            logger.debug(f"PDF embedded image extraction skipped/optional: {img_err}")

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

            for slide_idx, slide in enumerate(prs.slides, start=1):
                slide_texts = []
                slide_image_urls = []
                slide_title = f"Slide {slide_idx}"

                # Extract title if present
                if slide.shapes.title and slide.shapes.title.text:
                    slide_title = slide.shapes.title.text.strip()
                    slide_texts.append(f"## {slide_title}")

                for shape in slide.shapes:
                    if shape == slide.shapes.title:
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

                    # Extract embedded images in shapes
                    elif hasattr(shape, "image"):
                        try:
                            from app.services.storage import upload_image
                            img_obj = shape.image
                            img_bytes = img_obj.blob
                            img_ext = img_obj.ext
                            fname = f"pptx_s{slide_idx}_img.{img_ext}"
                            upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                            img_url = upload_res.get("image_url")
                            if img_url:
                                slide_image_urls.append(img_url)
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

            # Extract embedded images from .pptx media parts zip fallback
            try:
                import zipfile
                from app.services.storage import upload_image

                with zipfile.ZipFile(file_path, 'r') as z:
                    media_files = [f for f in z.namelist() if f.startswith('ppt/media/')]
                    extracted_image_urls = []
                    for idx, media_name in enumerate(media_files, start=1):
                        img_bytes = z.read(media_name)
                        img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                        if img_ext in ["png", "jpg", "jpeg", "webp"]:
                            fname = f"pptx_img_{idx}_{os.path.basename(media_name)}"
                            upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                            img_url = upload_res.get("image_url")
                            if img_url:
                                extracted_image_urls.append(img_url)
                                logger.info(f"🖼️ Extracted and uploaded embedded PPTX image #{idx} '{media_name}' to MinIO -> {img_url}")
                    
                    if extracted_image_urls and pages:
                        existing_urls = pages[0].get("image_urls", [])
                        combined_urls = list(dict.fromkeys(existing_urls + extracted_image_urls))
                        pages[0]["image_urls"] = combined_urls
                        pages[0]["image_url"] = combined_urls[0]
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
                        "You are an expert medical aesthetic AI knowledge engineer for PT Arya Noble (ERHA) Knowledge Base.\n\n"
                        "Your task is to analyze the provided image (which could be a Product Photo or a Clinical Before-After Face Condition Photo) and extract accurate, fluent, and cohesive knowledge.\n\n"
                        "## Guidelines:\n"
                        "1. **Natural & Cohesive Language**: Write natural, professional, fluent Indonesian prose suitable for clinical doctors and aesthetic specialists. Avoid stiff key-value forms or empty template blocks.\n"
                        "2. **Product Photos (Foto Produk)**:\n"
                        "   - Describe the product name, intended skin types, key benefits, and usage naturally.\n"
                        "   - Include active ingredients in standard markdown bullet points.\n"
                        "3. **Before-After Face Condition Photos (Foto Wajah Before-After)**:\n"
                        "   - State the treatment/product name.\n"
                        "   - Analyze the clinical skin condition changes (Before vs After) naturally (e.g. reduction of inflammatory acne lesions, fading of post-acne erythema, smoothing of skin texture).\n"
                        "4. **No Visual Fluff**: Do NOT describe background color, packaging graphics, lighting, or photography angles.\n\n"
                        "## Output Format (Valid JSON ONLY):\n"
                        "{\n"
                        '  "title": "ERHA Acneact Gentle Acne Moisturizer",\n'
                        '  "product_name": "ERHA Acneact Gentle Acne Moisturizer",\n'
                        '  "document_type": "PRODUCT",\n'
                        '  "brand": "ERHA",\n'
                        '  "sku": null,\n'
                        '  "active_ingredients": ["Granactive Acne Peptide", "Salicylic Acid (BHA)"],\n'
                        '  "summary_markdown": "# ERHA Acneact Gentle Acne Moisturizer\\n\\nERHA Acneact Gentle Acne Moisturizer adalah pelembap wajah ringan yang diformulasikan khusus untuk kulit berminyak, berjerawat, dan sensitif. Memiliki tekstur gel-krim yang cepat meresap dan tidak menyumbat pori-pori.\\n\\n## Manfaat & Penggunaan\\n- Melembapkan kulit berjerawat sekaligus menenangkan kemerahan.\\n- Membantu mengontrol produksi sebum berlebih.\\n- Digunakan secara merata pada wajah setelah pembersih dan serum.\\n\\n## Active Ingredients\\n- **Granactive Acne Peptide**: Membantu meredakan peradangan jerawat.\\n- **Salicylic Acid (BHA)**: Merawat pori-pori dan mencegah timbulnya jerawat baru."\n'
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
                            brand = data.get("brand") or "ERHA"
                            active_ing = data.get("active_ingredients") or []
                            sku_val = data.get("sku")
                            clean_sku = str(sku_val).strip() if sku_val and str(sku_val).strip().lower() not in ["none", "null", "n/a", "-"] else None

                            extracted_meta.update({
                                "title": img_title,
                                "product_name": p_name,
                                "brand": brand,
                                "sku": clean_sku,
                                "active_ingredients": active_ing
                            })

                            # If Vision LLM provided a beautiful fluent summary_markdown directly, use it!
                            raw_summary_md = data.get("summary_markdown")
                            if raw_summary_md and raw_summary_md.strip():
                                summary_text = raw_summary_md.strip()
                                # Ensure image URL is embedded right below the first H1 title
                                if image_url and image_url not in summary_text:
                                    lines = summary_text.split("\n")
                                    if lines and lines[0].startswith("#"):
                                        summary_text = lines[0] + f"\n\n![{img_title}]({image_url})\n" + "\n".join(lines[1:])
                                    else:
                                        summary_text = f"# {img_title}\n\n![{img_title}]({image_url})\n\n" + summary_text
                                extracted_text = summary_text
                            else:
                                # Fallback natural markdown
                                md_blocks = [f"# {img_title}\n\n![{img_title}]({image_url})"]
                                deskripsi = data.get("deskripsi_fungsi") or data.get("searchable_knowledge") or ""
                                if deskripsi:
                                    md_blocks.append(f"## Deskripsi & Fungsi Produk\n{deskripsi}")
                                if active_ing:
                                    ing_lines = ["## Active Ingredients"]
                                    if isinstance(active_ing, list):
                                        for ing in active_ing:
                                            if ing and str(ing).strip():
                                                ing_lines.append(f"- {ing}")
                                    else:
                                        ing_lines.append(f"- {active_ing}")
                                    md_blocks.append("\n".join(ing_lines))
                                extracted_text = "\n\n".join(md_blocks)

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

            page_data = {
                "page": 1,
                "text": extracted_text,
                "image_urls": [image_url] if image_url else [],
                "image_url": image_url,
                "s3_key": s3_key,
                "storage_key": s3_key,
                "image_reference": image_url
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
