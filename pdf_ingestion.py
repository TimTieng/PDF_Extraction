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

from __future__ import annotations

import logging
from pdb import main
import warnings
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd

import chile_budget_model as cbm
from tablehelper import TableHelper

# PyMuPDF import: some installs use `pymupdf`, most use `fitz`
try:
    import pymupdf as _pymupdf  # type: ignore
except Exception:  # pragma: no cover
    import fitz as _pymupdf  # type: ignore


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

    RETURNS:
        Float, or None if not parseable.
    """
    s = _norm_str(value)
    if not s:
        return None

    # Chile number formatting often uses '.' for thousands, ',' for decimals
    s = s.replace(".", "").replace(",", ".")

    try:
        return float(s)
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

    print("\n--- SAMPLE HEADER ---")
    if headers_by_page0:
        k = next(iter(headers_by_page0))
        print(headers_by_page0[k])
    print("---------------------\n")


    # ---- Map rows into logical model ----
    current_subtitle: Optional[str] = None
    current_item: Optional[str] = None

    for _, row in df_all.iterrows():
        st_code = _norm_int_str(row.get("sub_titulo"))
        item_code = _norm_int_str(row.get("item_asig"))
        denom = _safe_str(row.get("denominaciones"), default="")

        amt_clp = _norm_float(row.get("moneda_nacional_miles_de_$CLP"))
        amt_usd = _norm_float(row.get("moneda_ext_convertida_miles_USD"))

        # rolling hierarchy from table values
        if st_code:
            current_subtitle = st_code
            current_item = None

        if item_code:
            current_item = item_code

        if not current_subtitle:
            continue

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

        ministry = _get_or_create_ministry(nb, ministry_name, partida)
        unit_name = _safe_str(main.get("service_component"), default=f"CAPITULO_{capitulo}")
        unit = _get_or_create_unit(ministry, name=unit_name, code=capitulo)

        program = _get_or_create_program(unit, name=f"PROGRAMA_{programa}", code=programa)

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
