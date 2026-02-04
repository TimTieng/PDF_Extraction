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
from typing import Any, Optional, List, Dict, Union
import re

# Specialty/Custom Libraries

HeaderValue = Union[str,List[str], int, None]

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
 
        # if debug:
        #     print("\n" + "=" * 90)
        #     print(f"[DEBUG] SIDE HEADER | page_num={page_num} -> camelot_page={camelot_page}")
        #     print(f"[DEBUG] header_side_area={header_side_area} | tables_found={side_tables.n}")
        #     print("=== SIDE HEADER AREA LINES (CAMELOT) ===")

        #     for i, l in enumerate(side_clean[:40]):
        #         print(f"{i:02d}: {l}")
        #     print(f"[DEBUG] parsed partida={partida} capitulo={capitulo} programa={programa}")
 
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
# ---------- END OF SCRIPT ----------