"""
Page schema — the canonical unit of OCR output for a single PDF page.

Architecture reference — architecture.md §4.2:
'patient_id ties the page to its owning Patient.  document_name and
page_number together address the page within a document and are the
provenance keys that Evidence records carry forward.  page_image_path
points to the stored image for a single page; the OCR Retry Tool uses
this path when retrying pages with low ocr_confidence.  raw_text is the
OCR-recognized text from which Evidence is extracted, and the provenance
pair (source_start_char, source_end_char) on each Evidence indexes into
raw_text.  ocr_status tracks the OCR lifecycle for the page.
ocr_confidence is the signal used to populate
AgentState.low_confidence_pages.'
"""

from pydantic import BaseModel, Field


class Page(BaseModel):
    """
    OCR output for a single PDF page.

    A Page is addressed within the system by the composite key
    (patient_id, document_name, page_number).  It is the only surface
    from which Evidence is extracted (§3.3 architecture) and the only
    surface the OCR Retry Tool writes back to.
    """

    patient_id: str = Field(
        ...,
        description=(
            "Reference to the owning Patient record.  Together with "
            "document_name and page_number this forms the composite address "
            "of the page within the system."
        ),
    )
    document_name: str = Field(
        ...,
        description=(
            "Name of the source document this page belongs to.  Carried "
            "forward as a provenance key on every Evidence record extracted "
            "from this page."
        ),
    )
    page_number: int = Field(
        ...,
        ge=1,
        description=(
            "1-based position of this page within its document.  Carried "
            "forward as a provenance key on every Evidence record extracted "
            "from this page."
        ),
    )
    page_image_path: str = Field(
        ...,
        description=(
            "File-system path to the stored image for this page.  The OCR "
            "Retry Tool reads this path from AgentState.low_confidence_pages "
            "and re-runs OCR on the image without re-rendering the full PDF."
        ),
    )
    raw_text: str = Field(
        ...,
        description=(
            "OCR-recognized text for this page.  Evidence extraction reads "
            "this field, and the provenance span (source_start_char, "
            "source_end_char) on each Evidence record indexes into this string."
        ),
    )
    ocr_status: str = Field(
        ...,
        description=(
            "Current OCR lifecycle status for this page, maintained by the "
            "OCR Tool (FR-4a).  Tracks whether OCR is pending, complete, or "
            "requires a retry."
        ),
    )
    ocr_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence score for the OCR output on this page, in the range "
            "[0.0, 1.0].  Pages below the configured threshold are added to "
            "AgentState.low_confidence_pages and become candidates for "
            "targeted OCR retry."
        ),
    )
