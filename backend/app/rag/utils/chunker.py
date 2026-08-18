import re
from typing import List, Dict, Any
from loguru import logger
from langchain_experimental.text_splitter import SemanticChunker

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    HuggingFaceEmbeddings = None

try:
    from docling.chunking import HierarchicalChunker
    from docling_core.types.doc import DoclingDocument
except ImportError:
    DoclingDocument = Any
    HierarchicalChunker = None
    logger.warning("docling is not installed. Docling OCR chunking will be unavailable.")

from app.rag.utils.parser import ParseResult

from app.rag.services.embeddings import EmbeddingFactory

class CustomChunker:
    def __init__(self, embedding_model_name: str = None):
        logger.info("Initializing Custom Chunker (Structural + Semantic)...")
        
        # 1. Structural Chunker (Docling) — only for OCR path
        if HierarchicalChunker:
            self.structural_chunker = HierarchicalChunker()
        else:
            self.structural_chunker = None
            
        # 2. Semantic Chunker using active EmbeddingFactory
        try:
            logger.info("Loading active EmbeddingAdapter for Semantic Chunking...")
            self.embeddings = EmbeddingFactory.get_embeddings_adapter()
            self.semantic_splitter = SemanticChunker(
                self.embeddings, 
                breakpoint_threshold_type="percentile"
            )
        except Exception as e:
            logger.warning(f"SemanticChunker using fallback: {e}")
            self.semantic_splitter = None

    # =========================================================================
    # KNOWN SECTION HEADERS (shared across both paths)
    # =========================================================================
    KNOWN_SECTIONS = {
        "product name", "brand", "category", "description", "target skin type",
        "active ingredients", "ingredients", "benefits", "indications",
        "contraindications", "how to use", "directions", "warnings", "storage",
        "reference", "references", "product overview", "product information",
        "target patient", "dosage", "composition", "packaging", "shelf life",
        "mechanism of action", "clinical studies", "side effects",
        "precautions", "interactions", "formulation",
    }

    # =========================================================================
    # DOCLING PATH: Existing logic for DoclingDocument objects
    # =========================================================================
    def _extract_docling_headings(self, chunk: Any) -> List[str]:
        """Extracts the heading hierarchy from a docling chunk's metadata."""
        headings = []
        if hasattr(chunk, "meta") and hasattr(chunk.meta, "headings"):
            if chunk.meta.headings:
                for h in chunk.meta.headings:
                    headings.append(str(h))
        return headings

    def _extract_docling_page(self, chunk: Any) -> int:
        """Extracts the page number from a docling chunk's metadata."""
        if hasattr(chunk, "meta") and hasattr(chunk.meta, "doc_items") and chunk.meta.doc_items:
            first_item = chunk.meta.doc_items[0]
            if hasattr(first_item, "prov") and first_item.prov:
                prov_item = first_item.prov[0]
                if hasattr(prov_item, "page_no"):
                    return int(prov_item.page_no)
        return 1

    def _chunk_docling_document(self, doc, max_length_for_semantic: int = 500) -> List[Dict]:
        """Original Docling HierarchicalChunker path for OCR-parsed documents."""
        if not self.structural_chunker:
            logger.error("Structural chunker unavailable for Docling document.")
            return []

        logger.info("Applying Docling HierarchicalChunker to Document Tree...")
        try:
            structural_chunks = list(self.structural_chunker.chunk(doc))
        except Exception as e:
            logger.error(f"Failed to chunk document hierarchically: {e}")
            return []
            
        logger.info(f"Created {len(structural_chunks)} structural chunks from Document Tree.")
        
        processed_chunks = []
        current_section = "Root"
        
        for sc in structural_chunks:
            text = sc.text if hasattr(sc, "text") else str(sc)
            text_strip = text.strip()
            if not text_strip:
                continue
                
            headings = self._extract_docling_headings(sc)
            page = self._extract_docling_page(sc)
            
            is_table = any(type(item).__name__ == "TableItem" for item in sc.meta.doc_items) if hasattr(sc, "meta") and hasattr(sc.meta, "doc_items") and sc.meta.doc_items else False
            is_picture = any(type(item).__name__ == "PictureItem" for item in sc.meta.doc_items) if hasattr(sc, "meta") and hasattr(sc.meta, "doc_items") and sc.meta.doc_items else False
            
            if is_table:
                chunk_type = "TableChunk"
            elif is_picture:
                chunk_type = "PictureChunk"
            else:
                chunk_type = "TextChunk"
            
            if not headings and text_strip.lower() in self.KNOWN_SECTIONS:
                current_section = text_strip.upper()
                continue
                
            if headings:
                section = headings[-1].upper()
            else:
                section = current_section
                
            base_metadata = {
                "headings": headings,
                "section": section,
                "chunk_type": chunk_type,
                "page": page
            }
            
            processed_chunks.append({
                "text": text,
                "metadata": base_metadata
            })

        return self._merge_and_split(processed_chunks, max_length_for_semantic)

    # =========================================================================
    # FAST PATH: Document -> Section -> Entity/Treatment -> Semantic Chunking
    # =========================================================================
    def _split_large_table(self, table_lines: List[str], max_rows_per_chunk: int = 8) -> List[str]:
        """
        Splits a large markdown table into smaller valid sub-tables,
        ensuring each chunk has the complete table header and delimiter.
        """
        if len(table_lines) <= 3:
            return ["\n".join(table_lines)]

        header = table_lines[0]
        delimiter = table_lines[1]
        data_rows = table_lines[2:]

        sub_tables = []
        for i in range(0, len(data_rows), max_rows_per_chunk):
            chunk_rows = data_rows[i:i + max_rows_per_chunk]
            sub_table = "\n".join([header, delimiter] + chunk_rows)
            sub_tables.append(sub_table)

        return sub_tables

    def _chunk_fast_pages(self, pages: List[Dict], max_length_for_semantic: int = 600) -> List[Dict]:
        """
        Hierarchical Chunking:
        Document -> Section (H1/H2) -> Entity/Treatment (H3/H4/Numbered) -> Semantic Chunks.
        Ensures 1 chunk = 1 complete informational unit answering 1 doctor intent.
        """
        logger.info(f"⚡ Hierarchical chunking {len(pages)} pages (Document -> Section -> Entity -> Semantic Chunks)...")

        processed_chunks = []
        current_section = "General"
        current_entity = ""

        # Regex patterns for hierarchical boundaries
        section_h1_h2_pattern = re.compile(r"^(?:#{1,2}\s+|\d+\.\s+[A-Z])", re.IGNORECASE)
        entity_h3_h4_pattern = re.compile(r"^(?:#{3,4}\s+|\d+\.\d+\s+|\*\*[A-Z0-9\s\.\-]+\*\*)", re.IGNORECASE)

        for page_data in pages:
            page_num = page_data.get("page", 1)
            page_image_url = page_data.get("image_url")
            page_text = page_data.get("text", "").strip()
            if not page_text:
                continue

            lines = page_text.split("\n")
            current_entity_lines = []
            current_table_lines = []

            def _build_meta(chunk_type: str) -> Dict[str, Any]:
                meta = {
                    "headings": [current_section, current_entity] if current_entity else [current_section],
                    "section": current_section,
                    "entity": current_entity,
                    "chunk_type": chunk_type,
                    "page": page_num
                }
                if page_image_url:
                    meta["image_url"] = page_image_url
                return meta

            def flush_entity_block():
                nonlocal current_entity_lines
                if not current_entity_lines:
                    return

                block_text = "\n".join(current_entity_lines).strip()
                if not block_text:
                    current_entity_lines = []
                    return

                # If block is very short (< 80 chars) and has no specific entity, buffer it to combine with next block
                if len(block_text) < 80 and not current_entity:
                    return

                # If entity block is within target size (~600-1200 chars), keep as 1 self-contained unit
                if len(block_text) <= 1200:
                    processed_chunks.append({
                        "text": block_text,
                        "metadata": _build_meta("EntityChunk" if current_entity else "TextChunk")
                    })
                else:
                    # Split long entity into logical semantic sub-units (e.g. paragraphs / double newlines)
                    paragraphs = [p.strip() for p in block_text.split("\n\n") if p.strip()]
                    if len(paragraphs) > 1:
                        running_sub = []
                        for p in paragraphs:
                            running_sub.append(p)
                            sub_text = "\n\n".join(running_sub)
                            if len(sub_text) >= 500:
                                # Prepend entity header if not already in sub-text
                                if current_entity and not sub_text.startswith("#"):
                                    sub_text = f"### {current_entity}\n\n{sub_text}"
                                processed_chunks.append({
                                    "text": sub_text,
                                    "metadata": _build_meta("EntityChunk" if current_entity else "TextChunk")
                                })
                                running_sub = []
                        if running_sub:
                            sub_text = "\n\n".join(running_sub)
                            if current_entity and not sub_text.startswith("#"):
                                sub_text = f"### {current_entity}\n\n{sub_text}"
                            processed_chunks.append({
                                "text": sub_text,
                                "metadata": _build_meta("EntityChunk" if current_entity else "TextChunk")
                            })
                    else:
                        processed_chunks.append({
                            "text": block_text,
                            "metadata": _build_meta("EntityChunk" if current_entity else "TextChunk")
                        })

                current_entity_lines = []

            def flush_table_block():
                nonlocal current_table_lines
                if not current_table_lines:
                    return

                if len(current_table_lines) > 10:
                    sub_tables = self._split_large_table(current_table_lines, max_rows_per_chunk=6)
                    for tbl in sub_tables:
                        processed_chunks.append({
                            "text": tbl,
                            "metadata": _build_meta("TableChunk")
                        })
                else:
                    processed_chunks.append({
                        "text": "\n".join(current_table_lines),
                        "metadata": _build_meta("TableChunk")
                    })
                current_table_lines = []

            for line in lines:
                line_strip = line.strip()
                if not line_strip:
                    if current_table_lines:
                        flush_table_block()
                    continue

                # 1. Detect Markdown Table Row
                is_table_row = line_strip.startswith("|") and line_strip.endswith("|")
                if is_table_row:
                    flush_entity_block()
                    current_table_lines.append(line_strip)
                    continue
                else:
                    if current_table_lines:
                        flush_table_block()

                # 2. Detect Major Section (H1 / H2 / 1. Title)
                if section_h1_h2_pattern.match(line_strip) and not is_table_row:
                    flush_entity_block()
                    clean_sec = line_strip.lstrip("#: ").strip()
                    if clean_sec:
                        current_section = clean_sec
                        current_entity = ""
                    current_entity_lines.append(line_strip)
                    continue

                # 3. Detect Entity / Treatment / Product (H3 / H4 / 1.1 Item)
                if entity_h3_h4_pattern.match(line_strip) and not is_table_row:
                    flush_entity_block()
                    clean_ent = line_strip.lstrip("#: *").rstrip("*").strip()
                    if clean_ent:
                        current_entity = clean_ent
                    current_entity_lines.append(line_strip)
                    continue

                # 4. Regular content line / bullet point
                current_entity_lines.append(line_strip)

            # Flush remaining lines
            flush_entity_block()
            flush_table_block()

        logger.info(f"Hierarchical chunking complete: generated {len(processed_chunks)} granular, entity-aware chunks.")
        return processed_chunks

    # =========================================================================
    # PUBLIC API: Unified entry point
    # =========================================================================
    def chunk_document(self, parse_result, max_length_for_semantic: int = 600) -> List[Dict]:
        """
        Unified chunking entry point. Accepts either:
        - ParseResult (from new smart parser)
        - DoclingDocument (backward compatibility)
        
        Automatically routes to hierarchical chunking.
        """
        if isinstance(parse_result, ParseResult):
            if parse_result.is_fast:
                return self._chunk_fast_pages(parse_result.pages, max_length_for_semantic)
            elif parse_result.is_docling and parse_result.docling_doc:
                return self._chunk_docling_document(parse_result.docling_doc, max_length_for_semantic)
            else:
                logger.error("ParseResult has no usable data.")
                return []

        if DoclingDocument and isinstance(parse_result, DoclingDocument):
            return self._chunk_docling_document(parse_result, max_length_for_semantic)

        logger.warning(f"Unknown parse_result type: {type(parse_result)}. Attempting Docling chunking.")
        return self._chunk_docling_document(parse_result, max_length_for_semantic)
