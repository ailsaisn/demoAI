import math
import re
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger

from app.rag.canonical import (
    ImageType,
    ImageDisplayPolicy,
    ImageRelevance,
    ImageSemanticRole,
    ImageOrigin,
    PDFContext,
    ImageProvenance,
    generate_stable_image_id,
)

PRODUCT_SEMANTIC_KEYWORDS = {
    "serum", "cream", "krim", "gel", "cleanser", "toner", "sunscreen", "lotion",
    "oil", "mask", "moisturizer", "essence", "ampoule", "facial wash", "scrub",
    "peeling", "anti-aging", "brightening", "acne", "spf", "ml", "gr", "gram",
    "idr", "rp", "netto", "isi", "harga", "price"
}

LOGO_KEYWORDS = {
    "aesthetic clinic", "clinic by", "hospital", "brand", "pt", "copyright",
    "naturally speaking"
}


def compute_bbox_center(bbox: List[float]) -> Tuple[float, float]:
    """Computes (cx, cy) center coordinate from bbox [x0, y0, x1, y1]."""
    x0, y0, x1, y1 = bbox[:4]
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def compute_distance(pt1: Tuple[float, float], pt2: Tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)


class SpatialImageTextAssociator:
    """
    Associates embedded images and page regions with extracted OCR text entities
    using a multi-factor scoring formula:
      Score = 0.35 * distance + 0.25 * region + 0.25 * semantic_match + 0.15 * visual_feature
    """

    def __init__(self):
        pass

    def associate_page_elements(
        self,
        document_id: str,
        page_num: int,
        page_width: float,
        page_height: float,
        ocr_blocks: List[Dict[str, Any]],
        embedded_images: List[Dict[str, Any]],
        pdf_context: PDFContext = PDFContext.FLATTENED_DESIGN
    ) -> List[ImageProvenance]:
        """
        Analyzes embedded images on a page, evaluates spatial & semantic correlation
        with OCR text blocks, and generates deterministic ImageProvenance objects.
        """
        if not embedded_images:
            return []

        provenance_list: List[ImageProvenance] = []

        # 1. Detect Primary Product Title from OCR blocks
        primary_title = None
        for b in ocr_blocks:
            txt = (b.get("text") or "").strip()
            txt_l = txt.lower()
            y_top = b.get("bbox", [0, 0, 0, 0])[1]
            if len(txt) > 5 and y_top < (page_height * 0.45):
                has_brand = any(bw in txt_l for bw in LOGO_KEYWORDS)
                has_prod = any(pw in txt_l for pw in PRODUCT_SEMANTIC_KEYWORDS)
                if has_prod and not has_brand:
                    primary_title = txt
                    break

        if not primary_title:
            for b in ocr_blocks:
                txt = (b.get("text") or "").strip()
                txt_l = txt.lower()
                y_top = b.get("bbox", [0, 0, 0, 0])[1]
                if len(txt) > 5 and y_top < (page_height * 0.45) and not any(bw in txt_l for bw in LOGO_KEYWORDS):
                    primary_title = txt
                    break

        diag_len = math.sqrt(page_width ** 2 + page_height ** 2)

        for img in embedded_images:
            xref = img.get("xref", 0)
            rect = img.get("rect")  # fitz.Rect [x0, y0, x1, y1]
            if not rect:
                continue

            img_bbox = [rect.x0, rect.y0, rect.x1, rect.y1]
            img_cx, img_cy = compute_bbox_center(img_bbox)
            img_w = abs(rect.x1 - rect.x0)
            img_h = abs(rect.y1 - rect.y0)
            native_w = img.get("width", img_w)
            native_h = img.get("height", img_h)

            # Check if this image is a text container card (flat/horizontal box containing text blocks)
            text_blocks_inside = 0
            for b in ocr_blocks:
                b_cx, b_cy = compute_bbox_center(b.get("bbox", [0, 0, 0, 0]))
                if (rect.x0 - 5 <= b_cx <= rect.x1 + 5) and (rect.y0 - 5 <= b_cy <= rect.y1 + 5):
                    text_blocks_inside += 1

            aspect_ratio = native_h / max(1.0, native_w)
            pixel_area = native_w * native_h
            is_background_card = aspect_ratio < 0.75 or aspect_ratio > 4.0
            # Only flat/horizontal images with text inside are background container cards
            is_text_container = (aspect_ratio < 0.85) and (text_blocks_inside >= 1)
            is_margin_decor = img_cx < (page_width * 0.12) or img_cx > (page_width * 0.98)

            # 1. Distance Score: Proximity to primary title
            best_dist_score = 0.5
            if primary_title:
                for b in ocr_blocks:
                    if b.get("text") == primary_title:
                        t_cx, t_cy = compute_bbox_center(b.get("bbox", [0, 0, 0, 0]))
                        d = compute_distance((img_cx, img_cy), (t_cx, t_cy))
                        norm_d = min(1.0, d / max(1.0, diag_len))
                        best_dist_score = max(0.0, 1.0 - norm_d)
                        break

            # 2. Region Score: Alignment with right column or product display quadrant
            region_score = 0.5
            if img_cx > (page_width * 0.40):
                region_score = 0.85
            if (page_height * 0.15) < img_cy < (page_height * 0.85):
                region_score = min(1.0, region_score + 0.15)

            # 3. Semantic Match: Nearby OCR text within 35% diagonal
            nearby_texts = []
            for b in ocr_blocks:
                b_cx, b_cy = compute_bbox_center(b.get("bbox", [0, 0, 0, 0]))
                d_to_img = compute_distance((img_cx, img_cy), (b_cx, b_cy))
                if d_to_img < (diag_len * 0.35):
                    nearby_texts.append((b.get("text") or "").lower())

            combined_nearby = " ".join(nearby_texts)
            semantic_matches = sum(1 for kw in PRODUCT_SEMANTIC_KEYWORDS if kw in combined_nearby)
            semantic_score = min(1.0, semantic_matches * 0.25)

            # 4. Visual Feature Score: Aspect ratio & pixel area
            visual_feature_score = 0.05
            if not is_text_container and not is_background_card and not is_margin_decor:
                # Vertical packaging (bottle, tube, dropper)
                if 1.15 <= aspect_ratio <= 3.5 and pixel_area > 50000:
                    visual_feature_score = 1.0
                # Square packaging (jar, cream pot, product box)
                elif 0.80 <= aspect_ratio <= 1.25 and pixel_area > 80000:
                    visual_feature_score = 0.85

            # Combined Multi-Factor Association Score
            final_score = (
                0.35 * best_dist_score +
                0.25 * region_score +
                0.25 * semantic_score +
                0.15 * visual_feature_score
            )

            # Classification & Policy Assignment:
            # Genuine product packaging has high visual score (bottle/jar/box aspect ratio)
            is_genuine_product = visual_feature_score >= 0.85 and final_score >= 0.60

            if is_genuine_product:
                image_type = ImageType.PRODUCT
                display_policy = ImageDisplayPolicy.INCLUDE
                image_relevance = ImageRelevance.RELEVANT
                semantic_role = ImageSemanticRole.PRODUCT_REFERENCE
                linked_product = primary_title
                reason = (
                    f"Product packaging photo linked to '{primary_title}' "
                    f"(score={final_score:.2f}, aspect={aspect_ratio:.2f})"
                )
            else:
                is_logo_or_brand = any(logo_kw in combined_nearby for logo_kw in LOGO_KEYWORDS)
                image_type = ImageType.DOCUMENT_LOGO if (is_logo_or_brand and visual_feature_score < 0.5) else ImageType.DECORATIVE
                display_policy = ImageDisplayPolicy.EXCLUDE
                image_relevance = ImageRelevance.IRRELEVANT
                semantic_role = ImageSemanticRole.DOCUMENT_DECORATION
                linked_product = None
                reason = (
                    f"Excluded non-product asset (area={pixel_area}, aspect={aspect_ratio:.2f}, "
                    f"is_container={is_text_container}, score={final_score:.2f})"
                )

            target_url = img.get("target_url") or f"/api/storage/images/doc_{document_id}_p{page_num}_{xref}.jpeg"
            stable_id = generate_stable_image_id(
                document_id=document_id,
                page_or_sheet=page_num,
                target_url=target_url,
                image_index=xref
            )

            provenance = ImageProvenance(
                image_id=stable_id,
                document_id=document_id,
                source_document=img.get("source_document", ""),
                page_or_sheet=page_num,
                image_index=xref,
                target_url=target_url,
                alt_text=linked_product or "Product Image",
                image_origin=ImageOrigin.EMBEDDED_ASSET,
                extraction_source="embedded_image",
                pdf_context=pdf_context,
                image_type=image_type,
                image_relevance=image_relevance,
                display_policy=display_policy,
                semantic_role=semantic_role,
                linked_product=linked_product,
                confidence=round(final_score, 3),
                classification_reason=reason
            )

            provenance_list.append(provenance)
            logger.info(
                f"🏷️ [SPATIAL-ASSOCIATOR] Page {page_num} Img xref {xref} ({native_w}x{native_h}) "
                f"-> {provenance.image_type.value.upper()} [{provenance.display_policy.value.upper()}] "
                f"linked='{provenance.linked_product}' (score={final_score:.3f})"
            )

        return provenance_list
