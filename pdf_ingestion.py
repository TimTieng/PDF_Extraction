"""
pdf_ingestion.py

PURPOSE:
    Orchestrate Chile PDF extraction (via TableHelper) into the chile_budget_model
    logical model.

RESPONSIBILITIES:
    - Open PDF for metadata (PyMuPDF)
    - Extract service component tables via TableHelper (Template A/B)
    - Extract headers via TableHelper and cache them by page (0-based)
    - Map table rows into NationalBudget → Ministry → Unit → Program → Subtitle → Item → Subitem

NOTES:
    - Camelot table pages are 1-based.
    - Header cache uses 0-based pages (page0 = source_page - 1).
"""
# Standard Imports
from __future__ import annotations

import logging
import math
from camelot import logger
import pandas as pd
from pdb import main
import re
import warnings
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

# Custom/Special Imports
import chile_budget_model as cbm
from tablehelper import TableHelper

# PyMuPDF import: some installs use `pymupdf`, most use `fitz`
try:
    import pymupdf as _pymupdf  # type: ignore
except Exception:  # pragma: no cover
    import fitz as _pymupdf  # type: ignore


# CANONICAL BUDGET ROW STRUCTURE:
# For mapping rows into the logical model, we define a canonical structure that captures the key parsed components of a row. 
# This allows the classification and mapping logic to work with a consistent interface.

class CanonicalBudgetRow:
    """
    PURPOSE:
        Stores one normalized financial row extracted from a Chile budget PDF
        before the row is mapped into the logical model.

    NOTES:
        - This class is the canonical handoff object between extraction logic
          and logical-model population.
        - It stores both normalized values and raw extracted values so parsing
          issues can be debugged without re-opening the PDF.
        - This class should remain lightweight and data-oriented.

    PARAMETERS:
        source_pdf:
            Name or path of the source PDF.
        source_page_1based:
            Human-readable PDF page number (1-based).
        source_page_0based:
            Zero-based page index if needed by extraction tooling.
        source_schema:
            Extraction schema/template used, such as TEMPLATE_A or TEMPLATE_B.
        source_row_index:
            Row index from the extracted DataFrame or normalized row stream.
        row_kind:
            Normalized row classification, such as SECTION_HEADER,
            SUBTITLE_ROLLUP, ITEM_2, SUBITEM_3, TEXT_CONTINUATION, or UNKNOWN.
        bucket:
            Financial section such as INGRESOS, GASTOS, or UNKNOWN.
        ministry_name:
            Normalized ministry name from report header.
        ministry_code:
            Optional ministry code if available.
        unit_name:
            Normalized unit/service name from report header.
        unit_code:
            Optional unit code if available.
        program_name:
            Normalized program name from side header/report context.
        program_code:
            Optional program code if available.
        service_component:
            Optional top-level service component label.
        sub_component:
            Optional sub-component label.
        subtitle_code:
            Subtitle code from the financial hierarchy.
        subtitle_name:
            Subtitle description/name.
        item_code:
            Two-digit item code.
        item_name:
            Item description/name.
        subitem_code:
            Three-digit subitem/asignacion code.
        subitem_name:
            Subitem description/name.
        denominaciones:
            Primary normalized descriptive text for the row.
        glosa_reference_numbers:
            List of glosa note numbers referenced by this row.
        amount_clp_thousands:
            Normalized CLP amount in thousands.
        amount_usd_thousands:
            Normalized USD amount in thousands when present.
        is_text_continuation:
            Whether the row is a continuation of a previous row's text.
        continuation_target:
            Optional target level for continuation text, such as subtitle,
            item, or subitem.
        raw_sub_titulo:
            Raw extracted subtitle column value.
        raw_item_asig:
            Raw extracted item/asignacion column value.
        raw_denominaciones:
            Raw extracted denominaciones value.
        raw_glosa_no:
            Raw extracted glosa number field.
        raw_amount_clp:
            Raw extracted CLP amount text.
        raw_amount_usd:
            Raw extracted USD amount text.
        parser_notes:
            List of debug or parser notes collected during normalization.
        is_valid:
            Whether the row passed basic validation checks.
    """

    def __init__(
        self,
        source_pdf: str,
        source_page_1based: int,
        source_page_0based: int = None,
        source_schema: str = "UNKNOWN",
        source_row_index: int = None,
        row_kind: str = "UNKNOWN",
        bucket: str = "UNKNOWN",
        ministry_name: str = None,
        ministry_code: str = None,
        unit_name: str = None,
        unit_code: str = None,
        program_name: str = None,
        program_code: str = None,
        service_component: str = None,
        sub_component: str = None,
        subtitle_code: str = None,
        subtitle_name: str = None,
        item_code: str = None,
        item_name: str = None,
        subitem_code: str = None,
        subitem_name: str = None,
        denominaciones: str = None,
        glosa_reference_numbers: list[str] = None,
        amount_clp_thousands: float = None,
        amount_usd_thousands: float = None,
        is_text_continuation: bool = False,
        continuation_target: str = None,
        raw_sub_titulo: str = None,
        raw_item_asig: str = None,
        raw_denominaciones: str = None,
        raw_glosa_no: str = None,
        raw_amount_clp: str = None,
        raw_amount_usd: str = None,
        parser_notes: list[str] = None,
        is_valid: bool = True,
    ):
        self.source_pdf = source_pdf
        self.source_page_1based = source_page_1based
        self.source_page_0based = source_page_0based
        self.source_schema = source_schema
        self.source_row_index = source_row_index

        self.row_kind = row_kind
        self.bucket = bucket

        self.ministry_name = ministry_name
        self.ministry_code = ministry_code
        self.unit_name = unit_name
        self.unit_code = unit_code
        self.program_name = program_name
        self.program_code = program_code
        self.service_component = service_component
        self.sub_component = sub_component

        self.subtitle_code = subtitle_code
        self.subtitle_name = subtitle_name
        self.item_code = item_code
        self.item_name = item_name
        self.subitem_code = subitem_code
        self.subitem_name = subitem_name

        self.denominaciones = denominaciones
        self.glosa_reference_numbers = glosa_reference_numbers or []

        self.amount_clp_thousands = amount_clp_thousands
        self.amount_usd_thousands = amount_usd_thousands

        self.is_text_continuation = is_text_continuation
        self.continuation_target = continuation_target

        self.raw_sub_titulo = raw_sub_titulo
        self.raw_item_asig = raw_item_asig
        self.raw_denominaciones = raw_denominaciones
        self.raw_glosa_no = raw_glosa_no
        self.raw_amount_clp = raw_amount_clp
        self.raw_amount_usd = raw_amount_usd

        self.parser_notes = parser_notes or []
        self.is_valid = is_valid

    def to_dict(self) -> dict:
        """
        PURPOSE:
            Converts this canonical row into a standard dictionary for
            DataFrame creation, logging, export, or debugging.

        RETURNS:
            dict:
                Dictionary representation of this canonical row.
        """
        return {
            "source_pdf": self.source_pdf,
            "source_page_1based": self.source_page_1based,
            "source_page_0based": self.source_page_0based,
            "source_schema": self.source_schema,
            "source_row_index": self.source_row_index,
            "row_kind": self.row_kind,
            "bucket": self.bucket,
            "ministry_name": self.ministry_name,
            "ministry_code": self.ministry_code,
            "unit_name": self.unit_name,
            "unit_code": self.unit_code,
            "program_name": self.program_name,
            "program_code": self.program_code,
            "service_component": self.service_component,
            "sub_component": self.sub_component,
            "subtitle_code": self.subtitle_code,
            "subtitle_name": self.subtitle_name,
            "item_code": self.item_code,
            "item_name": self.item_name,
            "subitem_code": self.subitem_code,
            "subitem_name": self.subitem_name,
            "denominaciones": self.denominaciones,
            "glosa_reference_numbers": self.glosa_reference_numbers,
            "amount_clp_thousands": self.amount_clp_thousands,
            "amount_usd_thousands": self.amount_usd_thousands,
            "is_text_continuation": self.is_text_continuation,
            "continuation_target": self.continuation_target,
            "raw_sub_titulo": self.raw_sub_titulo,
            "raw_item_asig": self.raw_item_asig,
            "raw_denominaciones": self.raw_denominaciones,
            "raw_glosa_no": self.raw_glosa_no,
            "raw_amount_clp": self.raw_amount_clp,
            "raw_amount_usd": self.raw_amount_usd,
            "parser_notes": self.parser_notes,
            "is_valid": self.is_valid,
        }

    def __repr__(self) -> str:
        """
        PURPOSE:
            Returns a concise debug representation of the canonical row.
        """
        return (
            "CanonicalBudgetRow("
            f"page={self.source_page_1based}, "
            f"schema={self.source_schema}, "
            f"row_kind={self.row_kind}, "
            f"subtitle_code={self.subtitle_code}, "
            f"item_code={self.item_code}, "
            f"subitem_code={self.subitem_code}, "
            f"amount_clp_thousands={self.amount_clp_thousands}, "
            f"is_valid={self.is_valid})"
        )

# -----------------------------------------------------------------------------
# Row classification and parsing utilities functions to support ingestion
# -----------------------------------------------------------------------------

RowKind = Literal["SUBTITLE_ROLLUP", "ITEM_2", "SUBITEM_3", "TEXT_CONTINUATION", "UNKNOWN"]

_ITEM_RE = re.compile(r"\d+")

class ParsedItemAsig:
    """
    PURPOSE:
        Lightweight container representing the parsed structure of an
        'item_asig' cell from Template B tables.

    DESCRIPTION:
        The item_asig column may contain:
            - A 2-digit parent code (e.g., "01")
            - A 3-digit child code (e.g., "002")
            - Both parent and child in a single cell (e.g., "01 002")
            - Line-break separated values (e.g., "01\\n002")
            - Blank or malformed text

        This class stores the interpreted components in a normalized format.

    ATTRIBUTES:
        raw   : Original normalized string value of the cell.
        item2 : Parsed 2-digit parent code (if present).
        item3 : Parsed 3-digit child code (if present).

    NOTES:
        - Codes are extracted using digit detection only.
        - This class does NOT enforce hierarchy rules.
          It simply represents parsed structure.
    """

    def __init__(self, raw: str, item2: Optional[str] = None, item3: Optional[str] = None):
        self.raw = raw
        self.item2 = item2
        self.item3 = item3

    def __repr__(self) -> str:
        """
        PURPOSE:
            Provide developer-friendly debugging output.

        RETURNS:
            String representation of parsed structure.
        """
        return f"ParsedItemAsig(raw={self.raw!r}, item2={self.item2!r}, item3={self.item3!r})"


def _parse_item_asig(value: object) -> ParsedItemAsig:
    """
    PURPOSE:
        Parse the raw 'item_asig' value into structured 2-digit and 3-digit components.

    PARAMETERS:
        value : Raw cell value from DataFrame.

    RETURNS:
        ParsedItemAsig instance containing:
            - raw string
            - item2 (2-digit parent code if present)
            - item3 (3-digit child code if present)

    BEHAVIOR:
        - Extracts digit tokens using regex.
        - Prefers explicit 2-digit and 3-digit tokens when both exist.
        - If only one token exists:
            - 2 digits → interpreted as parent
            - 3 digits → interpreted as child

    NOTES:
        This function performs structural parsing only.
        It does not determine semantic row type.
    """
    s = _norm_str(value) or ""
    digits = _ITEM_RE.findall(s)

    item2 = None
    item3 = None

    # Prefer explicit 2-digit and 3-digit tokens if present
    for tok in digits:
        if len(tok) == 2 and item2 is None:
            item2 = tok
        elif len(tok) == 3 and item3 is None:
            item3 = tok

    # If only one token exists, interpret by length
    if len(digits) == 1:
        tok = digits[0]
        if len(tok) == 2:
            item2 = item2 or tok
        elif len(tok) == 3:
            item3 = item3 or tok

    return ParsedItemAsig(raw=s, item2=item2, item3=item3)


def _classify_row(
    st_code: Optional[str],
    parsed: ParsedItemAsig,
    denom: str,
    amt_clp: Optional[float],
    amt_usd: Optional[float],
    current_subtitle: Optional[str] = None,
) -> RowKind:
    """
    PURPOSE:
        Classify a financial table row into a structural hierarchy type.
    """
    has_amt = (amt_clp is not None) or (amt_usd is not None)
    has_denom = bool((denom or "").strip())
    denom_norm = (denom or "").strip()

    # 1) Subtitle roll-up row (explicit subtitle code present)
    if st_code and (parsed.item2 is None and parsed.item3 is None) and has_denom:
        return "SUBTITLE_ROLLUP"

    # 1a) Program section header / roll-up (INGRESOS / GASTOS)
    if (
        not st_code
        and (parsed.item2 is None and parsed.item3 is None)
        and has_denom
        and denom_norm.upper() in {"INGRESOS", "GASTOS"}
        and has_amt
    ):
        return "SECTION_HEADER"

    # 1b) Subtitle roll-up row (implicit via carry-forward context)
    if (
        not st_code
        and current_subtitle
        and (parsed.item2 is None and parsed.item3 is None)
        and has_denom
        and denom_norm.upper() in {"INGRESOS", "GASTOS"}
        and has_amt
    ):
        return "SUBTITLE_ROLLUP"

    # 2) Parent item (2-digit level)
    if parsed.item2 and not parsed.item3 and (has_denom or has_amt):
        return "ITEM_2"

    # 3) Child item (3-digit level)
    if parsed.item3 and (has_denom or has_amt):
        return "SUBITEM_3"

    # 4) Continuation text (wrapped rows)
    if has_denom or has_amt:
        return "TEXT_CONTINUATION"

    return "UNKNOWN"


def _log_row_debug(
    log: logging.Logger,
    kind: str,
    row: pd.Series,
    st_code: Optional[str],
    parsed: Optional[object],  # allow None until classifier is wired
    denom: str,
    amt_clp: Optional[float],
    amt_usd: Optional[float],
    ctx: Dict[str, str],
    every_n: int = 200,
    i: int = 0,
    raw_sub_titulo=None,
    raw_item_asig=None,
    subtitle_updated=False,
    item_updated=False,
) -> None:
    """
    PURPOSE:
        Emit structured debug logs for row classification + mapping context.

    PARAMETERS:
        log     : Logger.
        kind    : Row classification label (string).
        row     : DataFrame row.
        st_code : Row subtitle code (if present).
        parsed  : ParsedItemAsig (or None until classifier is wired).
        denom   : Denominaciones text.
        amt_clp : Parsed CLP amount.
        amt_usd : Parsed USD amount.
        ctx     : Context dictionary (ministry/unit/program/etc).
        every_n : Emit logs for every N rows (sampling).
        i       : Row counter used for sampling.

    RETURNS:
        None.

    NOTES:
        - Safe when parsed is None.
        - Only logs when logger level is DEBUG.
    """
    if every_n and i % every_n != 0:
        return

    item2 = parsed.get("item2") if isinstance(parsed, dict) else None
    item3 = parsed.get("item3") if isinstance(parsed, dict) else None
    page = row.get("source_page")

    log.debug(
        "ROW kind=%s page=%s st=%s item2=%s item3=%s upd_st=%s upd_item=%s "
        "amt_clp=%s amt_usd=%s denom=%r ctx=%s raw_st=%r raw_item_asig=%r",
        kind, page, st_code, item2, item3, subtitle_updated, item_updated,
        amt_clp, amt_usd, denom, ctx, raw_sub_titulo, raw_item_asig
    )


def _is_close(a: Optional[float], b: Optional[float], tol: float = 0.5) -> bool:
    """
    PURPOSE:
        Compare two numeric values with tolerance, handling None safely.

    NOTES:
        tol defaults to 0.5 since your numbers are in 'miles' (thousands) and
        rounding differences can occur in PDFs.
    """
    if a is None or b is None:
        return True
    return math.isclose(float(a), float(b), abs_tol=tol)


def _validate_rollups(
    nb: "cbm.NationalBudget",
    log: logging.Logger,
    tol: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    PURPOSE:
        Validate roll-up integrity:
            - Subtitle total vs sum(Item totals)
            - Item total vs sum(Subitem amounts)

    RETURNS:
        List of anomaly records (dicts) for debugging/QA.

    BEHAVIOR:
        - Skips comparisons when either side is missing (None).
        - Uses tolerance to allow for rounding differences.
    """
    anomalies: List[Dict[str, Any]] = []

    for m_key, ministry in (nb.ministries or {}).items():
        for u_key, unit in (getattr(ministry, "units", {}) or {}).items():
            for p_key, program in (getattr(unit, "programs", {}) or {}).items():

                # Program has income_subtitles / expense_subtitles in your model
                subtitle_maps = []
                if hasattr(program, "income_subtitles"):
                    subtitle_maps.append(("income", program.income_subtitles))
                if hasattr(program, "expense_subtitles"):
                    subtitle_maps.append(("expense", program.expense_subtitles))

                for bucket, subtitles in subtitle_maps:
                    for st_code, subtitle in (subtitles or {}).items():

                        # ---- Subtitle total vs sum(Item totals) ----
                        items = getattr(subtitle, "items", {}) or {}
                        sum_items_clp = None
                        sum_items_usd = None

                        # compute sums only if we have at least one numeric value
                        vals_clp = [getattr(it, "total_amount_pesos", None) for it in items.values()]
                        vals_usd = [getattr(it, "total_amount_usd", None) for it in items.values()]

                        if any(v is not None for v in vals_clp):
                            sum_items_clp = sum(v for v in vals_clp if v is not None)
                        if any(v is not None for v in vals_usd):
                            sum_items_usd = sum(v for v in vals_usd if v is not None)

                        st_clp = getattr(subtitle, "total_amount_pesos", None)
                        st_usd = getattr(subtitle, "total_amount_usd", None)

                        if sum_items_clp is not None and st_clp is not None and not _is_close(st_clp, sum_items_clp, tol=tol):
                            anomalies.append(
                                {
                                    "level": "subtitle",
                                    "bucket": bucket,
                                    "ministry": m_key,
                                    "unit": u_key,
                                    "program": p_key,
                                    "subtitle_code": st_code,
                                    "reported_clp": st_clp,
                                    "computed_clp": sum_items_clp,
                                }
                            )

                        if sum_items_usd is not None and st_usd is not None and not _is_close(st_usd, sum_items_usd, tol=tol):
                            anomalies.append(
                                {
                                    "level": "subtitle",
                                    "bucket": bucket,
                                    "ministry": m_key,
                                    "unit": u_key,
                                    "program": p_key,
                                    "subtitle_code": st_code,
                                    "reported_usd": st_usd,
                                    "computed_usd": sum_items_usd,
                                }
                            )

                        # ---- Item total vs sum(Subitem amounts) ----
                        for item_code, item in items.items():
                            subs = getattr(item, "subitems", {}) or {}
                            sub_vals_clp = [getattr(s, "amount_pesos", None) for s in subs.values()]
                            sub_vals_usd = [getattr(s, "amount_usd", None) for s in subs.values()]

                            item_clp = getattr(item, "total_amount_pesos", None)
                            item_usd = getattr(item, "total_amount_usd", None)

                            sum_sub_clp = None
                            sum_sub_usd = None
                            if any(v is not None for v in sub_vals_clp):
                                sum_sub_clp = sum(v for v in sub_vals_clp if v is not None)
                            if any(v is not None for v in sub_vals_usd):
                                sum_sub_usd = sum(v for v in sub_vals_usd if v is not None)

                            if sum_sub_clp is not None and item_clp is not None and not _is_close(item_clp, sum_sub_clp, tol=tol):
                                anomalies.append(
                                    {
                                        "level": "item",
                                        "bucket": bucket,
                                        "ministry": m_key,
                                        "unit": u_key,
                                        "program": p_key,
                                        "subtitle_code": st_code,
                                        "item_code": item_code,
                                        "reported_clp": item_clp,
                                        "computed_clp": sum_sub_clp,
                                    }
                                )

                            if sum_sub_usd is not None and item_usd is not None and not _is_close(item_usd, sum_sub_usd, tol=tol):
                                anomalies.append(
                                    {
                                        "level": "item",
                                        "bucket": bucket,
                                        "ministry": m_key,
                                        "unit": u_key,
                                        "program": p_key,
                                        "subtitle_code": st_code,
                                        "item_code": item_code,
                                        "reported_usd": item_usd,
                                        "computed_usd": sum_sub_usd,
                                    }
                                )

    if anomalies:
        log.warning("Roll-up validation found %d anomalies (tol=%s).", len(anomalies), tol)
        # Print first few to keep logs readable
        for a in anomalies[:10]:
            log.warning("ANOMALY: %s", a)
    else:
        log.info("Roll-up validation passed (no anomalies; tol=%s).", tol)

    return anomalies


# -----------------------------------------------------------------------------
# Normalization utilities
# -----------------------------------------------------------------------------
def _norm_str(value: Any) -> Optional[str]:
    """
    PURPOSE:
        Normalize a value to a stripped string or None.

    RETURNS:
        A stripped string, or None if blank/None.
    """
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _safe_str(value: Any, default: str) -> str:
    """
    PURPOSE:
        Convert a value to a non-empty string, or return a default.

    RETURNS:
        Non-empty string.
    """
    s = _norm_str(value)
    return s if s is not None else default


def _norm_int_str(value: Any) -> Optional[str]:
    """
    PURPOSE:
        Normalize a value to a digits-only string (preserves leading zeros).

    RETURNS:
        Digits-only string, or None.
    """
    s = _norm_str(value)
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits if digits else None


def _norm_float(value: Any) -> Optional[float]:
    """
    PURPOSE:
        Convert a value into a float safely (handles Chilean separators).
        Returns None for blanks and NaN.
    """
    if value is None:
        return None

    # handle pandas NaN / float('nan')
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except Exception:
        pass

    s = _norm_str(value)
    if not s:
        return None

    s = s.replace(".", "").replace(",", ".")
    try:
        f = float(s)
        if math.isnan(f):
            return None
        return f
    except ValueError:
        return None


def _extract_creation_date_from_pymupdf_metadata(metadata: Dict[str, Any]) -> Optional[datetime]:
    """
    PURPOSE:
        Extract and parse a creation date from PyMuPDF metadata if possible.

    RETURNS:
        datetime if parseable, else None.

    NOTES:
        PDFs may store dates like "D:20220101123456Z".
        We parse the digit prefix progressively.
    """
    if not metadata:
        return None

    raw = (
        metadata.get("creationDate")
        or metadata.get("CreationDate")
        or metadata.get("created")
        or metadata.get("Created")
    )
    if not raw:
        return None

    s = str(raw).strip()
    if s.startswith("D:"):
        s = s[2:]

    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 8:
        return None

    # Try increasingly permissive parses
    for fmt, n in [("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)]:
        try:
            return datetime.strptime(digits[:n], fmt)
        except ValueError:
            continue

    return None

# -----------------------------------------------------------------------------
# Model get-or-create helpers
# -----------------------------------------------------------------------------
def _get_or_create_ministry(nb: cbm.NationalBudget, name: str, code: str) -> cbm.Ministry:
    """
    PURPOSE:
        Get or create a Ministry under NationalBudget.

    RETURNS:
        Ministry instance.
    """
    key = name or code or "UNKNOWN_MINISTRY"
    if key not in nb.ministries:
        nb.ministries[key] = cbm.Ministry(ministry_name=name, ministry_code=code)
    return nb.ministries[key]


def _get_or_create_unit(ministry: cbm.Ministry, name: str, code: str) -> cbm.Unit:
    """
    PURPOSE:
        Get or create a Unit under a Ministry.

    RETURNS:
        Unit instance.
    """
    if not hasattr(ministry, "units") or ministry.units is None:
        ministry.units = {}

    key = name or code or "UNKNOWN_UNIT"
    if key not in ministry.units:
        ministry.units[key] = cbm.Unit(unit_name=name, unit_code=code)
    return ministry.units[key]


def _get_or_create_program(unit: cbm.Unit, name: str, code: str) -> cbm.Program:
    """
    PURPOSE:
        Get or create a Program under a Unit.

    RETURNS:
        Program instance.
    """
    key = name or code or "UNKNOWN_PROGRAM"
    if key not in unit.programs:
        unit.programs[key] = cbm.Program(program_name=name, program_code=code)
    return unit.programs[key]


def _get_or_create_subtitle(program: cbm.Program, code: str, name: str = "") -> cbm.Subtitle:
    """
    PURPOSE:
        Get or create a Subtitle under a Program.

    RETURNS:
        Subtitle instance.

    NOTES:
        This uses program.expense_subtitles by default (adjust if you later separate income vs expense).
    """
    key = code or name or "UNKNOWN_SUBTITLE"
    if key not in program.expense_subtitles:
        program.expense_subtitles[key] = cbm.Subtitle(name=name or None, code=code or None)
    return program.expense_subtitles[key]


def _get_or_create_item(subtitle: cbm.Subtitle, code: str, name: str = "") -> cbm.Item:
    """
    PURPOSE:
        Get or create an Item under a Subtitle.

    RETURNS:
        Item instance.
    """
    key = code or name or "UNKNOWN_ITEM"
    if key not in subtitle.items:
        subtitle.items[key] = cbm.Item(name=name or None, code=code or None)
    return subtitle.items[key]


def _create_subitem(name: str) -> cbm.Subitem:
    """
    PURPOSE:
        Create a Subitem instance, handling different constructor signatures.

    RETURNS:
        Subitem instance.

    NOTES:
        Some versions of your model may require extra args (code/note_num).
        We try common patterns.
    """
    try:
        return cbm.Subitem(name=name)  # simplest
    except TypeError:
        # common alternate signatures
        try:
            return cbm.Subitem(name=name, code=None, note_num=None)
        except TypeError:
            return cbm.Subitem(name=name, code="", note_num=None)


def _get_or_create_subitem(item: cbm.Item, name: str) -> cbm.Subitem:
    """
    PURPOSE:
        Get or create a Subitem under an Item.

    RETURNS:
        Subitem instance.
    """
    key = name or "UNKNOWN_SUBITEM"
    if key not in item.subitems:
        item.subitems[key] = _create_subitem(name=key)
    return item.subitems[key]


# -----------------------------------------------------------------------------
# Header cache builder
# -----------------------------------------------------------------------------
def _build_headers_by_page0(
    th: TableHelper,
    pdf_path: str,
    config: Dict[str, Any],
    df_all: pd.DataFrame,
    logger: logging.Logger,
) -> Dict[int, Dict[str, Any]]:
    """
    PURPOSE:
        Build a header cache keyed by 0-based page index.

    RETURNS:
        Dict[page0, header_dict] where header_dict has keys like 'main_header' and 'side_header'.

    FALLBACK:
        Returns empty dict if config/columns are missing or extraction fails.
    """
    header_cfg = config.get("header_areas", {}) or {}
    header_main_area = header_cfg.get("header_main")
    header_side_area = header_cfg.get("header_side")

    if not header_main_area or not header_side_area:
        logger.warning("Header areas missing in config['header_areas']; skipping header cache.")
        return {}

    if "source_page" not in df_all.columns:
        logger.warning("df_all missing 'source_page' column; skipping header cache.")
        return {}

    page0s = sorted({int(p) - 1 for p in df_all["source_page"].dropna().unique()})

    if not page0s:
        logger.warning("No source pages found; skipping header cache.")
        return {}

    # Camelot may warn when the header bbox has no table-like structure; suppress the noisy ones.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"No tables found in table area.*",
            category=UserWarning,
        )
        try:
            return th.extract_combined_report_headers_return_list(
                pdf_path=pdf_path,
                page_nums=page0s,
                header_main_area=header_main_area,
                header_side_area=header_side_area,
                debug=False,
            )
        except Exception as e:
            logger.warning(f"Header extraction failed; continuing without headers. Error: {e}")
            return {}


# CANONICAL BUDGET ROW HELPER FUNCTIONS
def _build_canonical_budget_row(
    row: pd.Series,
    *,
    pdf_path: str,
    headers_by_page0: Dict[int, Dict[str, Any]],
    row_index: int,
    current_subtitle: Optional[str] = None,
) -> CanonicalBudgetRow:
    """
    PURPOSE:
        Convert one extracted pandas row into a CanonicalBudgetRow object.

    PARAMETERS:
        row:
            One row from the combined extracted financial DataFrame.
        pdf_path:
            Path to the source PDF. Stored for provenance.
        headers_by_page0:
            Header cache keyed by 0-based page number.
        row_index:
            Row index from the combined extracted DataFrame.
        current_subtitle:
            Rolling subtitle context used by row classification logic.

    RETURNS:
        CanonicalBudgetRow:
            Normalized canonical intermediate row object.
    """

    # ---- Source provenance ----
    src_page_1 = row.get("source_page")
    page0 = int(src_page_1) - 1 if src_page_1 is not None else None

    # ---- Header context ----
    hdr = headers_by_page0.get(page0, {}) if page0 is not None else {}
    main = (hdr.get("main_header") or {}) if isinstance(hdr, dict) else {}
    side = (hdr.get("side_header") or {}) if isinstance(hdr, dict) else {}

    ministry_name = _safe_str(
        main.get("ministry") if isinstance(main, dict) else None,
        default="TEMP_MINISTRY",
    )

    # Side-header fields currently available in your pipeline
    partida = _safe_str(
        side.get("partida") if isinstance(side, dict) else None,
        default="000",
    )
    capitulo = _safe_str(
        side.get("capitulo") if isinstance(side, dict) else None,
        default="000",
    )
    programa = _safe_str(
        side.get("programa") if isinstance(side, dict) else None,
        default="000",
    )

    service_component = _safe_str(
    main.get("service_component") if isinstance(main, dict) else None,
    default=None,
    )

    sub_component = _safe_str(
        main.get("sub_component") if isinstance(main, dict) else None,
        default=None,
    )

    # ---- Raw extracted values ----
    raw_sub_titulo = row.get("sub_titulo")
    raw_item_asig = row.get("item_asig")
    raw_denominaciones = row.get("denominaciones")
    raw_glosa_no = row.get("glosa_no")
    raw_amount_clp = row.get("moneda_nacional_miles_de_$CLP")
    raw_amount_usd = row.get("moneda_ext_convertida_miles_USD")

    # ---- Normalized values ----
    st_code = _norm_int_str(raw_sub_titulo)
    denom = _safe_str(raw_denominaciones, default="").strip()

    amt_clp = _norm_float(raw_amount_clp)
    amt_usd = _norm_float(raw_amount_usd)

    parsed = _parse_item_asig(raw_item_asig)

    # ---- Classification ----
    kind = _classify_row(
        st_code=st_code,
        parsed=parsed,
        denom=denom,
        amt_clp=amt_clp,
        amt_usd=amt_usd,
        current_subtitle=current_subtitle,
    )

    # ---- Bucket / section inference ----
    bucket = "UNKNOWN"
    denom_upper = denom.upper()
    if denom_upper == "INGRESOS":
        bucket = "INGRESOS"
    elif denom_upper == "GASTOS":
        bucket = "GASTOS"

    # ---- Continuation inference ----
    is_text_continuation = (kind == "TEXT_CONTINUATION")
    continuation_target = None
    if is_text_continuation:
        if parsed.item3:
            continuation_target = "subitem"
        elif parsed.item2:
            continuation_target = "item"
        elif current_subtitle:
            continuation_target = "subtitle"

    # ---- Glosa note references (keep simple for v1) ----
    glosa_reference_numbers: list[str] = []
    glosa_raw = _safe_str(raw_glosa_no, default="")
    if glosa_raw:
        glosa_reference_numbers = re.findall(r"\d+", glosa_raw)

    # ---- Map parsed hierarchy fields ----
    subtitle_code = st_code
    subtitle_name = denom if kind == "SUBTITLE_ROLLUP" else None

    item_code = parsed.item2
    item_name = denom if kind == "ITEM_2" else None

    subitem_code = parsed.item3
    subitem_name = denom if kind == "SUBITEM_3" else None

    # ---- Validation / parser notes ----
    parser_notes: list[str] = []
    is_valid = True

    has_denom = bool(denom)
    has_amt = (amt_clp is not None) or (amt_usd is not None)
    has_code = bool(st_code) or bool(parsed.item2) or bool(parsed.item3)

    if not has_denom and not has_amt and not has_code:
        parser_notes.append("blank_row")
        is_valid = False

    if kind == "UNKNOWN":
        parser_notes.append("unknown_row_kind")

    if kind == "TEXT_CONTINUATION":
        parser_notes.append("text_continuation_row")

    return CanonicalBudgetRow(
        source_pdf=pdf_path,
        source_page_1based=int(src_page_1) if src_page_1 is not None else None,
        source_page_0based=page0,
        source_schema="UNKNOWN",  # keep simple for v1; improve later
        source_row_index=row_index,
        row_kind=kind,
        bucket=bucket,
        ministry_name=ministry_name,
        ministry_code=partida,
        unit_name=None,
        unit_code=capitulo,
        program_name=None,
        program_code=programa,
        service_component=service_component,
        sub_component=sub_component,
        subtitle_code=subtitle_code,
        subtitle_name=subtitle_name,
        item_code=item_code,
        item_name=item_name,
        subitem_code=subitem_code,
        subitem_name=subitem_name,
        denominaciones=denom,
        glosa_reference_numbers=glosa_reference_numbers,
        amount_clp_thousands=amt_clp,
        amount_usd_thousands=amt_usd,
        is_text_continuation=is_text_continuation,
        continuation_target=continuation_target,
        raw_sub_titulo=_safe_str(raw_sub_titulo, default=None),
        raw_item_asig=_safe_str(raw_item_asig, default=None),
        raw_denominaciones=_safe_str(raw_denominaciones, default=None),
        raw_glosa_no=_safe_str(raw_glosa_no, default=None),
        raw_amount_clp=_safe_str(raw_amount_clp, default=None),
        raw_amount_usd=_safe_str(raw_amount_usd, default=None),
        parser_notes=parser_notes,
        is_valid=is_valid,
    )


# -----------------------------------------------------------------------------
# Core orchestration
# -----------------------------------------------------------------------------
def build_chile_logical_model(
    pdf_path: str,
    config: Dict[str, Any],
    template_a_pages: list[int],
    template_b_pages: list[int],
    logger: Optional[logging.Logger] = None,
) -> cbm.NationalBudget:
    """
    PURPOSE:
        Build a Chile NationalBudget logical model from a PDF.

    PARAMETERS:
        pdf_path: Path to Chile PDF.
        config: YAML-derived config dict.
        template_a_pages: 1-based page numbers for Template A tables.
        template_b_pages: 1-based page numbers for Template B tables.
        logger: Optional logger.

    RETURNS:
        Populated NationalBudget object (may be partially populated if extraction is incomplete).
    """
    log = logger or logging.getLogger(__name__)
    th = TableHelper()

    # ---- PDF metadata (PyMuPDF) ----
    with _pymupdf.open(pdf_path) as doc:
        meta = doc.metadata or {}
        creation_dt = _extract_creation_date_from_pymupdf_metadata(meta)

    # ---- Root model ----
    admin = cbm.Admin(
        date_created=creation_dt,
        date_reviewed=datetime.now(),
        citation_list=[],
        classification=cbm.Classification.U,
    )

    country = _safe_str(config.get("country"), default="Chile")
    nb = cbm.NationalBudget(country=country, admin=admin)

    # ---- Extract tables ----
    df_a = pd.DataFrame()
    if template_a_pages:
        df_a = th.extract_service_component_tables_template_a_from_list(
            pdf_path=pdf_path,
            pages=template_a_pages,
            config=config,
        )

    df_b = pd.DataFrame()
    if template_b_pages:
        df_b = th.extract_service_component_tables_template_b_from_list(
            pdf_path=pdf_path,
            pages=template_b_pages,
            config=config,
        )

    # DEBUG  - log shapes and sample rows
    log.info(f"df_a shape: {df_a.shape}\n")
    log.info(f"df_b shape: {df_b.shape}\n")


    if df_a.empty and df_b.empty:
        log.warning("No tables extracted.")
        return nb
    

    df_all = pd.concat([df_a, df_b], ignore_index=True)

    # Debug: log row counts and page distribution before processing
    # log.info("df_all rows=%s", len(df_all))
    # log.info("df_all pages=%s", df_all["pages"].value_counts().to_dict())

    # ---- Build header cache once ----
    headers_by_page0 = _build_headers_by_page0(th, pdf_path, config, df_all, log)

    # print("\n--- SAMPLE HEADER ---")
    # if headers_by_page0:
    #     k = next(iter(headers_by_page0))
    #     print(headers_by_page0[k])
    # print("---------------------\n")


    # ---- Map rows into logical model ----
    current_subtitle: Optional[str] = None
    current_item: Optional[str] = None

    # DEBUG ADDR for row classification counts
    kind_counts = Counter()
    created_counts = Counter()  # track how many ministries/units/programs/items/subitems we create
    created_by_kind = Counter() # track which row kinds are creating the most entities (for debugging)


    # ---- DEBUG row counter (used for sampled debug logging) ----
    row_i = 0

    # for row_i, row in df_all.iterrows():
    for row_i, row in df_all.iterrows():

        # st_code = _norm_int_str(row.get("sub_titulo"))
        # denom = _safe_str(row.get("denominaciones"), default="").strip()

        # amt_clp = _norm_float(row.get("moneda_nacional_miles_de_$CLP"))
        # amt_usd = _norm_float(row.get("moneda_ext_convertida_miles_USD"))

        # parsed = _parse_item_asig(row.get("item_asig"))
        cb_row = _build_canonical_budget_row(
            row=row,
            pdf_path=pdf_path,
            headers_by_page0=headers_by_page0,
            row_index=int(row_i),
            current_subtitle=current_subtitle,
        )

        st_code = cb_row.subtitle_code
        denom = cb_row.denominaciones or ""
        amt_clp = cb_row.amount_clp_thousands
        amt_usd = cb_row.amount_usd_thousands
        parsed = _parse_item_asig(cb_row.raw_item_asig)
        kind = cb_row.row_kind
        page0 = cb_row.source_page_0based

        # BLANK ROW GUARD 
        # has_denom = bool(denom)
        # has_amt = (amt_clp is not None) or (amt_usd is not None)
        # has_code = bool(st_code) or bool(parsed.item2) or bool(parsed.item3)

        # if not has_denom and not has_amt and not has_code:
        #     continue

        if not cb_row.is_valid and "blank_row" in cb_row.parser_notes:
            continue

        # ---- 1 update rolling subtitle context FIRST ----
        if st_code:
            current_subtitle = st_code
            current_item = None  # reset item context on subtitle change

        # ---- 2 classify row USING current_subtitle context ----
        # kind = _classify_row(
        #     st_code=st_code,
        #     parsed=parsed,
        #     denom=denom,
        #     amt_clp=amt_clp,
        #     amt_usd=amt_usd,
        #     current_subtitle=current_subtitle,
        # )

        # DEBUG: skip TEXT_CONTINUATION rows for now (they don't drive structure, just add context/details to the last item)
        if kind == "TEXT_CONTINUATION":
            continue

        # DEBUG: count classifications
        kind_counts[kind] += 1

        # DEBUG: log UNKNOWN classifications for visibility (sampled)
        if kind == "UNKNOWN":
            log.warning(
                "UNKNOWN ROW page=%s st=%r parsed=%s denom=%r amt_clp=%r amt_usd=%r",
                page0,
                st_code,
                parsed,
                denom,
                amt_clp,
                amt_usd,
            )

        # DEBUG: count classifications
        kind_counts[kind] += 1

        if kind == "SECTION_HEADER":
            # Optional: track section if you want
            # current_section = denom_norm.upper()
            continue

        # ---- 3) update rolling item context ----
        if parsed.item2:
            current_item = parsed.item2

        # ---- Header-driven hierarchy (fallback to TEMP if headers missing) ----
        # src_page_1 = row.get("source_page")
        # page0 = int(src_page_1) - 1 if src_page_1 is not None else None

        # hdr = headers_by_page0.get(page0, {}) if page0 is not None else {}
        # main = (hdr.get("main_header") or {}) if isinstance(hdr, dict) else {}
        # side = (hdr.get("side_header") or {}) if isinstance(hdr, dict) else {}

        # ministry_name = _safe_str(main.get("ministry") if isinstance(main, dict) else None, default="TEMP_MINISTRY")
        # partida = _safe_str(side.get("partida") if isinstance(side, dict) else None, default="000")
        # capitulo = _safe_str(side.get("capitulo") if isinstance(side, dict) else None, default="000")
        # programa = _safe_str(side.get("programa") if isinstance(side, dict) else None, default="000")

        ministry_name = cb_row.ministry_name or "TEMP_MINISTRY"
        partida = cb_row.ministry_code or "000"
        capitulo = cb_row.unit_code or "000"
        programa = cb_row.program_code or "000"

        # ---- DEBUG: log row classification + context (sampled) ----
        # Note: if you haven't implemented _parse_item_asig/_classify_row yet,
        # you can temporarily log using item_code and st_code only.
        ctx = {
            "ministry": ministry_name,
            "partida": partida,
            "capitulo": capitulo,
            "programa": programa,
            "current_subtitle": current_subtitle,
            "current_item": current_item,
        }

        # TEMP debug classification (works with your existing variables)
        # When you add row-classifier later, replace this with:
        # parsed = _parse_item_asig(row.get("item_asig"))
        # kind = _classify_row(st_code, parsed, denom, amt_clp, amt_usd)
        parsed = _parse_item_asig(row.get("item_asig"))
        kind = _classify_row(st_code, parsed, denom, amt_clp, amt_usd)

        # DEBUG HELPERS for actionable print statemetns:
        raw_st = row.get("sub_titulo")
        raw_item = row.get("item_asig")

        subtitle_updated = bool(st_code)          # row had a new subtitle code
        item_updated = bool(parsed.item2)            # row had a new item code

        _log_row_debug(
            log=log,
            kind=kind,
            row=row,
            st_code=st_code,
            parsed=parsed,          # placeholder until classifier is wired
            denom=denom,
            amt_clp=amt_clp,
            amt_usd=amt_usd,
            ctx=ctx,
            every_n=200,
            i=row_i,
            raw_sub_titulo=raw_st,
            raw_item_asig=raw_item,
            subtitle_updated=subtitle_updated,
            item_updated=item_updated,
        )

        row_i += 1

        # ministry = _get_or_create_ministry(nb, ministry_name, partida)
        # unit_name = _safe_str(main.get("service_component"), default=f"CAPITULO_{capitulo}")
        # unit = _get_or_create_unit(ministry, name=unit_name, code=capitulo)

        # program = _get_or_create_program(unit, name=f"sub_component{programa}", code=programa)

        ministry = _get_or_create_ministry(nb, ministry_name, partida)

        unit_name = _safe_str(cb_row.service_component, default=f"CAPITULO_{capitulo}")
        unit = _get_or_create_unit(ministry, name=unit_name, code=capitulo)

        program_name = _safe_str(cb_row.sub_component, default=f"PROGRAMA_{programa}")
        program = _get_or_create_program(unit, name=program_name, code=programa)

        subtitle = None
        item = None
        subitem = None

        # ---------------------------------------------------------
        # SUBTITLE row
        # ---------------------------------------------------------
        if kind == "SUBTITLE_ROLLUP":
            subtitle_name = denom if denom else ""
            subtitle = _get_or_create_subtitle(
                program,
                code=current_subtitle,
                name=subtitle_name,
            )
            created_counts["subtitle"] += 1
            created_by_kind[f"subtitle@{kind}"] += 1

            if amt_clp is not None:
                subtitle.amount_pesos = (getattr(subtitle, "amount_pesos", None) or 0) + amt_clp
            if amt_usd is not None:
                subtitle.amount_usd = (getattr(subtitle, "amount_usd", None) or 0) + amt_usd

        # ---------------------------------------------------------
        # ITEM row
        # ---------------------------------------------------------
        elif kind == "ITEM_2":
            subtitle = _get_or_create_subtitle(
                program,
                code=current_subtitle,
                name="",
            )
            created_counts["subtitle"] += 1
            created_by_kind[f"subtitle@{kind}"] += 1

            item_name = denom if denom else ""
            item = _get_or_create_item(
                subtitle,
                code=current_item,
                name=item_name,
            )
            created_counts["item"] += 1
            created_by_kind[f"item@{kind}"] += 1

            if amt_clp is not None:
                item.amount_pesos = (getattr(item, "amount_pesos", None) or 0) + amt_clp
            if amt_usd is not None:
                item.amount_usd = (getattr(item, "amount_usd", None) or 0) + amt_usd

        # ---------------------------------------------------------
        # SUBITEM row
        # ---------------------------------------------------------
        elif kind == "SUBITEM_3":
            subtitle = _get_or_create_subtitle(
                program,
                code=current_subtitle,
                name="",
            )
            created_counts["subtitle"] += 1
            created_by_kind[f"subtitle@{kind}"] += 1

            if current_item:
                item = _get_or_create_item(
                    subtitle,
                    code=current_item,
                    name="",
                )
                created_counts["item"] += 1
                created_by_kind[f"item@{kind}"] += 1

                subitem_name = denom if denom else "UNNAMED_SUBITEM"
                subitem = _get_or_create_subitem(item, name=subitem_name)
                created_counts["subitem"] += 1
                created_by_kind[f"subitem@{kind}"] += 1

                if amt_clp is not None:
                    subitem.amount_pesos = (getattr(subitem, "amount_pesos", None) or 0) + amt_clp
                if amt_usd is not None:
                    subitem.amount_usd = (getattr(subitem, "amount_usd", None) or 0) + amt_usd

    # DEBUG: log final classification counts
    log.info("GLOBAL KIND COUNTS: %s", dict(kind_counts))
    log.info("CREATED BY KIND: %s", dict(created_by_kind))

    return nb
