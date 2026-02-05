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
import pandas as pd
from typing import Any, Optional, List, Dict, Tuple, Union
import re

# Specialty/Custom Libraries

HeaderValue = Union[str,List[str], int, None]
Number = Union[int, float]

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
        Determine whether a line of header text is a wrapped continuation of the
        previous line.

        This helper is used during PDF header reconstruction to detect cases where
        a logical header line has been visually wrapped across multiple lines by
        the PDF layout engine (e.g., long parenthetical lists of codes).

        The heuristic is intentionally conservative to avoid false positives.
        A line is considered a continuation only when:
            - The previous line appears "open" (e.g., ends with a comma, hyphen,
            or contains an unclosed parenthesis), AND
            - The current line consists primarily of digits and/or punctuation
            (e.g., numeric lists, closing parentheses).

        This approach favors preserving original header structure over aggressive
        merging, reducing the risk of combining unrelated header fields.

        Parameters
        ----------
        curr : str
            The current line being evaluated.
        prev : str
            The previous header line already captured.

        Returns
        -------
        bool
            True if the current line should be merged into the previous line as a
            wrapped continuation; False otherwise.
        """
        c = curr.strip()
        p = prev.strip()
        # If previous line looks "open" (wrap/continuation likely)
        prev_open = (
            p.endswith(",")
            or (p.count("(") > p.count(")"))
            or p.endswith("-")
        )

        # Current line is mostly "continuation-ish" (numbers/punct/closing paren)
        cont_like = (
            bool(re.match(r"^[\d\W]+$", c))  # digits/punctuation only
            or bool(re.match(r"^[\)\],;\.\s]+", c))
            or bool(re.match(r"^[\d]{1,2}\b", c))  # starts with a number
        )

        return prev_open and cont_like
    

    @classmethod
    def _merge_continuations(cls, lines: List[str]) -> List[str]:
        """
        Merge wrapped continuation lines in a sequence of extracted header lines.

        This method reconstructs logical header lines that were split across
        multiple visual lines in the source PDF. It relies on
        `_looks_like_continuation` to conservatively identify continuation patterns
        and merge them into a single coherent line.

        The merge is performed left-to-right, preserving original order and spacing.
        Lines that do not meet the continuation criteria are left unchanged.

        This function is intended to operate on already-filtered header text
        (e.g., main report header lines) prior to semantic parsing into specific
        header fields.

        Parameters
        ----------
        lines : List[str]
            A list of extracted header lines in document order.

        Returns
        -------
        List[str]
            A new list of header lines with wrapped continuations merged into their
            preceding lines.
        """
        merged: List[str] = []
        for line in lines:
            if not merged:
                merged.append(line)
                continue

            if cls._looks_like_continuation(line, merged[-1]):
                merged[-1] = f"{merged[-1].rstrip()} {line.lstrip()}"
            else:
                merged.append(line)

        return merged

    # ---------- SERVICE COMPONENT TABLE EXTRACTION HELPER FUNCTIONS SECTION ----------
    @staticmethod
    def _parse_csv_floats(value: str, *, expected_n: int) -> Tuple[float, ...]:
        """
        Parse a comma-separated string of numbers into floats.

        Args:
            value: String containing comma-separated numeric values (e.g., "1.0,2.0,3.0,4.0").
            expected_n: Expected number of numeric values.

        Returns:
            A tuple of floats of length `expected_n`.

        Raises:
            ValueError: If the number of values does not match `expected_n` or parsing fails.
        """
        parts = [p.strip() for p in value.split(",")]
        if len(parts) != expected_n:
            raise ValueError(f"Expected {expected_n} comma-separated values, got {len(parts)}: {value!r}")
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
        pad: float = 10.0,
    ) -> str:
        """
        Convert a macOS Preview selection (origin top-left) into a Camelot `table_areas` string.

        Preview selection format:
            left, top, width, height
            - Origin is top-left
            - Y increases downward

        Camelot/PDF coordinate format:
            x1, y1, x2, y2
            - Origin is bottom-left
            - Y increases upward

        Args:
            page_height: PDF page height in points (from the PDF MediaBox).
            left: Preview selection left (points).
            top: Preview selection top (points).
            width: Preview selection width (points).
            height: Preview selection height (points).

        Returns:
            A string formatted as "x1,y1,x2,y2" for Camelot `table_areas`.
        """
        x1 = float(left) - pad
        x2 = float(left) + float(width) + pad
        
        preview_bottom = float(top) + float(height)

        y1 = float(page_height) - preview_bottom - pad
        y2 = float(page_height) - float(top) + pad

        return f"{x1},{y1},{x2},{y2}"
    

    @staticmethod
    def _clean_service_component_table(df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and normalize a service component table for readability.

        What this does:
        - Strips whitespace and collapses repeated spaces/newlines.
        - Replaces empty strings with None.
        - Drops footer artifacts (e.g., a lone page number like "543").
        - Merges "continuation-only" rows (wrapped/hyphenated denominaciones lines) into
        the previous row's denominaciones.

        Args:
            df: Raw extracted DataFrame.

        Returns:
            Cleaned DataFrame.
        """
        df = df.copy()

        # Normalize whitespace / empty values
        for col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace({"": None, "nan": None, "None": None})
            )

        # Drop rows that look like a lone page number in 'denominaciones'
        if "denominaciones" in df.columns:
            other_cols = [c for c in df.columns if c != "denominaciones"]
            mask_page_num = (
                df["denominaciones"].str.fullmatch(r"\d{2,4}", na=False)
                & df[other_cols].isna().all(axis=1)
            )
            df = df.loc[~mask_page_num].reset_index(drop=True)

        # Merge continuation-only rows into the previous row's denominaciones
        required = {"sub_titulo", "item_asig", "denominaciones", "glosa_no", "monto_clp_miles", "monto_usd_miles"}
        if required.issubset(df.columns):
            rows = []
            i = 0
            while i < len(df):
                cur = df.iloc[i].to_dict()

                is_continuation_only = (
                    cur.get("denominaciones") is not None
                    and cur.get("sub_titulo") is None
                    and cur.get("item_asig") is None
                    and cur.get("glosa_no") is None
                    and cur.get("monto_clp_miles") is None
                    and cur.get("monto_usd_miles") is None
                )

                if is_continuation_only and rows:
                    prev = rows[-1]
                    prev_text = prev.get("denominaciones") or ""
                    cur_text = cur.get("denominaciones") or ""

                    # If previous ends with a hyphen, remove hyphen and join directly
                    if prev_text.endswith("-"):
                        prev["denominaciones"] = (prev_text[:-1] + cur_text).strip()
                    else:
                        prev["denominaciones"] = (prev_text + " " + cur_text).strip()

                    i += 1
                    continue

                rows.append(cur)
                i += 1

            df = pd.DataFrame(rows, columns=df.columns)

        return df



    # ---------- CORE FUNCTIONS SECTION  ----------
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
            page_nums: List[int],
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

        for page in page_nums:
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
            page_nums=page_nums,
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

        # Build kwargs so we can optionally add explicit column boundaries
        kwargs = dict(
            filepath=pdf_path,
            pages=str(page),
            flavor=flavor,
            table_areas=[area_str],
        )

        columns_preview = tmpl.get("columns_preview")
        if columns_preview and flavor == "stream":
            cols = [
                str(float(x))
                for x in self._parse_csv_floats(columns_preview, expected_n=expected_cols - 1)
            ]
            kwargs["columns"] = [",".join(cols)]

        tables = camelot.read_pdf(**kwargs)


        if tables.n == 0 and flavor == "lattice":
            # Fallback: sometimes lines aren't detected even though the table is visible
            tables = camelot.read_pdf(
                pdf_path,
                pages=str(page),
                flavor="stream",
                table_areas=[area_str],
            )

        if tables.n == 0:
            raise RuntimeError(
                f"No tables found by Camelot on page={page} using table_area={area_str} "
                f"(template_a_with_usd)."
            )

        best = max(tables, key=lambda t: int(t.shape[0]) * int(t.shape[1]))
        df = best.df

        # If lattice found a table but the column count is wrong, try stream (with columns if available)
        if df.shape[1] != expected_cols and flavor == "lattice":
            stream_kwargs = dict(
                filepath=pdf_path,
                pages=str(page),
                flavor="stream",
                table_areas=[area_str],
            )

            stream_kwargs["split_text"] = True

            columns_preview = tmpl.get("columns_preview")
            if columns_preview:
                cols = [
                    str(float(x))
                    for x in self._parse_csv_floats(columns_preview, expected_n=expected_cols - 1)
                ]
                stream_kwargs["columns"] = [",".join(cols)]

            stream_tables = camelot.read_pdf(**stream_kwargs)

            if stream_tables.n > 0:
                best_stream = max(stream_tables, key=lambda t: int(t.shape[0]) * int(t.shape[1]))
                df_stream = best_stream.df
                if df_stream.shape[1] == expected_cols:
                    df = df_stream  # accept stream result

        # Final validation (after giving stream a chance)
        if df.shape[1] != expected_cols:
            raise ValueError(
                f"Template A extraction failed validation: expected {expected_cols} columns, "
                f"got {df.shape[1]} (page={page}, flavor={flavor}, area={area_str})."
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

        return df


# ---------- END OF SCRIPT ----------