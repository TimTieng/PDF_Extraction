"""
CREATED: 30 JAN 2026
AUTHOR: @GAMBIT
JIRA TICKET: TBD

PURPOSE:
    The TableHelper Class will contain several methods and helper functions to assist in structuring and formatting table content 
    found within the Chile Budget PDF document 
    
DATA SOURCE:
    1. Ley de Presupuestos ano 2025 para el sector publico: "Chile total budget_articles-363446_doc_pdf.pdf"

TYPE OF SCRIPT: SUPPORT SCRIPT

EXECUTION:
    This is a non executable script. 
    
NOTES:
    1. Current  pdf_extract reads in the ENTIRE pdf page. It may be easier to ingest logical sections of the page from my pov
    2. adding pyright: ignore[reportPrivateImportUsage]
    
CONCEPTUAL PROCESS:
    1. Ingest content of the pdf document in logical sections/groups based on the content of each page:
        - Main Report Header
        - Side Report Header in NE Corner of PDF
        - Financial Tables
        - Glosas pages which comes after the pdf tables page
"""
# Adding for read_pdf privatimportusage warning
# pyright: reportPrivateImportUsage=false

# Standard Imports
import camelot
import pymupdf
import logging
import pandas as pd
from typing import Any, Optional, List, Dict, Tuple,Union
import re

# Specialty/Custom Libraries

logger = logging.getLogger(__name__)
HeaderValue = Union[str,List[str], int, None]
Number = Union[int,float]

class TableHelper:
    """
    Class that will have several methods designed to help structuring of table content found in the chile budget pdf file
    """
    # ---------- HELPER FUNCTION SECTION  ----------
    def _is_side_header_cell(self, s:str)-> bool:
        """
        Docstring for _is_side_header_cell
        
        :param self: Description
        :param s: Description
        :type s: str
        :return: Description
        :rtype: bool
        """
        if not s:
            return False
        
        t = self._normalize_whitespace(str(s)).strip()
        
        # Updates to fix  FACH Programa Fidae (o1) bug on pdf page 556
        return bool(re.fullmatch(r"\b(PARTIDA|CAP[IÍ]TULO|PROGRAMA)\s*:?", t, flags=re.IGNORECASE))


    def _lines_from_camelot_df(self, df, *, drop_side_header:bool = True) -> List[str]:
        """
        PURPOSE:
            Converts Camelot's extracted grid DataFrame into a list of readable text lines.
            This helps treat the header area like "lines of text" instead of table cells.
 
        PARAMETERS:
            df: A pandas DataFrame returned by Camelot (t.df), containing strings.
 
        RETURNS:
            A list of non-empty text lines extracted from the grid, in reading order.
        """
        lines: List[str] = []

        # Row-major traversal; join non-empty cells per row
        for _, row in df.iterrows():
            cells = [str(x).strip() for x in row.tolist()]
            cells = [c for c in cells if c and c.lower() != "nan"]

            if drop_side_header:
                # Only drop the label cells when we are extracting MAIN header
                cells = [c for c in cells if not self._is_side_header_cell(c)]

            if not cells:
                continue

            # Often header content is split across cells; join with space
            line = " ".join(cells)
            line = re.sub(r"\s+", " ", line).strip()

            if line:
                lines.append(line)

        return lines
    

    def _clean_lines(self, text: str) -> List[str]:
        """
        PURPOSE:
            Cleans extracted text by normalizing whitespace and removing empty lines.
 
        PARAMETERS:
            text: Raw text (possibly with newlines) to clean.
 
        RETURNS:
            A list of cleaned, non-empty text lines.
        """
        out = []

        for raw in (text or "").splitlines():
            s = re.sub(r"\s+", " ", raw).strip()
            if s:
                out.append(s)

        return out
 

    def _find_line_index(self, lines: List[str], pattern: str) -> Optional[int]:
        """
        PURPOSE:
            Finds the index of the first line that matches a given regular expression.
 
        PARAMETERS:
            - lines: List of text lines to search through.
            - pattern: Regular expression pattern used to identify the target line.
 
        RETURNS:
            The index of the matching line if found, otherwise None.
        """
        rx = re.compile(pattern, re.IGNORECASE)

        for i, line in enumerate(lines):
            if rx.search(line):
                return i

        return None
 

    def _skip_side_header_line(self, line: str) -> bool:
        """
        PURPOSE:
            Identifies lines that should be ignored when extracting report header text.
            Skips side-header labels and finance table column headers.
 
        PARAMETERS:
            line: A single extracted line of text.
 
        RETURNS:
            True if the line should be skipped, False otherwise.
        """
        l = line.strip()
 
        # DEBUG ADDITION
        if not l:
            return True
        # Only skip the SIDE HEADER SICTION , NOT PROGRAMA FIDAE (01) for FACH
        if re.match(r"\b(PARTIDA|CAP[IÍ]TULO|PROGRAMA)\s*[:\-]?\s*\d+\s*$", l, re.IGNORECASE):
            return True
        
        # Skip table column headers
        if re.search(
            r"\b(Sub[-\s]?T[íi]tulo|Item|Asig\.?|Asignaci[oó]n|Denominaciones|Glosa|Moneda|Miles de)\b",
            l,
            re.IGNORECASE,
        ):
            return True
        if re.fullmatch(r"\d{1,4}", l):
            return True
        return False


    def _fallback_find_ministry(self, head: List[str]) -> Optional[str]:
        """
        PURPOSE:
            Attempts to identify the ministry line if it is not cleanly detected.
            Uses alternative heuristics like finding 'MINISTERIO' anywhere or
            selecting an uppercase-heavy line near the top.
 
        PARAMETERS:
            head: Cleaned lines from the header extraction region.
 
        RETURNS:
            A best-guess ministry line if found, otherwise None.
        """

        for line in head:
            if re.search(r"\bMINISTERIO\b", line, re.IGNORECASE):
                return line
            
        best = None
        best_score = 0.0

        for line in head[:15]:
            if self._skip_side_header_line(line):
                continue
            letters = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", line)
            if len(letters) < 8:
                continue
            upper = sum(1 for c in letters if c.isupper())
            score = upper / max(len(letters), 1)
            if score > best_score and len(line) >= 10:
                best = line
                best_score = score
        return best

    
    def _normalize_whitespace(self, s: str) -> str:
        """
        PURPOSE:
        Normalizes whitespace so regex matching works consistently.
 
        PARAMETERS:
        s: Input string.
 
        RETURNS:
        A string with collapsed spaces and trimmed ends.
        """
        return re.sub(r"\s+", " ", (s or "").strip())


    def _extract_labeled_value(self, text: str, label_pattern: str) -> Optional[str]:
        """
        PURPOSE:
        Extracts a numeric value that appears after a label like PARTIDA/CAPÍTULO/PROGRAMA.
 
        PARAMETERS:
        text: Text blob to search.
        label_pattern: Regex pattern for the label (e.g., r"\\bPARTIDA\\b").
 
        RETURNS:
        The extracted numeric value as a string, zero-padded to 2 digits when appropriate,
        or None if not found.
        """
        if not text:
            return None
 
        # Match formats like:
        # PARTIDA : 11
        # PARTIDA:11
        # PARTIDA 11
        rx = re.compile(label_pattern + r"\s*[:\-]?\s*([0-9]{1,3})", re.IGNORECASE)
        m = rx.search(text)
        if not m:
            return None
 
        val = m.group(1)
        # Most are 2-digit (01, 11, 19). Keep 3-digit as-is.
        return val.zfill(2) if len(val) <= 2 else val
    

    # Created specifically for PDF Page 713 Ministry of work and labor services (multi-line Ministry)
    def _is_ministry_continuation(self, line: str) -> bool:
        """
        PURPOSE:
            Decide if a header line is a continuation of the ministry name (ministry spans multiple lines).
    
        PARAMETERS:
            - line: A single cleaned header line.
    
        RETURNS:
            True if the line should be appended to the ministry, otherwise False.
        """

        s = (line or "").strip()

        if not s:
            return False
    
        # Specific logic for handleing 
        # e.g., "Y PREVISIÓN SOCIAL"
        if re.match(r"^(Y|E)\b", s, flags=re.IGNORECASE):
            return True
        return False
 
 
    def _is_service_continuation(self, line: str) -> bool:
        """
        PURPOSE:
            Decide if a header line is a continuation of the service_component name.
    
        PARAMETERS:
            - line: A single cleaned header line.
    
        RETURNS:
            True if the line should be appended to the service component, otherwise False.
        """

        s = (line or "").strip()

        if not s:
            return False
    
        # Typical continuation lines start with lower-case Spanish prepositions/articles
        # e.g., "de la Armada de Chile"

        if re.match(r"^(de|del|de la|de los|de las|la|las|los)\b", s, flags=re.IGNORECASE):
            return True
    
        return False
    
 
    def _dedupe_preserve_order(self, lines: List[str]) -> List[str]:
        """
        PURPOSE:
            Remove duplicate lines while preserving original order.
    
        PARAMETERS:
            - lines: List of strings.
    
        RETURNS:
            New list with duplicates removed (order preserved).
        """
        seen = set()
        out = []

        for s in lines:
            key = (s or "").strip()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out
 

    # Added Specifically for Servicsion hidrografico y oceanogrico de la armada de chile
    def _split_repeated_wrapped_header_blocks(
        self,
        captured: List[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """
        PURPOSE:
            Resolves a specific PDF extraction edge case where Camelot returns
            duplicated, wrapped header blocks for the main report header.
    
        SCENARIO THIS FIXES:
        On some pages, the PDF visually contains TWO logical header fields
        (service_component and sub_component), and EACH field wraps across
        multiple lines. Camelot may extract them in the following order:
            [A, B, A, B]
    
        Where:
            - (A, B) is the wrapped service_component
            - (A, B) is the wrapped sub_component (repeated verbatim)
    
        This helper detects repeated wrapped blocks and splits them cleanly
        into two logical header values.
    
        EXAMPLE:
            captured = [
                "Servicio Hidrográfico y Oceanográfico",
                "de la Armada de Chile",
                "Servicio Hidrográfico y Oceanográfico",
                "de la Armada de Chile",
            ]
    
        If no repeated wrapped pattern is detected, the function falls back
        to a simple positional interpretation:
            - first ine → service_component
            - second line → sub_component (if present)
    
        PARAMETERS:
            captured:
                Ordered list of extracted header lines following the ministry line,
                after side-header and table-header filtering has been applied.
    
        RETURNS:
            Tuple of:
                (service_component, sub_component)
            Each value may be None if not confidently detected.
        """
        def _norm(s: str) -> str:
            """Normalize text for comparison (casefold + collapsed whitespace)."""
            return self._normalize_whitespace(s or "").strip().casefold()
    
        if not captured:
            return None, None
        norm = [_norm(x) for x in captured if _norm(x)]
        service_lines: List[str] = []
        sub_lines: List[str] = []

        # Detect repetition period (most common: 2-line wrap)
        repeat_len = None
        for k in (2, 1, 3):
            if len(norm) >= 2 * k and norm[:k] == norm[k : 2 * k]:
                repeat_len = k
                break
        if repeat_len is not None:
            service_lines = captured[:repeat_len]
            sub_lines = captured[repeat_len : 2 * repeat_len]
        else:
            service_lines = [captured[0]]
            if len(captured) > 1:
                sub_lines = [captured[1]]

        service_component = " ".join(
            s.strip() for s in service_lines if s and s.strip()
        ) or None
    
        sub_component = " ".join(
            s.strip() for s in sub_lines if s and s.strip()
        ) or None
    
        return service_component, sub_component


    # DEBUG ADD- fixes when terminal outputs sub_component with spaces ebtween each character
    def _despace_letter_runs(self, s: str) -> str:
        """
        Fixes OCR/Camelot artifacts where words are returned as
        'S u b s e c r e t a r i a' (letters separated by spaces).
    
        This preserves normal spacing for real multi-letter tokens and numbers.
        """
        if not s:
            return s
    
        tokens = s.split()
        out = []
        run = []
    
        def flush_run():
            nonlocal run
            if run:
                out.append("".join(run))
                run = []
    
        for tok in tokens:
            # Build runs of single-letter alphabetic tokens: S u b s e c ...
            if len(tok) == 1 and tok.isalpha():
                run.append(tok)
                continue
    
            flush_run()
            out.append(tok)
    
        flush_run()
        return " ".join(out)


    @staticmethod
    def _looks_like_continuation(curr: str, prev: str) -> bool:
        """
        PURPOSE:
            To Determine whether a header line is a wrapped continuation of the previous line. This occurs several times in the chile pdf
            when a Service component is so long that it goes to the next line/row. 
        
        PARAMETERS:
            - curr: the current line that is being evaluated
            - prev: the previous header line that was already captured in a data object
        
        RETURNS:
            Bool: True if the current line should be merged into the previos line as a wrapped continuation, or false
        """
        c = curr.strip()
        p = prev.strip()

        # If previous looks open or a likely text wrapping occured
        prev_open = (
            p.endswith(",")
            or (p.count("(") > p.count(")"))
            or p.endswith("-")
        )

        # Current line is most likely a continutation (numbers/ punctuation or closing parenthesis)
        cont_like = (
            bool(re.match(r"^[\d\W]+$", c))
            or bool(re.match(r"^[\)\],;\.s]+", c))
            or bool(re.match(r"^[\d]{1,2}\b", c))
        )
        return prev_open and cont_like
    

    @classmethod
    def _merge_continuations(cls, lines: List[str]) -> List[str]:
        """
        PURPOSE: 
            Merged wrapped continution lines in a seqwuence of extracted header lines. This method aims to reconstruct
            logical main header report lines that were split across multiple lines/rows. This is heavily reliant on _looks_like_continuation()
            The merge is performed Left to Right as yo uwill see via the splitting mechanism (lstrip and rstrip)
        
        PARAMETERS:
            lines: a list of extracted header lines in document order
        
        RETURNS:
            list[str]: a new list of header lines with wrapped continuations merged into their precedinglines
        """
        merged: List[str] = []
        for line in lines:
            if not merged:
                merged.append(line)
                continue
            if cls._looks_like_continuation(line,merged[-1]):
                merged[-1] = f"{merged[-1].rstrip()} {line.lstrip()}"
            else:
                merged.append(line)
        return merged

    # ---------- SERVICE COMPONENT TABLE EXTRACTION HELPER FUNCTIONS SECTION ---------------
    @staticmethod
    def _parse_csv_floats(value:str, *, expected_n: int) -> Tuple[float,...]:
        """
        Docstring for _parse_csv_floats
        
        :param value: Description
        :type value: str
        :param expected_n: Description
        :type expected_n: int
        :return: Description
        :rtype: Tuple[float, ...]
        """
        parts = [p.strip() for p in value.split(',')]
        if len(parts) != expected_n:
            raise ValueError(f"Expected: {expected_n} comma-separated values got {len(parts)}: {value!r}")
        try:
            return tuple(float(p) for p in parts)
        except ValueError as e:
            raise ValueError(f"Could not parse floats from {value!r}") from e
    

    @staticmethod
    def _preview_bbox_to_camelot_area(
        *,
        page_height: Number,
        left: Number,
        top: Number,
        width: Number,
        height: Number,
        pad: float = 10.0
    )-> str:
        """
        Docstring for _preview_bbox_to_camelot_area
        
        :param page_height: Description
        :type page_height: Number
        :param left: Description
        :type left: Number
        :param top: Description
        :type top: Number
        :param width: Description
        :type width: Number
        :param height: Description
        :type height: Number
        :param pad: Description
        :type pad: float
        :return: Description
        :rtype: str
        """
        x1 = float(left) - pad
        x2 = float(left) + float(width) + pad

        preview_bottom = float(top) + float(height)

        y1 = float(page_height) - preview_bottom - pad
        y2 = float(page_height) - float(top) + pad

        return f"{x1},{y1},{x2},{y2}"

    @staticmethod
    def _clean_service_component_table(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # normalize whitespace and empty values as seen in the pdf pages
        # This block is where we assign "None" to all the empty spaces in the PDF page
        for col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace({"": None, "nan": None, "None": None})
            )
        # Drop rows that look like a long page number that aligns with the 'Denominaciones' column in the pdf
        if "denominaciones" in df.columns:
            other_cols = [col for col in df.columns if col != 'denominaciones']
            mask_page_num = (
                df['denominaciones'].str.fullmatch(r"\d{2,4}", na=False)
                & df[other_cols].isna().all(axis=1)
            )
            df = df.loc[~mask_page_num].reset_index(drop=True)

        # Merge continuation only rows into the previous rows denominaciones column
        required = {"sub_titulo", "item_asign", "denominaciones", "glosa_no", "moneda_clp_miles", "moneda_ext_usd_miles"}
        if required.issubset(df.columns):
            rows = []
            i = 0
            while i < len(df):
                cur = df.iloc[i].to_dict()

                is_continuation_only = (
                    cur.get("denominaciones") is not None
                    and cur.get("sub_titulo") is None
                    and cur.get("item_asign") is None
                    and cur.get("glosa_no") is None
                    and cur.get("moneda_clp_miles") is None
                    and cur.get("moneda_ext_usd_miles") is None
                )

                if is_continuation_only and rows:
                    prev = rows[-1]
                    prev_text = prev.get("denominaciones") or ""
                    cur_text = cur.get("denominaciones") or ""

                    # If the previous ends with a hyphen, remove hyphen and join it directly to the preceding text
                    if prev_text.endswith("-"):
                        prev['denominaciones'] = (prev_text[:-1] + cur_text).strip()
                    else:
                        prev['denominaciones'] = (prev_text + " " + cur_text).strip()
                    
                    # Increment
                    i += 1
                    continue

                rows.append(cur)
                i+=1

            df = pd.DataFrame(rows,columns=df.columns)
            
        return df


    # ---------- GLOSAS TABLE EXTRACTION HELPER FUNCTIONS SECTION ----------
    @staticmethod
    def _parse_camelot_area(area_str: str) -> tuple[float, float, float, float]:
        """
        Parse a Camelot table_areas bbox string into floats.
 
        Args:
            area_str: Camelot bbox string formatted as "x1,y1,x2,y2".
 
        Returns:
            Tuple of (x1, y1, x2, y2) as floats.
 
        Raises:
            ValueError: If the string is not 4 comma-separated numbers.
        """
        parts = [p.strip() for p in area_str.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Expected 4 comma-separated values for area_str, got {len(parts)}: {area_str!r}")
        try:
            x1, y1, x2, y2 = (float(p) for p in parts)
        except ValueError as e:
            raise ValueError(f"Could not parse floats from area_str={area_str!r}") from e
        return x1, y1, x2, y2
 
    @staticmethod
    def _format_camelot_area(x1: float, y1: float, x2: float, y2: float) -> str:
        """
        Format floats into Camelot bbox string.
 
        Args:
            x1: Left.
            y1: Bottom.
            x2: Right.
            y2: Top.
 
        Returns:
            Camelot bbox string: "x1,y1,x2,y2".
        """
        return f"{x1},{y1},{x2},{y2}"
 
    def _find_glosas_bbox_and_table_only_area(
        self,
        pdf_path: str,
        camelot_page: int,
        base_table_area_str: str,
        *,
        page_height: float,
        keyword: str = "GLOSAS",
        x_min: float = 0.0,
        x_max: float = 200.0,
        pad_points: float = 8.0,
    ) -> tuple[str, float | None]:
        """
        Find the 'GLOSAS' heading on a PDF page using PyMuPDF, convert its coordinates for Camelot,
        and return a new Camelot bbox string that excludes the Glosas section (table-only region).
 
        This is designed for pages where the main budget table and the Glosas section appear on the
        same page. The main table is above the Glosas heading. We:
          1) Search for the exact heading text (default: "GLOSAS") using PyMuPDF.
          2) Convert the found text rectangle's Y coordinate from PyMuPDF space (top-left origin)
             to PDF/Camelot space (bottom-left origin) using the page height.
          3) Adjust the *bottom* (y1) of the provided `base_table_area_str` so the table bbox ends
             just above the Glosas heading.
 
        Coordinate notes (important):
            - PyMuPDF returns rectangles in a coordinate space where Y grows downward from the top.
            - Camelot/PDF coordinates use bottom-left origin where Y grows upward.
            - Conversion: pdf_y = page_height - pymupdf_y
 
        Page numbering notes:
            - Camelot pages are 1-based.
            - PyMuPDF pages are 0-based.
            - This function expects `camelot_page` (1-based) and converts internally.
 
        Args:
            pdf_path: Path to the PDF file.
            camelot_page: Page number in Camelot terms (1-based).
            base_table_area_str: Camelot bbox string "x1,y1,x2,y2" for a region that may include Glosas.
            page_height: Page height in points (e.g., 751.19). Must match the target page.
            keyword: Text to search for. Default "GLOSAS" (all caps).
            x_min: Optional left bound filter in PyMuPDF coords to reduce false matches.
            x_max: Optional right bound filter in PyMuPDF coords to reduce false matches.
            pad_points: Padding (in points) added above the Glosas heading when cropping the table-only bbox.
 
        Returns:
            (new_table_area_str, glosas_cut_y_pdf)
            - new_table_area_str: Camelot bbox string for the table-only region. If keyword not found,
              returns `base_table_area_str` unchanged.
            - glosas_cut_y_pdf: The computed cut line in PDF/Camelot Y coords (float), or None if not found.
 
        Raises:
            ValueError: If `base_table_area_str` is malformed.
            RuntimeError: If the requested page index is out of bounds.
        """
        x1, y1, x2, y2 = self._parse_camelot_area(base_table_area_str)
 
        # Convert Camelot page (1-based) to PyMuPDF page index (0-based)
        page_index = int(camelot_page) - 1
        if page_index < 0:
            raise RuntimeError(f"Invalid camelot_page={camelot_page}; must be >= 1")
 
        with pymupdf.open(pdf_path) as doc:
            if page_index >= doc.page_count:
                raise RuntimeError(
                    f"camelot_page={camelot_page} is out of range for this PDF "
                    f"(doc has {doc.page_count} pages; max camelot_page={doc.page_count})."
                )
 
            page = doc[page_index]
 
            # Find all occurrences of the keyword on the page
            rects = page.search_for(keyword)
 
            if not rects:
                # No glosas heading found; return unchanged
                return base_table_area_str, None
 
            # Filter matches by expected X region (helps prevent false positives)
            candidates = [r for r in rects if (r.x0 >= x_min and r.x0 <= x_max)]
            if not candidates:
                candidates = rects  # fallback: use any match if X-filter removes all
 
            # Choose the "best" match:
            # - typically, the title "GLOSAS" is a standalone heading, so pick the leftmost/topmost candidate.
            # - prioritize smallest x0 (left margin), then smallest y0 (higher on page).
            best = sorted(candidates, key=lambda r: (r.x0, r.y0))[0]
 
            # PyMuPDF y0 is top of the rectangle in top-left origin space
            glosas_y_pdf = float(page_height) - float(best.y0)
 
        # If the glosas cut line is within our base bbox vertical span, crop the bottom upward.
        # Camelot expects y1 < y2; increasing y1 makes the bbox shorter (removes lower content).
        if y1 < glosas_y_pdf < y2:
            new_y1 = max(y1, glosas_y_pdf + float(pad_points))
            new_area = self._format_camelot_area(x1, new_y1, x2, y2)
            return new_area, glosas_y_pdf
 
        # If the match is outside the bbox span, leave unchanged (likely bbox already excludes it)
        return base_table_area_str, glosas_y_pdf
 
 
    def _crop_table_area_above_glosas(
        self,
        pdf_path: str,
        camelot_page: int,
        base_table_area_str: str,
        *,
        page_height: float,
        pad_points: float = 8.0,
    ) -> tuple[str, float | None]:
        """
        Find the 'GLOSAS' heading on a page (PyMuPDF), convert coordinates to PDF/Camelot space,
        and crop a Camelot table_areas bbox so it excludes the Glosas section.
 
        Args:
            pdf_path: Path to PDF.
            camelot_page: 1-based page number (Camelot convention).
            base_table_area_str: Camelot bbox string "x1,y1,x2,y2" (PDF coords, origin bottom-left).
            page_height: Page height in points.
            pad_points: Extra padding above the GLOSAS heading to avoid clipping the last table row.
 
        Returns:
            (new_table_area_str, glosas_cut_y_pdf)
            - new_table_area_str: Cropped bbox string. Unchanged if GLOSAS not found.
            - glosas_cut_y_pdf: Y coordinate (PDF/Camelot space) of the top of the GLOSAS heading, or None.
        """
        x1, y1, x2, y2 = (float(v.strip()) for v in base_table_area_str.split(","))
 
        page_index = camelot_page - 1
        if page_index < 0:
            raise ValueError("camelot_page must be >= 1")
 
        with pymupdf.open(pdf_path) as doc:
            page = doc.load_page(page_index)
 
            # Try a couple common variants
            rects = page.search_for("GLOSAS :")
            if not rects:
                rects = page.search_for("GLOSAS:")
 
            if not rects:
                return base_table_area_str, None
 
            # If multiple matches, pick the leftmost/topmost
            rect = sorted(rects, key=lambda r: (r.x0, r.y0))[0]
 
            # Convert PyMuPDF y0 (top-origin) to PDF y (bottom-origin)
            glosas_cut_y_pdf = float(page_height) - float(rect.y0)
 
        # Crop only if the cut falls inside the bbox vertical span
        if y1 < glosas_cut_y_pdf < y2:
            new_y1 = max(y1, glosas_cut_y_pdf + pad_points)
            new_area = f"{x1},{new_y1},{x2},{y2}"
            return new_area, glosas_cut_y_pdf
 
        return base_table_area_str, None
 

    # Original
    # @staticmethod
    # def _score_template_a_alignment(df: pd.DataFrame) -> int:
    #     """
    #     Heuristic score for whether a 6-col Template A extraction is aligned correctly.
    #     Higher is better.
    #     """
    #     if df is None or df.empty or df.shape[1] != 6:
    #         return -10_000
 
    #     tmp = df.copy()
    #     tmp.columns = [
    #         "sub_titulo",
    #         "item_asig",
    #         "denominaciones",
    #         "glosa_no",
    #         "moneda_nacional_miles_de_$CLP",
    #         "moneda_ext_convertida_miles_USD",
    #     ]
 
    #     denom = tmp["denominaciones"].fillna("").astype(str).str.strip()
    #     item  = tmp["item_asig"].fillna("").astype(str).str.strip()
    #     sub   = tmp["sub_titulo"].fillna("").astype(str).str.strip()
    #     glosa = tmp["glosa_no"].fillna("").astype(str).str.strip()
    #     clp   = tmp["moneda_nacional_miles_de_$CLP"].fillna("").astype(str).str.strip()
    #     usd   = tmp["moneda_ext_convertida_miles_USD"].fillna("").astype(str).str.strip()
 
    #     denom_nonempty = (denom != "").sum()
 
    #     # Sub-titulo should have many 2-digit codes (or blanks), not words
    #     sub_numeric_or_empty = (sub.eq("") | sub.str.fullmatch(r"\d{2}", na=False)).sum()
    #     sub_nonempty = (sub != "").sum()
 
    #     # Item can have 1–3 digits or be empty (014, 01, 243, etc.)
    #     item_numeric_or_empty = (item.eq("") | item.str.fullmatch(r"\d{1,3}", na=False)).sum()
    #     item_has_words = item.str.contains(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", regex=True).sum()
 
    #     # Glosa should contain some 2-digit codes on many pages
    #     glosa_nonempty = (glosa != "").sum()
    #     glosa_2digit = glosa.str.fullmatch(r"\d{2}", na=False).sum()
 
    #     # Detect classic shifts: glosa codes leaking into CLP
    #     clp_2digit_like = clp.str.fullmatch(r"\d{2}", na=False).sum()
 
    #     # Detect money swapping: if USD is too "full" compared to CLP (rough signal)
    #     clp_nonempty = (clp != "").sum()
    #     usd_nonempty = (usd != "").sum()
 
    #     bad_headings = item.str.contains(r"\b(?:INGRESOS|GASTOS|APORTE|TRANSFERENCIAS)\b", regex=True).sum()
 
 
    #     score = 0
    #     score += 2 * denom_nonempty
    #     score += 2 * item_numeric_or_empty
    #     score += 1 * sub_numeric_or_empty
    #     score -= 3 * item_has_words
    #     score -= 10 * bad_headings
 
    #     # Strong alignment incentives / penalties
    #     score += 4 * glosa_2digit
    #     score -= 30 * (1 if sub_nonempty < 2 else 0)          # subtitle missing => big penalty
    #     score -= 30 * (1 if glosa_nonempty == 0 else 0)       # glosa missing => big penalty
    #     score -= 20 * clp_2digit_like                         # glosa leaking into CLP
    #     score -= 10 * (1 if (usd_nonempty > clp_nonempty and clp_nonempty < 3) else 0)
 
    #     return int(score)
    #DEBUG ADD 10FEB
    @staticmethod
    def _score_template_a_alignment(df: pd.DataFrame) -> int:
        """
        Enhanced validation for alignment with penalties for likely misassignments.
        """
        if df is None or df.empty or df.shape[1] != 6:
            return -10_000

        tmp = df.copy()
        tmp.columns = [
            "sub_titulo",
            "item_asig",
            "denominaciones",
            "glosa_no",
            "moneda_nacional_miles_de_$CLP",
            "moneda_ext_convertida_miles_USD",
        ]

        denom = tmp["denominaciones"].fillna("").astype(str).str.strip()
        item  = tmp["item_asig"].fillna("").astype(str).str.strip()
        sub   = tmp["sub_titulo"].fillna("").astype(str).str.strip()

        # Calculate penalties for unusual assignments
        denom_too_empty = (denom == "").sum()
        item_is_wordy = item.str.match(r".*[A-Za-zÁÉÍÓÚÑáéíóúñ]", na=False).sum()

        # Check if `item_asig` is appropriately numeric
        item_non_numeric = ~item.str.fullmatch(r"[\d]{1,3}", na=False)

        score = 0

        # Reward strongly aligned cases
        score += 2 * (item.str.fullmatch(r"[\d]{1,3}", na=False).sum())  # Numeric item_asig
        score += 2 * (denom != "").sum()  # Non-empty denominaciones

        # Penalize misaligned cases
        score -= 3 * denom_too_empty
        score -= 5 * item_non_numeric.sum()
        score -= 4 * item_is_wordy

        return int(score) # END OF DEBUG ADD 10FEB
    
    #DEBUG ADD 10FEB
    @staticmethod
    def _post_process_extracted_table(df: pd.DataFrame) -> pd.DataFrame:
        """
        Post-process the extracted table to resolve issues where text values
        are wrongly placed in `item_asig` and split content appropriately.
        """
        tmp = df.copy()
        tmp.columns = [
            "sub_titulo",
            "item_asig",
            "denominaciones",
            "glosa_no",
            "moneda_nacional_miles_de_$CLP",
            "moneda_ext_convertida_miles_USD",
        ]

        # Define a regex pattern to match numeric keys followed by text
        numeric_with_text_pattern = r"^(\d{1,3})\s+(.+)$"
        
        # Split text patterns in `item_asig` where applicable
        misaligned = tmp["item_asig"].str.match(numeric_with_text_pattern, na=False)
        split_values = tmp.loc[misaligned, "item_asig"].str.extract(numeric_with_text_pattern)
        
        # Assign numeric part back to item_asig
        tmp.loc[misaligned, "item_asig"] = split_values[0]  # Group 1: Numeric portion
        tmp.loc[misaligned, "denominaciones"] = split_values[1]  # Group 2: Associated text
        
        # Any non-numeric `item_asig` is moved to `denominaciones`
        item_is_wordy = tmp["item_asig"].str.contains(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", na=False)
        tmp.loc[item_is_wordy, "denominaciones"] = tmp.loc[item_is_wordy, "item_asig"]
        tmp.loc[item_is_wordy, "item_asig"] = None

        # ===============================
        # PATCH 2: Repair "slipped item_asig into sub_titulo"
        # ===============================
        sub = tmp["sub_titulo"].fillna("").astype(str).str.strip()
        item = tmp["item_asig"].fillna("").astype(str).str.strip()
        denom = tmp["denominaciones"].fillna("").astype(str).str.strip()

        # Identify "real" Sub-Título headings:
        # - sub is exactly 2 digits
        # - item is empty
        # - denominaciones looks like an uppercase heading
        is_heading = (
            sub.str.fullmatch(r"\d{2}", na=False)
            & item.eq("")
            & denom.str.fullmatch(r"[A-ZÁÉÍÓÚÑ\s\-\.\,]{4,}", na=False)
        )
        valid_sub = set(sub[is_heading])

        # If item is empty but sub contains a 1–3 digit code that is NOT a heading,
        # it's almost certainly an item_asig that slipped into sub_titulo.
        mask_slip = (
            item.eq("")
            & sub.str.fullmatch(r"\d{1,3}", na=False)
            & (~sub.isin(valid_sub))
            & denom.ne("")
        )

        tmp.loc[mask_slip, "item_asig"] = sub[mask_slip]
        tmp.loc[mask_slip, "sub_titulo"] = None
        # ===============================
        # END PATCH 2
        # ===============================


        return tmp

    # ---------- REPORT HEADER FUNCTIONS SECTION  ----------
    # Function that only extracts the main report header of each page 
    def extract_main_report_header(
        self,
        pdf_path: str,
        page_num: int,
        *,
        header_main_area: str,
        flavor: str = "stream",
        strip_text: str = "\n",
        debug: bool = False,
    ) -> Dict[str, HeaderValue]:
        """
        PURPOSE:
            Extracts ONLY the main report header information (top-center header) from a single
            PDF page using Camelot, bounded by a main header area box. This avoids mixing
            the main header with the side header (PARTIDA/CAPÍTULO/PROGRAMA) and table content.
 
        PARAMETERS:
            - pdf_path: File path to the source PDF.
            - page_num: 0-based page index (Python-style). Will be converted to Camelot's 1-based page string.
            - header_main_area: Camelot table_areas string "x1,y1,x2,y2" defining the MAIN header region to extract.
            - flavor: Camelot extraction flavor ("stream" is usually best for header text blocks).
            - strip_text: Characters Camelot should strip from cell text (commonly "\\n").
            - debug: If True, prints intermediate extracted lines for troubleshooting.
 
        RETURNS:
            A dictionary containing:
                - ministry: Name of the ministry line (best guess)
                - service_component: Primary service/component name line
                - sub_component: Secondary line if present
                - raw_main_header_lines: Lines used during extraction (debugging Purpose)
        """
        camelot_page = str(page_num + 1)

        main_tables = camelot.read_pdf(
            pdf_path,
            pages=camelot_page,
            flavor=flavor,
            table_areas=[header_main_area],
            strip_text=strip_text,
        )

        extracted_lines: List[str] = []

        if main_tables.n > 0:
            for t in main_tables:
                extracted_lines.extend(self._lines_from_camelot_df(t.df))
 
        lines = self._clean_lines("\n".join(extracted_lines))
        head = lines[:40]
 
        if debug:
            print("\n" + "=" * 90)
            print(f"[DEBUG] header_main_area={header_main_area} | tables_found={main_tables.n}")
            print("=== MAIN REPORT HEADER AREA LINES (CAMELOT) ===")

            for i, l in enumerate(head):
                print(f"{i:02d}: {l}")
 
        ministry_idx = self._find_line_index(head, r"\bMINISTERIO\b")
        ministry = head[ministry_idx] if ministry_idx is not None else None
        
        # --- UPDATE FOR PAGE 713: merge multi-line ministry ( "MINISTERIO DEL TRABAJO" + "Y PREVISIÓN SOCIAL") ---
        start_after_ministry_idx = None
        
        if ministry_idx is not None:
            start_after_ministry_idx = ministry_idx

            # Find the first non-sideheader line after the "MINISTERIO..." line
            nxt = None
            for j in range(ministry_idx + 1, min(ministry_idx + 6, len(head))):
                if not self._skip_side_header_line(head[j]):
                    nxt = j
                    break
    
            # If the next meaningful line is a ministry continuation, merge it
            if nxt is not None and self._is_ministry_continuation(head[nxt]):
                ministry = f"{head[ministry_idx].strip()} {head[nxt].strip()}"
                start_after_ministry_idx = nxt  # start capturing AFTER the continuation line
    
        captured: List[str] = []
        service_component = None
        sub_component = None
        
        if start_after_ministry_idx is not None:
            # UPDATE - We need to capture up to 4 main header lines after Ministry line
            for line in head[start_after_ministry_idx + 1 : start_after_ministry_idx + 15]:
                if self._skip_side_header_line(line):
                    continue
                captured.append(line)
                # Updateing to make sure of cases where subcomponent extends to a 4th line
                if len(captured) >= 4:
                    break
        # service_component, sub_component = (self._split_repeated_wrapped_header_blocks(captured))
        captured_merged = self._merge_continuations(captured)
        service_component, sub_component = self._split_repeated_wrapped_header_blocks(captured_merged)


        if debug:
            print(f"[DEBUG] ministry_idx = {ministry_idx}, ministry= {ministry!r}")
            print(f"[DEBUG] start_after_ministry_idx={start_after_ministry_idx}")
            print(f"[DEBUG] Captured count = {len(captured)}, captured= {captured!r}")
            print(f"[DEBUG] service_component={service_component!r}")
            print(f"[DEBUG] sub_component={sub_component!r}")

        raw_main_header_lines:Optional[List[str]] = ([ministry] if ministry else []) + captured
        if not raw_main_header_lines:
            raw_main_header_lines = None

        return {
            "ministry": ministry,
            "service_component": service_component,
            "sub_component": sub_component,
            "raw_main_header_lines": raw_main_header_lines,
        }


    def extract_main_report_header_return_list(
            self,
            pdf_path: str,
            page_numbers: List[int],
            *,
            header_main_area: str,
            flavor: str = 'stream',
            strip_text: str = '\n',
            debug: bool = False,
    ) -> List[dict]:
        """
        PURPOSE:
            This function wraps extract_main_report_header and allows to accept a list of pdf pages

        RETURNS:
            A list of dictionaries containing main report header (center section) information
        """
        # results will hold the main header and side header information
        results = []

        for page in page_numbers:
            out = self.extract_main_report_header(
                pdf_path=pdf_path,
                page_num=page,
                header_main_area=header_main_area,
                flavor=flavor,
                strip_text=strip_text,
                debug=debug,
            )
            # out["page_num"] = page
            results.append({"page_num": page, **out})
        return results


    def extract_side_report_header(
        self,
        pdf_path: str,
        page_num: int,
        *,
        header_side_area: str,
        flavor: str = "stream",
        strip_text: str = "\n",
        debug: bool = False,
    ) -> Dict[str, Union[str, List[str], None]]:
        """
        PURPOSE:
            Extracts ONLY the report side header values (PARTIDA/CAPÍTULO/PROGRAMA)
            from the top-right side header box on a single PDF page using Camelot.
 
        PARAMETERS:
            - pdf_path: File path to the source PDF.
            - page_num: 0-based page index (Python-style). Will be converted to Camelot's 1-based page string.
            - header_side_area: Camelot table_areas string "x1,y1,x2,y2" defining the SIDE header region to extract.
            - flavor: Camelot extraction flavor ("stream" is usually best for header text blocks).
            - strip_text: Characters Camelot should strip from cell text (commonly "\\n").
            - debug: If True, prints intermediate extracted lines and parsed values for troubleshooting.
 
        RETURNS:
            A dictionary containing:
            - partida: PARTIDA value as a string (often 2 digits)
            - capitulo: CAPÍTULO value as a string (often 2 digits)
            - programa: PROGRAMA value as a string (often 2 digits)
            - raw_side_header_lines: Lines used during extraction (debugging aid)
        """
        camelot_page = str(page_num + 1)
 
        side_tables = camelot.read_pdf(
            pdf_path,
            pages=camelot_page,
            flavor=flavor,
            table_areas=[header_side_area],
            strip_text=strip_text,
        )
 
        # DEBUG
        if debug and side_tables.n > 0:
            print(f"\n[DEBUG] RAW SIDE HEADER TABLE DF")
            print(side_tables[0].df)

        side_lines: List[str] = []

        if side_tables.n > 0:
            for t in side_tables:
                # UPDATED to use revised function with drop_side_header flag
                side_lines.extend(self._lines_from_camelot_df(t.df,drop_side_header=False))
 
        side_clean = self._clean_lines("\n".join(side_lines))
        side_text = self._normalize_whitespace(" ".join(side_clean))

        # DEBUG
        if debug:
            print(f"[DEBUG] side_text = {side_text}")

        partida = self._extract_labeled_value(side_text, r"\bPARTIDA\b")
        capitulo = self._extract_labeled_value(side_text, r"\bCAP[IÍ]TULO\b")
        programa = self._extract_labeled_value(side_text, r"\bPROGRAMA\b")
 
        raw_side_header_lines = side_clean[:40] if side_clean else None

        return {
            "partida": partida,
            "capitulo": capitulo,
            "programa": programa,
            "raw_side_header_lines": raw_side_header_lines,
        }


    def extract_side_report_header_return_list(
            self,
            pdf_path: str,
            page_nums: List[int],
            *,
            header_side_area: str,
            flavor: str = 'stream',
            strip_text: str = "\n",
            debug: bool = False,
    ) -> List[dict]:
        """
        PURPOSE:
            This function wraps extract_side_report_header and allows to accept a list of pdf pages

        RETURNS:
            A list of dictionaries containing side report header (top right corner/Grey Box) information on the pdf pages 
        """
        if debug:
            print("[DEBUG] running extract_side_report_header_return_list()")

        # results = []
        results: List[Dict[str,Any]] = []

        for page in page_nums:
            if debug:
                print("\n" + "=" * 90)
                print(f"[DEBUG] SIDE_REPORT_HEADER_RETURN_LIST() | Page_Num: {page}")
                print("=" * 90)

            out = self.extract_side_report_header(
                pdf_path=pdf_path,
                page_num=page,
                header_side_area=header_side_area,
                flavor=flavor,
                strip_text=strip_text,
                debug=debug,
            )
            results.append({"page_num": page, **out})
        return results
    

    def extract_combined_report_headers_return_list(
        self,
        pdf_path: str,
        page_nums: List[int],
        *,
        header_main_area: str,
        header_side_area: str,
        flavor: str = "stream",
        strip_text: str = "\n",
        debug: bool = False,
    ) -> Dict[int, Dict[str, Any]]:
        """
        PURPOSE:
            Extracts BOTH the main report header and the side report header from multiple PDF pages.
            This function calls the existing batch extractors (main + side) and merges results per page.
    
        PARAMETERS:
            pdf_path: Path to the source PDF file.
            page_nums: List of 0-based page indexes to extract from.
            header_main_area: Camelot table_areas bbox string "x1,y1,x2,y2" targeting the main header region.
            header_side_area: Camelot table_areas bbox string "x1,y1,x2,y2" targeting the side header region.
            flavor: Camelot extraction flavor (usually "stream").
            strip_text: Characters Camelot should strip from cell text (commonly "\\n").
            debug: If True, prints debugging output for each page.
    
        RETURNS:
            A dictionary keyed by page_num (int). Each value is a merged dictionary containing:
            - main header fields (ex: ministry, service_component, sub_component, raw_header_lines)
            - side header fields (ex: partida, capitulo, programa, raw_side_header_lines)
        """
        # Run both batch extractors by calling their specific functions with applicable param arguments ie- header search area and side header search area
        main_list = self.extract_main_report_header_return_list(
            pdf_path=pdf_path,
            page_numbers=page_nums,
            header_main_area=header_main_area,
            flavor=flavor,
            strip_text=strip_text,
            debug=debug,
        )
    
        side_list = self.extract_side_report_header_return_list(
            pdf_path=pdf_path,
            page_nums=page_nums,
            header_side_area=header_side_area,
            flavor=flavor,
            strip_text=strip_text,
            debug=debug,
        )
    
        # Index by page_num (force int), and detect duplicates
        main_by_page = {}
        for d in main_list:
            if "page_num" not in d:
                continue
            k = int(d["page_num"])
            if k in main_by_page:
                print(f"[WARN] duplicate main header page_num={k} overwriting previous entry")
            main_by_page[k] = d
        
        side_by_page = {}
        for d in side_list:
            if "page_num" not in d:
                continue
            k = int(d["page_num"])
            if k in side_by_page:
                print(f"[WARN] duplicate side header page_num={k} overwriting previous entry")
            side_by_page[k] = d
    
        # Merge per page
        merged: Dict[int, Dict[str, Any]] = {}
    
        for p in page_nums:
            main = main_by_page.get(p, {})
            side = side_by_page.get(p, {})
    
            # Remove duplicated "page_num" keys so merged dict is clean
            main = {k: v for k, v in main.items() if k != "page_num"}
            side = {k: v for k, v in side.items() if k != "page_num"}
    
            if debug:
                print(f"[DEBUG] merge page={p} | main_keys={list(main.keys())} | side_keys={list(side.keys())}")
                print(f"[DEBUG] main_sub_component={main.get('sub_component')}")
                print(f"[DEBUG] main_raw_lines={main.get('raw_main_header_lines')}")

            merged[p] = {
                "page_num": p,
                "main_header": main,
                "side_header": side,
            }
    
            if debug:
                print("\n" + "=" * 90)
                print(f"[DEBUG] MERGED HEADERS | page_num={p}")
                print(f"[DEBUG] main_header keys: {list(main.keys())}")
                print(f"[DEBUG] side_header keys: {list(side.keys())}")
                print("=" * 90)
    
        return merged
    
    # ------------- SERVICE COMPONENT TABLE EXTRACTION SECTION -------------
    def extract_service_component_table_template_a(
        self,
        pdf_path: str,
        page: Union[int, str],
        config: Dict[str, Any],
        *,
        flavor: str = "lattice",
        ) -> pd.DataFrame:
        """
        Extract the service component table from a single PDF page using Template A config.
 
        Notes:
            - This function currently reads the YAML key
              `service_component_table_areas.template_a_with_usd` (expected_cols=6).
              If you later add a true 5-column variant, add a separate YAML key/function.
            - MVP scope: extracts **one page**.
            - The YAML `table_area_preview` must be measured in macOS Preview as:
              "left,top,width,height" in PDF points. This is converted to Camelot's
              "x1,y1,x2,y2" coordinate system.
 
        Args:
            pdf_path: Path to the PDF.
            page: Page number to extract (int or str).
            config: Parsed YAML config dict with:
                config["service_component_table_areas"]["template_a_with_usd"] containing:
                  - page_height
                  - table_area_preview
                  - expected_cols
            flavor: Camelot flavor (default "lattice").
 
        Returns:
            DataFrame of the extracted table.
 
        Raises:
            KeyError: Missing required config keys.
            RuntimeError: No tables found in the configured area.
            ValueError: Extracted table has unexpected column count.
        """
        tmpl = config["service_component_table_areas"]["template_a_with_usd"]
 
        page_height = tmpl["page_height"]
        expected_cols = int(tmpl["expected_cols"])
 
        left, top, width, height = self._parse_csv_floats(
            tmpl["table_area_preview"], expected_n=4
        )
        area_str = self._preview_bbox_to_camelot_area(
            page_height=page_height,
            left=left,
            top=top,
            width=width,
            height=height,
        )
 
        # --- Crop table area above any GLOSAS section (financial table only) ---
        area_str, glosas_cut_y = self._crop_table_area_above_glosas(
            pdf_path=pdf_path,
            camelot_page=int(page),
            base_table_area_str=area_str,
            page_height=float(page_height),
        )
        if glosas_cut_y is not None:
            logger.debug(f"GLOSAS detected on page {page} at y={glosas_cut_y} (cropping financial table only)")
 
        # IMPORTANT: For Template A financial tables (6 Columns), ALWAYS use FULL column cuts.
        columns_full = tmpl.get("columns_preview_full")
 
        def _best_table(tables):
            return max(tables, key=lambda t: int(t.shape[0]) * int(t.shape[1]))
 
        def _df_from_tables(tables_):
            if tables_ is None:
                return pd.DataFrame()
 
            # get camelots .n attribute (number of tables)
            n = getattr(tables_, "n", None)
            if n is not None:
                return pd.DataFrame() if n == 0 else _best_table(tables_).df
 
            # fallback if it's a list-like
            return pd.DataFrame() if len(tables_) == 0 else _best_table(tables_).df
 
        def _read_stream(area_str: str, columns_preview: str | None):
            stream_kwargs = dict(
                filepath=pdf_path,
                pages=str(page),
                flavor="stream",
                table_areas=[area_str],
                split_text=False,
            )
            if columns_preview:
                cols = [
                    str(float(x))
                    for x in self._parse_csv_floats(
                        columns_preview, expected_n=expected_cols - 1
                    )
                ]
                stream_kwargs["columns"] = [",".join(cols)]
            return camelot.read_pdf(**stream_kwargs) # type: ignore
 
        def _shift_columns_preview(columns_preview: str, delta: float) -> str:
            """
            Shift column divider x-positions by delta, but keep the FIRST divider fixed.
 
            Why: The left edge / Sub-Título cut is very stable across pages, but the
            Ítem Asig | Denominaciones boundary can drift and sometimes needs adjustment.
            """
            xs = list(self._parse_csv_floats(columns_preview, expected_n=expected_cols - 1))
 
            # Defensive: Template A expects 5 dividers when expected_cols=6
            if len(xs) != expected_cols - 1:
                return columns_preview
 
            # Freeze ONLY the first cut (Sub-Título | Ítem Asig).
            shifted = [xs[0]] + [float(x) + float(delta) for x in xs[1:]]
            return ",".join(str(x) for x in shifted)
        
        # DEBUG ADD 10FEB 
        def _shift_first_divider(columns_preview: str, delta_first: float) -> str:
            xs = list(self._parse_csv_floats(columns_preview, expected_n=expected_cols - 1))
            if len(xs) != expected_cols - 1:
                return columns_preview
            # Move ONLY the first divider; keep the rest unchanged
            xs[0] = float(xs[0]) + float(delta_first)
            return ",".join(str(x) for x in xs) # END OF DEBUG ADD 10 FEB

 
        # ---- Extraction strategy ----
        # Keep original behavior for "normal" pages (lattice first),
        # but ALWAYS score/choose final output from stream with FULL cuts (and small deltas if needed).
        if glosas_cut_y is None:
            tables = camelot.read_pdf(
                filepath=pdf_path,
                pages=str(page),
                flavor="lattice",
                table_areas=[area_str],
            )
 
            # Validate lattice result; if it doesn't look right, use stream.
            if tables.n == 0:
                tables = _read_stream(area_str, columns_full)
            else:
                df_try = _best_table(tables).df
                if df_try.shape[1] != expected_cols:
                    tables = _read_stream(area_str, columns_full)
        else:
            # Mixed page (financial table + glosas underneath): stream only, using FULL cuts.
            tables = _read_stream(area_str, columns_full)
 
        if tables.n == 0:
            raise RuntimeError(
                f"No tables found by Camelot on page={page} using area={area_str}."
            )
 
        # --- Final alignment rescue (only if baseline is bad) ---
        # Baseline (delta=0) should preserve the other pages.
        df0 = _df_from_tables(_read_stream(area_str, columns_full))
        score0 = self._score_template_a_alignment(df0)

        # Original COde 10 Feb
        # def _needs_delta_rescue_template_a(df_: pd.DataFrame) -> bool:
        #     """
        #     Only trigger delta-search for the specific 'cascade shift' failure mode:
        #     - Glosa column empty but glosa-like 2-digit codes appear in CLP
        #     - CLP appears to have shifted into USD (USD "too full" while CLP sparse)
        #     This avoids destabilizing otherwise-good pages (e.g., 559/565).
        #     """
        #     if df_ is None or df_.empty or df_.shape[1] != expected_cols:
        #         return True
 
        #     tmp = df_.copy()
        #     tmp.columns = [
        #         "sub_titulo",
        #         "item_asig",
        #         "denominaciones",
        #         "glosa_no",
        #         "moneda_nacional_miles_de_$CLP",
        #         "moneda_ext_convertida_miles_USD",
        #     ]
 
        #     glosa = tmp["glosa_no"].fillna("").astype(str).str.strip()
        #     clp   = tmp["moneda_nacional_miles_de_$CLP"].fillna("").astype(str).str.strip()
        #     usd   = tmp["moneda_ext_convertida_miles_USD"].fillna("").astype(str).str.strip()
 
        #     glosa_nonempty = (glosa != "").sum()
        #     clp_2digit_like = clp.str.fullmatch(r"\d{2}", na=False).sum()
 
        #     clp_nonempty = (clp != "").sum()
        #     usd_nonempty = (usd != "").sum()
 
        #     # Trigger conditions: the cascade symptoms you reported on the last page
        #     glosa_shifted_into_clp = (glosa_nonempty == 0 and clp_2digit_like >= 2)
        #     clp_shifted_into_usd = (usd_nonempty > clp_nonempty and clp_nonempty < 3)
 
        #     return glosa_shifted_into_clp or clp_shifted_into_usd

        # DEBUG ADD 10FEB
        def _needs_delta_rescue_template_a(df_: pd.DataFrame) -> bool:
            if df_ is None or df_.empty or df_.shape[1] != expected_cols:
                return True

            tmp = df_.copy()
            tmp.columns = [
                "sub_titulo",
                "item_asig",
                "denominaciones",
                "glosa_no",
                "moneda_nacional_miles_de_$CLP",
                "moneda_ext_convertida_miles_USD",
            ]

            # Validate expected content in columns
            sub_titulo = tmp["sub_titulo"].fillna("").astype(str).str.strip()
            item_asig = tmp["item_asig"].fillna("").astype(str).str.strip()
            denominaciones = tmp["denominaciones"].fillna("").astype(str).str.strip()
            glosa = tmp["glosa_no"].fillna("").astype(str).str.strip()

            # Check for suspicious shifts
            sub_empty_or_non_numeric = (sub_titulo.eq("") | sub_titulo.str.fullmatch(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", na=False)).sum()
            # item_has_keywords = item_asig.str.contains(r"\b(INGRESOS|TRANSFERENCIAS|APORTE)\b", regex=True).sum()
            item_has_keywords = item_asig.str.contains(r"\b(?:INGRESOS|TRANSFERENCIAS|APORTE)\b", regex=True).sum()


            # Glosa should have valid numeric-like codes
            valid_glosa = glosa.str.fullmatch(r"^\d{1,2}(,\d{1,2})?$", na=False).sum()

            # Penalize cascade symptoms of misaligned columns
            if sub_empty_or_non_numeric > 2 or item_has_keywords > 1:
                return True
            if valid_glosa == 0 and denominaciones.str.contains(r"[A-Za-z]").sum() > 2:
                return True

            return False # END OF DBUG ADD 10 FEB
        
        # DEBUG ADD 10FEB
        def _needs_first_divider_rescue(df_: pd.DataFrame) -> bool:
            if df_ is None or df_.empty or df_.shape[1] != expected_cols:
                return False

            tmp = df_.copy()
            tmp.columns = ["sub_titulo","item_asig","denominaciones","glosa_no",
                        "moneda_nacional_miles_de_$CLP","moneda_ext_convertida_miles_USD"]

            sub = tmp["sub_titulo"].fillna("").astype(str).str.strip()
            item = tmp["item_asig"].fillna("").astype(str).str.strip()
            denom = tmp["denominaciones"].fillna("").astype(str).str.strip()

            # Signature: many rows where item is empty but sub is numeric (1–3 digits) while denom has text
            slipped = (item.eq("") & sub.str.fullmatch(r"\d{1,3}", na=False) & denom.ne("")).sum()
            return slipped >= 3 # END OF DEBUG ADD 10 FEB

 
 
        # Baseline should preserve good pages (559/565). Only run delta rescue when the *cascade* is detected.
        if not _needs_delta_rescue_template_a(df0):
            df = df0
        else:
            candidates: list[tuple[float, pd.DataFrame, int]] = [(0.0, df0, score0)]

            # Original
            # for delta in (-6.0, 6.0, -12.0, 12.0):
            #     cols = _shift_columns_preview(columns_full, delta)
            #     df_cand = _df_from_tables(_read_stream(area_str, cols))
            #     score = self._score_template_a_alignment(df_cand)
            #     candidates.append((delta, df_cand, score))

            # DEBUG ADD 10FEB
            for delta in (-15.0, -10.0, -6.0, 0, 6.0, 10.0, 15.0):
                cols = _shift_columns_preview(columns_full, delta)
                df_cand = _df_from_tables(_read_stream(area_str, cols))
                score = self._score_template_a_alignment(df_cand)
                candidates.append((delta, df_cand, score)) # END OF DEBUG ADD 10FEB

            # Debug add 10feb
            if _needs_first_divider_rescue(df0):
                # Usually you want to move the first divider LEFT a bit to stop item codes falling into sub
                for d1 in (-12.0, -10.0, -8.0, -6.0, -4.0, 0.0, 4.0):
                    cols = _shift_first_divider(columns_full, d1)
                    df_cand = _df_from_tables(_read_stream(area_str, cols))
                    score = self._score_template_a_alignment(df_cand)
                    candidates.append((1000.0 + d1, df_cand, score))  # unique delta key, doesn’t matter

 
            best_delta, df_best, best_score = max(candidates, key=lambda t: t[2])
 
            # Safety gate: only accept a non-zero delta if it's a *meaningful* improvement.
            # Prevents small score fluctuations from breaking Sub/Item on otherwise-good pages.
            min_gain = 25
            if best_delta != 0.0 and best_score < score0 + min_gain:
                logger.debug(
                    f"Delta candidate rejected on page={page}: best_delta={best_delta} "
                    f"best_score={best_score} baseline={score0} (gain<{min_gain})"
                )
                df = df0
            else:
                if best_delta != 0.0:
                    logger.debug(
                        f"Template A alignment rescue applied on page={page}: "
                        f"selected delta={best_delta} score={best_score} baseline={score0}"
                    )
                df = df_best
 
 
        # Final validation
        if df.shape[1] != expected_cols:
            raise ValueError(
                f"Template A extraction failed validation: expected {expected_cols} columns, "
                f"got {df.shape[1]} (page={page}, area={area_str})."
            )
 
        # Assign canonical column names
        df.columns = [
            "sub_titulo",
            "item_asig",
            "denominaciones",
            "glosa_no",
            "moneda_nacional_miles_de_$CLP",
            "moneda_ext_convertida_miles_USD",
        ]
 
        # Clean / normalize text for readability
        df = self._clean_service_component_table(df)

        # Debug Add 10FEB
        df = self._post_process_extracted_table(df)
 
        return df
 
    
    def extract_service_component_tables_template_a_from_list(
        self,
        pdf_path: str,
        pages: list[int],
        config: dict,
    ) -> pd.DataFrame:
        """
        Extract Template A (6-column) service component tables for multiple pages and combine results.
 
        This is a thin wrapper around `extract_service_component_table_template_a`, intended for
        batch extraction once single-page behavior is validated.
 
        Args:
            pdf_path: Path to the PDF file.
            pages: List of Camelot 1-based page numbers to extract.
            config: Loaded YAML config dict containing `service_component_table_areas`.
 
        Returns:
            Combined DataFrame with two extra columns:
            - source_page: int (Camelot 1-based page)
            - has_glosas: bool (True if 'GLOSAS' was detected/cropped on that page)
        """
        dfs: list[pd.DataFrame] = []
 
        for p in pages:
            df = self.extract_service_component_table_template_a(
                pdf_path=pdf_path,
                page=p,
                config=config,
            )
 
            # Add provenance
            df = df.copy()
            df["source_page"] = int(p)
 
            df["has_glosas"] = False  # placeholder
 
            dfs.append(df)
 
        if not dfs:
            return pd.DataFrame()
 
        return pd.concat(dfs, ignore_index=True)
 # ---------- END OF SCRIPT ----------
