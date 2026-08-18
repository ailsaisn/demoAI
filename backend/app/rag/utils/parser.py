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
                for idx, media_name in enumerate(media_files[:5], start=1):
                    img_bytes = z.read(media_name)
                    img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                    if img_ext in ["png", "jpg", "jpeg", "webp"]:
                        fname = f"docx_img_{idx}_{os.path.basename(media_name)}"
                        upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                        img_url = upload_res.get("image_url")
                        if img_url and pages:
                            clean_img_title = os.path.splitext(os.path.basename(file_path))[0]
                            pages[0]["text"] = f"![{clean_img_title}]({img_url})\n\n" + pages[0]["text"]
                            pages[0]["image_url"] = img_url
                            logger.info(f"🖼️ Extracted and uploaded embedded DOCX image '{media_name}' to MinIO -> {img_url}")
                            break
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
                img_markdowns = []
                for img_idx, img_info in enumerate(img_list[:3]):
                    xref = img_info[0]
                    base_img = doc.extract_image(xref)
                    img_bytes = base_img.get("image")
                    img_ext = base_img.get("ext", "png")
                    if img_bytes:
                        fname = f"pdf_p{i+1}_img{img_idx+1}.{img_ext}"
                        upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                        img_url = upload_res.get("image_url")
                        if img_url:
                            img_markdowns.append(f"![{fname}]({img_url})")
                if img_markdowns and i < len(pages):
                    pages[i]["text"] += "\n\n" + "\n".join(img_markdowns)
                    pages[i]["image_url"] = upload_res.get("image_url")
        except Exception as img_err:
            logger.debug(f"PDF embedded image extraction skipped/optional: {img_err}")

        return ParseResult(pages=pages, method="fast")

    # -------------------------------------------------------------------------
    # FAST EXTRACTION: EXCEL & CSV (.xlsx, .xls, .csv)
    # -------------------------------------------------------------------------
    def _parse_excel_fast(self, file_path: str) -> ParseResult:
        """Extract text and markdown tables from .xlsx, .xls, and .csv files using pandas."""
        import pandas as pd

        ext = os.path.splitext(file_path)[1].lower()
        pages = []

        try:
            if ext == ".csv":
                df = pd.read_csv(file_path)
                df = df.dropna(how="all")
                md_table = df.to_markdown(index=False)
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
                        md_table = df.to_markdown(index=False)
                        sheet_text = f"### Sheet: {sheet_name}\n\n{md_table}"
                        pages.append({
                            "page": page_idx,
                            "text": sheet_text
                        })

            if not pages:
                pages = [{"page": 1, "text": "Dokumen spreadsheet kosong."}]

            # Extract embedded images from .xlsx media parts and upload to MinIO
            if ext in [".xlsx", ".xlsm"]:
                try:
                    import zipfile
                    from app.services.storage import upload_image

                    with zipfile.ZipFile(file_path, 'r') as z:
                        media_files = [f for f in z.namelist() if f.startswith('xl/media/')]
                        for idx, media_name in enumerate(media_files[:5], start=1):
                            img_bytes = z.read(media_name)
                            img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                            if img_ext in ["png", "jpg", "jpeg", "webp"]:
                                fname = f"excel_img_{idx}_{os.path.basename(media_name)}"
                                upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                                img_url = upload_res.get("image_url")
                                if img_url and pages:
                                    clean_img_title = os.path.splitext(os.path.basename(file_path))[0]
                                    pages[0]["text"] = f"![{clean_img_title}]({img_url})\n\n" + pages[0]["text"]
                                    pages[0]["image_url"] = img_url
                                    logger.info(f"🖼️ Extracted and uploaded embedded Excel image '{media_name}' to MinIO -> {img_url}")
                                    break
                except Exception as img_err:
                    logger.debug(f"Excel embedded image extraction skipped: {img_err}")

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

                # Extract speaker notes if any
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        slide_texts.append(f"**Notes:** {notes}")

                if slide_texts:
                    full_slide_content = f"### Slide {slide_idx}: {slide_title}\n\n" + "\n".join(slide_texts)
                    pages.append({
                        "page": slide_idx,
                        "text": full_slide_content
                    })

            if not pages:
                pages = [{"page": 1, "text": "Presentasi PowerPoint kosong."}]

            # Extract embedded images from .pptx media parts and upload to MinIO
            try:
                import zipfile
                from app.services.storage import upload_image

                with zipfile.ZipFile(file_path, 'r') as z:
                    media_files = [f for f in z.namelist() if f.startswith('ppt/media/')]
                    for idx, media_name in enumerate(media_files[:5], start=1):
                        img_bytes = z.read(media_name)
                        img_ext = os.path.splitext(media_name)[1].lower().replace(".", "")
                        if img_ext in ["png", "jpg", "jpeg", "webp"]:
                            fname = f"pptx_img_{idx}_{os.path.basename(media_name)}"
                            upload_res = upload_image(img_bytes, fname, content_type=f"image/{img_ext}")
                            img_url = upload_res.get("image_url")
                            if img_url and pages:
                                clean_img_title = os.path.splitext(os.path.basename(file_path))[0]
                                pages[0]["text"] = f"![{clean_img_title}]({img_url})\n\n" + pages[0]["text"]
                                pages[0]["image_url"] = img_url
                                logger.info(f"🖼️ Extracted and uploaded embedded PPTX image '{media_name}' to MinIO -> {img_url}")
                                break
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
                model_name = db_model_name or os.getenv("VISION_MODEL_NAME") or getattr(settings, "openai_model_name", None) or "gpt-4o-mini"

                # Guard against mismatched OpenAI vs Gemini model name / base_url
                if api_key and api_key.startswith("sk-"):
                    if not model_name or "gemini" in model_name.lower() or not any(model_name.startswith(p) for p in ["gpt-", "o1", "o3", "chatgpt"]):
                        model_name = "gpt-4o-mini"
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
                        "You are an AI knowledge extraction assistant for the PT Arya Noble Knowledge Base.\n\n"
                        "Your task is to analyze the provided image and convert the useful information contained in the image into structured, searchable knowledge.\n\n"
                        "The image may contain any type of information, including but not limited to:\n"
                        "* Product images\n"
                        "* Product packaging\n"
                        "* Screenshots\n"
                        "* Web pages\n"
                        "* Browser interfaces\n"
                        "* Documents\n"
                        "* Tables\n"
                        "* Charts\n"
                        "* Diagrams\n"
                        "* Posters\n"
                        "* Forms\n"
                        "* Clinical or educational materials\n"
                        "* Photos containing relevant information\n"
                        "* Other visual information\n\n"
                        "Do NOT assume that the image is a product image.\n\n"
                        "## Primary Objective\n"
                        "Extract the information that is actually useful for the Knowledge Base.\n"
                        "First determine what kind of visual information is present, then dynamically extract the relevant information.\n\n"
                        "## Critical Rules\n"
                        "1. Do not invent information that cannot be supported by the image.\n"
                        "2. Do not hallucinate unreadable text.\n"
                        "3. If information is unclear, explicitly mark it as uncertain or null.\n"
                        "4. Do not force the image into a predefined schema.\n"
                        "5. Extract fields dynamically based on the actual content.\n"
                        "6. Preserve important terminology and names exactly when they are readable.\n"
                        "7. Do not make medical or clinical claims that are not explicitly supported by the image.\n"
                        "8. Distinguish between information directly visible in the image and AI interpretation.\n"
                        "9. The extracted information will be reviewed by an administrator before becoming approved Knowledge Base content.\n"
                        "10. The output must be useful for semantic search and RAG retrieval.\n\n"
                        "## Analyze the Image\n"
                        "Determine:\n"
                        "1. Content Type (product, screenshot, webpage, document, table, chart, diagram, infographic, form, poster, photograph, other)\n"
                        "2. Title (Generate a concise title representing the main subject. Prefer visible title if present.)\n"
                        "3. Summary (Concise summary based only on observable information.)\n"
                        "4. Extracted Information (Dynamically identify important information. Do NOT use a fixed schema.)\n"
                        "5. Searchable Knowledge (Concise textual representation of important information to be embedded & retrieved by RAG system.)\n"
                        "6. Visual Context (Describe visual info only when it contributes meaningful context.)\n"
                        "7. Uncertainty (Identify unreadable text, partially visible info, ambiguous info, cropped content, etc.)\n\n"
                        "## Output Format\n"
                        "Return valid JSON ONLY using the following structure:\n"
                        "{\n"
                        '  "content_type": "...",\n'
                        '  "title": "...",\n'
                        '  "summary": "...",\n'
                        '  "extracted_information": {},\n'
                        '  "searchable_knowledge": "...",\n'
                        '  "visual_context": "...",\n'
                        '  "uncertainties": []\n'
                        "}\n\n"
                        "Output valid JSON ONLY without any preamble or markdown wrapper."
                    )

                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt_text},
                                    {"type": "image_url", "image_url": {"url": data_uri}}
                                ]
                            }
                        ],
                        temperature=0.0,
                        max_tokens=2000
                    )
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

                            c_type = data.get("content_type", "image")
                            img_title = data.get("title") or os.path.splitext(file_name)[0]
                            summary = data.get("summary", "")
                            ext_info = data.get("extracted_information", {})
                            searchable_k = data.get("searchable_knowledge", "")
                            vis_context = data.get("visual_context", "")
                            uncertainties = data.get("uncertainties", [])

                            extracted_meta.update({
                                "content_type": c_type,
                                "title": img_title,
                                "summary": summary,
                                "extracted_information": ext_info,
                                "uncertainties": uncertainties,
                                "searchable_knowledge": searchable_k,
                                "visual_context": vis_context
                            })

                            # Build structured markdown combining original image reference and extracted knowledge
                            md_blocks = [f"![{img_title}]({image_url})\n\n# {img_title}"]
                            md_blocks.append(f"**Content Type**: {c_type}")

                            if summary:
                                md_blocks.append(f"## Summary\n{summary}")
                            if searchable_k:
                                md_blocks.append(f"## Searchable Knowledge\n{searchable_k}")

                            if isinstance(ext_info, dict) and ext_info:
                                info_lines = ["## Extracted Information"]
                                for k, v in ext_info.items():
                                    formatted_key = k.replace("_", " ").title()
                                    if isinstance(v, (list, dict)):
                                        info_lines.append(f"- **{formatted_key}**: {json.dumps(v, ensure_ascii=False)}")
                                    else:
                                        info_lines.append(f"- **{formatted_key}**: {v}")
                                md_blocks.append("\n".join(info_lines))

                            if vis_context:
                                md_blocks.append(f"## Visual Context\n{vis_context}")

                            if uncertainties:
                                u_lines = ["## Uncertainties & Verification Needed"]
                                for u in uncertainties:
                                    u_lines.append(f"- {u}")
                                md_blocks.append("\n".join(u_lines))

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
