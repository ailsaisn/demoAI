"""
Lightweight structure-aware summary chunker.
Zero heavy dependencies — only re + loguru.
Import: from app.rag.utils.summary_chunker import chunk_summary_markdown
"""
import re
from loguru import logger


def _clean_invalid_image_markdown(text: str) -> str:
    """
    Strips invalid/placeholder markdown image tags like ![Name](image_url), ![Name](), etc.
    Deduplicates consecutive image walls (e.g. 20 icons in a row from PDF slides), keeping at most 2 per block.
    """
    if not text:
        return text

    def _replace_img(match):
        alt_text = match.group(1)
        url = match.group(2).strip()
        if url.startswith("http://") or url.startswith("https://"):
            return f"![{alt_text}]({url})"
        # Strip invalid/placeholder image tag
        return ""

    cleaned = re.sub(r'!\[([^\]]*)\]\(([^)]*)\)', _replace_img, text)

    # Collapse consecutive image blocks: if 3+ images appear consecutively without text, keep only the first 2
    def _limit_img_wall(match):
        imgs = re.findall(r'!\[.*?\]\(https?://[^\s\)]+\)', match.group(0))
        if len(imgs) > 2:
            return "\n".join(imgs[:2])
        return match.group(0)

    cleaned = re.sub(r'(!\[.*?\]\(https?://[^\s\)]+\)\s*){3,}', _limit_img_wall, cleaned, flags=re.DOTALL)

    # Clean up double blank lines caused by removed tags
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _split_large_markdown_table(table_text: str, section_title: str = "", max_chars: int = 1500) -> list:
    """
    Splits a large Markdown table (> max_chars) safely by rows.
    Preserves the Table Column Headers + Delimiter + Section Title on EVERY sub-chunk
    so LLM and vector embeddings never lose column or section context.
    """
    lines = [l.strip() for l in table_text.strip().split("\n") if l.strip()]
    table_lines = [l for l in lines if l.startswith("|")]

    # If it's not a standard markdown table or too small, return as single chunk
    if len(table_lines) < 3:
        return [table_text]

    # Extract header line and delimiter line
    header_line = table_lines[0]
    delimiter_line = table_lines[1]
    data_rows = table_lines[2:]

    # Header block string to prepend
    table_header_prefix = f"{header_line}\n{delimiter_line}"

    sub_chunks = []
    current_rows = []
    current_len = len(table_header_prefix)

    for row in data_rows:
        if current_len + len(row) + 1 > max_chars and current_rows:
            # Reconstruct table sub-chunk
            rows_str = "\n".join(current_rows)
            full_sub_table = f"{table_header_prefix}\n{rows_str}"
            if section_title:
                full_sub_table = f"## {section_title}\n\n{full_sub_table}"
            sub_chunks.append(full_sub_table)

            current_rows = []
            current_len = len(table_header_prefix)

        current_rows.append(row)
        current_len += len(row) + 1

    if current_rows:
        rows_str = "\n".join(current_rows)
        full_sub_table = f"{table_header_prefix}\n{rows_str}"
        if section_title:
            full_sub_table = f"## {section_title}\n\n{full_sub_table}"
        sub_chunks.append(full_sub_table)

    return sub_chunks


def chunk_summary_markdown(
    summary: str,
    source_file: str = "",
    knowledge_id: str = "",
    batch_id: str = None,
    file_hash: str = "",
    title: str = "",
    doc_type: str = "GENERAL",
    categories: list = None,
    valid_from: str = None,
    valid_until: str = None,
    visibility_settings: dict = None,
    max_section_chars: int = 1200,
) -> list:
    """
    Structure-aware chunking of AI-reviewed Markdown summary.
    Splits by ## headings, extracts contextual image_url/sku/price per chunk.
    No embedding model required — instant execution.
    """
    if not summary or not summary.strip():
        return []

    # Clean invalid/placeholder image tags (e.g. ![Name](image_url)) before chunking
    summary = _clean_invalid_image_markdown(summary)
    if not summary or not summary.strip():
        return []

    # Apply Document Normalization / Structure Reconstruction to fix line-break fragmentation
    from app.rag.utils.normalizer import normalize_document_text
    summary = normalize_document_text(summary)
    if not summary or not summary.strip():
        return []

    categories = categories or []
    visibility_settings = visibility_settings or {
        "clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]
    }

    # Split summary into sections by ## headings
    raw_sections = re.split(r'(?=\n##\s+)', summary)
    sections = [s.strip() for s in raw_sections if s.strip() and len(s.strip()) >= 30]
    if not sections:
        sections = [summary.strip()]

    logger.info(f"Structure-aware chunking: split summary into {len(sections)} sections by ## headings.")

    # Lightweight meta builder
    def _build_meta(chunk_text, entity_name, chunk_index):
        meta = {
            "source_file": source_file,
            "entity": entity_name,
            "section": entity_name,
            "page": 1,
            "chunk_index": chunk_index,
            "knowledge_id": knowledge_id,
            "batch_id": batch_id,
            "file_hash": file_hash,
            "title": title,
            "document_type": doc_type,
            "clinics": visibility_settings.get("clinics", ["all"]),
            "doctor_types": visibility_settings.get("doctor_types", ["all"]),
            "doctors": visibility_settings.get("doctors", ["all"]),
        }
        heading_path = f"{title} > {entity_name}" if title and entity_name and title.lower() != entity_name.lower() else (entity_name or title)
        meta["heading_path"] = heading_path

        if doc_type == "TREATMENT":
            meta["treatment_name"] = title if title else entity_name
        else:
            meta["product_name"] = title if title else entity_name
        if chunk_text:
            # Extract image_url from markdown images in this chunk's text
            img_matches = re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', chunk_text)
            if img_matches:
                meta["image_url"] = img_matches[0]

            # Extract SKU
            sku_match = re.search(
                r'(?:-\s*\*\*SKU\*\*|\bSKU\b)\s*[:=]\s*([A-Za-z0-9\-\_]+)',
                chunk_text, re.IGNORECASE
            )
            if sku_match:
                meta["sku"] = sku_match.group(1).strip()

            # Extract price (clean numeric string stopping at comma/semicolon/newline)
            price_match = re.search(
                r'(?:-\s*\*\*(?:Harga|Price|Harga Normal|Harga Promo)\*\*|\b(?:Harga|Price)\b)\s*[:=]\s*([^\n\r,;]+)',
                chunk_text, re.IGNORECASE
            )
            if price_match:
                meta["price"] = price_match.group(1).strip()

            # Extract promo dates from chunk text itself (always used if found)
            date_matches = re.findall(r'\b(20\d{2}-\d{2}-\d{2})\b', chunk_text)
            if len(date_matches) >= 2:
                meta["valid_from"] = date_matches[0]
                meta["valid_until"] = date_matches[1]
            elif len(date_matches) == 1:
                meta["valid_until"] = date_matches[0]
            else:
                # Doc-level promo dates are ONLY inherited by chunks that mention promo content
                # Non-promo chunks (regular product info) must NOT get promo dates
                _PROMO_KEYWORDS = {
                    "promo", "diskon", "discount", "flash sale", "voucher", "cashback",
                    "special price", "harga promo", "berlaku", "valid until", "periode",
                    "penawaran", "potongan harga", "buy 1 get", "gratis", "free gift",
                }
                is_promo_chunk = any(kw in chunk_text.lower() for kw in _PROMO_KEYWORDS)
                if is_promo_chunk:
                    if valid_from:
                        meta["valid_from"] = valid_from
                    if valid_until:
                        meta["valid_until"] = valid_until

        if categories:
            str_cats = [c["name"] if isinstance(c, dict) else str(c) for c in categories]
            chunk_txt_lower = (chunk_text + " " + entity_name).lower()
            matched_cat = None

            # First: check if any category name is explicitly mentioned in chunk text
            for cat_name in str_cats:
                if cat_name.lower() in chunk_txt_lower:
                    matched_cat = cat_name
                    break

            # Second: if no direct match, check common keyword synonyms
            if not matched_cat:
                synonym_map = {
                    "acne": ["jerawat", "acne", "bha", "salicylic", "spot gel"],
                    "brightening": ["truwhite", "brightening", "cerah", "niacinamide", "vitamin c"],
                    "anti-aging": ["wrinkle", "retinol", "aging", "penuaan", "firming"],
                    "moisturizer": ["moisturizer", "pelembap", "hydrating", "hydration"],
                    "cleanser": ["facial wash", "cleansing", "cleanser", "sabun", "scrub"],
                }
                for cat_name in str_cats:
                    cat_key = cat_name.lower()
                    for syn_group_key, keywords in synonym_map.items():
                        if syn_group_key in cat_key:
                            if any(kw in chunk_txt_lower for kw in keywords):
                                matched_cat = cat_name
                                break
                    if matched_cat:
                        break

            if matched_cat:
                reordered = [matched_cat] + [c for c in str_cats if c != matched_cat]
                meta["category"] = matched_cat
                meta["categories"] = reordered
            else:
                meta["category"] = str_cats[0]
                meta["categories"] = str_cats
        return meta

    GENERIC_SUBHEADERS = {
        "warnings", "warning", "warnings & storage", "warnings and storage", "overview", "product overview", 
        "deskripsi & fungsi produk", "deskripsi produk", "fungsi produk", "active ingredients", "ingredients", 
        "bahan aktif", "kandungan & bahan aktif", "kandungan", "komposisi", "how to use", "cara penggunaan", 
        "cara pakai", "benefits", "benefit", "manfaat", "manfaat produk", "manfaat & penggunaan",
        "manfaat dan penggunaan", "manfaat & hasil yang diharapkan", "penggunaan", "keunggulan", "keunggulan produk", 
        "side effects", "efek samping", "setelah tindakan", "perawatan setelah tindakan", "aftercare", "pre-care", 
        "persiapan sebelum tindakan", "indikasi & target kondisi kulit", "indikasi", "kontraindikasi", 
        "informasi & parameter prosedur", "source mapping", "catatan", "informasi tambahan", "references", "referensi",
        "lampiran", "appendix", "faq", "pertanyaan umum", "syarat & ketentuan", "terms & conditions"
    }

    chunks = []
    chunk_idx = 0
    current_main_entity = title

    for section_text in sections:
        h2_match = re.match(r'^##\s+(?:\d+[\.\)]\s*)?(.+)', section_text)
        header_title = h2_match.group(1).strip() if h2_match else title

        clean_header = header_title.lower().strip(":-_#\t ")
        if clean_header in GENERIC_SUBHEADERS or len(clean_header) <= 3:
            entity_name = current_main_entity or title
        else:
            entity_name = header_title
            current_main_entity = header_title

        if len(section_text) <= max_section_chars:
            chunk_idx += 1
            chunks.append({
                "text": section_text,
                "metadata": _build_meta(section_text, entity_name, chunk_idx)
            })
        else:
            # Split long sections safely (handling large tables & paragraphs)
            paragraphs = [p.strip() for p in section_text.split("\n\n") if p.strip()]
            running_parts = []
            running_len = 0

            for para in paragraphs:
                # If paragraph itself is a giant Markdown Table (> max_section_chars)
                if para.startswith("|") and len(para) > max_section_chars:
                    # Flush any accumulated running_parts first
                    if running_parts and running_len >= 100:
                        chunk_idx += 1
                        sub_text = "\n\n".join(running_parts)
                        if entity_name and not sub_text.startswith("##"):
                            sub_text = f"## {entity_name}\n\n{sub_text}"
                        chunks.append({
                            "text": sub_text,
                            "metadata": _build_meta(sub_text, entity_name, chunk_idx)
                        })
                        running_parts = []
                        running_len = 0

                    # Split giant table safely row-by-row while preserving headers
                    sub_tables = _split_large_markdown_table(
                        table_text=para,
                        section_title=entity_name,
                        max_chars=max_section_chars
                    )
                    for sub_tbl in sub_tables:
                        chunk_idx += 1
                        chunks.append({
                            "text": sub_tbl,
                            "metadata": _build_meta(sub_tbl, entity_name, chunk_idx)
                        })
                    continue

                # Normal paragraph handling
                combined_len = running_len + len(para)
                if combined_len > max_section_chars and running_parts and running_len >= 100:
                    chunk_idx += 1
                    sub_text = "\n\n".join(running_parts)
                    if entity_name and not sub_text.startswith("##"):
                        sub_text = f"## {entity_name}\n\n{sub_text}"
                    chunks.append({
                        "text": sub_text,
                        "metadata": _build_meta(sub_text, entity_name, chunk_idx)
                    })
                    running_parts = []
                    running_len = 0

                running_parts.append(para)
                running_len += len(para)

            if running_parts:
                chunk_idx += 1
                sub_text = "\n\n".join(running_parts)
                if entity_name and not sub_text.startswith("##"):
                    sub_text = f"## {entity_name}\n\n{sub_text}"
                chunks.append({
                    "text": sub_text,
                    "metadata": _build_meta(sub_text, entity_name, chunk_idx)
                })

    logger.info(f"Structure-aware chunking complete: {len(chunks)} chunks from {len(sections)} sections.")
    return chunks
