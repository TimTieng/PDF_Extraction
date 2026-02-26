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
import pandas as pd
from pdb import main
import re
import warnings
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

    # Treat NaN as missing (see section 2)
    # (Assumes _norm_float handles NaN; if not, keep has_amt but amounts may be None.)

    # 1) Subtitle roll-up row (explicit subtitle code present)
    if st_code and (parsed.item2 is None and parsed.item3 is None) and has_denom:
        return "SUBTITLE_ROLLUP"

    # 1b) Subtitle roll-up row (implicit: subtitle context exists, but PDF shows blank sub_titulo cell)
    if (
        not st_code
        and current_subtitle
        and (parsed.item2 is None and parsed.item3 is None)
        and has_denom
        and denom_norm.upper() in {"INGRESOS", "GASTOS"}
        and has_amt
    ):
        return "SUBTITLE_ROLLUP"

    if parsed.item2 and not parsed.item3:
        return "ITEM_2"

    if parsed.item3:
        return "SUBITEM_3"

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

    # ---- DEBUG row counter (used for sampled debug logging) ----
    row_i = 0

    for _, row in df_all.iterrows():
        st_code = _norm_int_str(row.get("sub_titulo"))
        denom = _safe_str(row.get("denominaciones"), default="").strip()

        amt_clp = _norm_float(row.get("moneda_nacional_miles_de_$CLP"))
        amt_usd = _norm_float(row.get("moneda_ext_convertida_miles_USD"))

        parsed = _parse_item_asig(row.get("item_asig"))

        # ---- 1) update rolling subtitle context FIRST ----
        if st_code:
            current_subtitle = st_code
            current_item = None  # reset item context on subtitle change

        # ---- 2) classify row USING current_subtitle context ----
        kind = _classify_row(
            st_code=st_code,
            parsed=parsed,
            denom=denom,
            amt_clp=amt_clp,
            amt_usd=amt_usd,
            current_subtitle=current_subtitle,
        )

        # ---- 3) update rolling item context ----
        if parsed.item2:
            current_item = parsed.item2

        # ---- Header-driven hierarchy (fallback to TEMP if headers missing) ----
        src_page_1 = row.get("source_page")
        page0 = int(src_page_1) - 1 if src_page_1 is not None else None

        hdr = headers_by_page0.get(page0, {}) if page0 is not None else {}
        main = (hdr.get("main_header") or {}) if isinstance(hdr, dict) else {}
        side = (hdr.get("side_header") or {}) if isinstance(hdr, dict) else {}

        ministry_name = _safe_str(main.get("ministry") if isinstance(main, dict) else None, default="TEMP_MINISTRY")
        partida = _safe_str(side.get("partida") if isinstance(side, dict) else None, default="000")
        capitulo = _safe_str(side.get("capitulo") if isinstance(side, dict) else None, default="000")
        programa = _safe_str(side.get("programa") if isinstance(side, dict) else None, default="000")

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

        ministry = _get_or_create_ministry(nb, ministry_name, partida)
        unit_name = _safe_str(main.get("service_component"), default=f"CAPITULO_{capitulo}")
        unit = _get_or_create_unit(ministry, name=unit_name, code=capitulo)

        program = _get_or_create_program(unit, name=f"sub_component{programa}", code=programa)

        subtitle = _get_or_create_subtitle(program, code=current_subtitle, name="")

        # Only create subitems when we’re within an item context
        if current_item:
            item = _get_or_create_item(subtitle, code=current_item, name="")
            subitem_name = denom if denom else "UNNAMED_SUBITEM"
            subitem = _get_or_create_subitem(item, name=subitem_name)

            if amt_clp is not None:
                subitem.amount_pesos = (getattr(subitem, "amount_pesos", None) or 0) + amt_clp
            if amt_usd is not None:
                subitem.amount_usd = (getattr(subitem, "amount_usd", None) or 0) + amt_usd

    return nb
