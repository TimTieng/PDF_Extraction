# TableHelper.py

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

import camelot

HeaderValue = Union[str, List[str], int, None]


class TableHelper:
    """
    Utility class for extracting Chile budget PDF header values using Camelot.

    This helper focuses on extracting:
      - Main report headers (top-center block):
          ministry, service_component, sub_component, raw_main_header_lines
      - Side report headers (top-right grey box):
          partida, capitulo, programa, raw_side_header_lines
      - A combined per-page merge of both.
    """

    # ---------------------------
    # Core text normalization
    # ---------------------------

    def _normalize_whitespace(self, s: str) -> str:
        """
        PURPOSE:
            Normalizes whitespace so regex matching and comparisons are consistent.

        RETURNS:
            A trimmed string with collapsed internal whitespace.
        """
        return re.sub(r"\s+", " ", (s or "").strip())

    def _clean_header_artifacts(self, s: str) -> str:
        """
        PURPOSE:
            Cleans small extraction artifacts that appear in header lines.

        SCENARIOS THIS HELPS:
            - Camelot sometimes introduces stray quotes or splits punctuation oddly, e.g.
              "..., 10, 11,'" or a next-line starting with "'12, 13, ..."
            - Smart cleanup helps preserve the intended meaning:
              "..., 10, 11, 12, 13, ..."

        RETURNS:
            Cleaned header string (still human-readable, no aggressive rewriting).
        """
        if not s:
            return ""

        out = s

        # Normalize curly quotes to straight quotes
        out = out.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")

        # Remove leading/trailing standalone quotes
        out = re.sub(r"^\s*'+\s*", "", out)
        out = re.sub(r"\s*'+\s*$", "", out)

        # Fix digit followed by a stray quote: 11' -> 11
        out = re.sub(r"(\d)\s*'\s*(?=[,)\s])", r"\1", out)

        # Fix quote that precedes digits: '12 -> 12
        out = re.sub(r"'\s*(\d)", r"\1", out)

        # Normalize double commas/spaces
        out = re.sub(r"\s*,\s*", ", ", out)
        out = re.sub(r"\s+", " ", out).strip()

        return out

    def _clean_lines(self, text: str) -> List[str]:
        """
        PURPOSE:
            Cleans extracted text by splitting into lines, collapsing whitespace,
            removing empties, and applying minor artifact cleanup.

        RETURNS:
            List of clean, non-empty header lines.
        """
        out: List[str] = []
        for raw in (text or "").splitlines():
            s = self._normalize_whitespace(raw)
            s = self._clean_header_artifacts(s)
            if s:
                out.append(s)
        return out

    # ---------------------------
    # Camelot table -> lines
    # ---------------------------

    def _join_cells_smart(self, cells: List[str]) -> str:
        """
        PURPOSE:
            Camelot sometimes returns header words split into single-character cells
            (e.g., ['S','u','b','s','e','c',...]).
            If we always do " ".join(cells), that becomes "S u b s e c ...".

            This function detects that scenario and joins WITHOUT spaces.
            Otherwise, it joins with spaces like normal text.

        SCENARIO THIS FIXES:
            Pages where the main header (especially sub_component lines like
            "Subsecretaría para las Fuerzas Armadas (01, 02, ...)")
            is extracted as one letter per cell due to Camelot grid segmentation.

        RETURNS:
            One reconstructed line of text.
        """
        toks: List[str] = []
        for c in cells:
            if c is None:
                continue
            t = str(c).strip()
            if not t or t.lower() == "nan":
                continue
            toks.append(t)

        if not toks:
            return ""

        # Heuristic: if most tokens are single letters, it's a "spaced letters" case
        single_letters = sum(1 for t in toks if len(t) == 1 and t.isalpha())
        if len(toks) >= 8 and (single_letters / len(toks)) >= 0.6:
            return "".join(toks)

        return " ".join(toks)

    def _is_side_header_cell(self, s: str) -> bool:
        """
        PURPOSE:
            Identifies whether a cell is clearly part of the SIDE header labels,
            so we can optionally drop them when extracting MAIN header blocks.

        SCENARIO THIS HELPS:
            When Camelot includes the "PARTIDA / CAPÍTULO / PROGRAMA" grey-box labels
            inside the same grid extraction area as the main header.

        RETURNS:
            True if the cell matches a side-header label pattern.
        """
        if not s:
            return False

        t = self._normalize_whitespace(str(s))

        # Only treat as side-header label if it looks like a LABEL (often appears as "PROGRAMA : 01")
        # This avoids incorrectly treating "Programa Fidae (01)" as a side-header label.
        return bool(re.search(r"\b(PARTIDA|CAP[IÍ]TULO|PROGRAMA)\b\s*[:]", t, flags=re.IGNORECASE))

    def _lines_from_camelot_df(self, df, *, drop_side_header: bool = True) -> List[str]:
        """
        PURPOSE:
            Converts Camelot's extracted grid DataFrame into a list of readable text lines.
            This lets us treat the header area like lines of text instead of table cells.

        KEY BEHAVIOR:
            - Uses a SMART join that prevents the "S u b s e c ..." spaced-letter bug.
            - Optionally drops side-header label cells (PARTIDA/CAPÍTULO/PROGRAMA:).

        PARAMETERS:
            df: Camelot table df (strings in cells).
            drop_side_header: If True, removes side-header label cells from line-building.

        RETURNS:
            List of non-empty reconstructed lines.
        """
        lines: List[str] = []

        # Row-major traversal: join non-empty cells per row
        for _, row in df.iterrows():
            cells = [str(x).strip() for x in row.tolist()]
            cells = [c for c in cells if c and c.lower() != "nan"]

            if drop_side_header:
                cells = [c for c in cells if not self._is_side_header_cell(c)]

            if not cells:
                continue

            line = self._join_cells_smart(cells)
            line = self._normalize_whitespace(line)
            line = self._clean_header_artifacts(line)

            if line:
                lines.append(line)

        return lines

    # ---------------------------
    # Header line skipping / parsing helpers
    # ---------------------------

    def _skip_side_header_line(self, line: str) -> bool:
        """
        PURPOSE:
            Decides if a line should be ignored when capturing MAIN header text.

        IMPORTANT:
            We only skip PARTIDA/CAPÍTULO/PROGRAMA lines when they look like a
            side-header label (i.e., "PROGRAMA : 01"), NOT when "Programa" appears
            inside a main header value like "Programa Fidae (01)".

        RETURNS:
            True if line should be skipped from MAIN header capture.
        """
        l = self._normalize_whitespace(line)

        # Skip only label-style side header lines
        if re.search(r"\b(PARTIDA|CAP[IÍ]TULO|PROGRAMA)\b\s*[:]", l, re.IGNORECASE):
            return True

        # Skip table column headers
        if re.search(
            r"\b(Sub[-\s]?T[íi]tulo|Item|Asig\.?|Asignaci[oó]n|Denominaciones|Glosa|Moneda|Miles de)\b",
            l,
            re.IGNORECASE,
        ):
            return True

        # Skip lines that are only small numbers (common when Camelot picks up table index values)
        if re.fullmatch(r"\d{1,4}", l):
            return True

        return False

    # Backward-compatible alias if you previously used _skip_header_line name
    def _skip_header_line(self, line: str) -> bool:
        """
        PURPOSE:
            Backward-compatible alias for _skip_side_header_line.

        RETURNS:
            True if line should be skipped from MAIN header capture.
        """
        return self._skip_side_header_line(line)

    def _find_line_index(self, lines: List[str], pattern: str) -> Optional[int]:
        """
        PURPOSE:
            Finds the index of the first line that matches a regex pattern.

        RETURNS:
            Index if found, otherwise None.
        """
        rx = re.compile(pattern, re.IGNORECASE)
        for i, line in enumerate(lines):
            if rx.search(line):
                return i
        return None

    def _fallback_find_ministry(self, head: List[str]) -> Optional[str]:
        """
        PURPOSE:
            Fallback ministry detection if the exact MINISTERIO line isn't found.

        SCENARIO THIS HELPS:
            Camelot sometimes slightly changes the ministry line (extra spacing,
            partial extraction). This tries to pick the best candidate line.

        RETURNS:
            A best-guess ministry line, or None.
        """
        for line in head:
            if re.search(r"\bMINISTERIO\b", line, re.IGNORECASE):
                return line

        best = None
        best_score = 0.0

        for line in head[:15]:
            if self._skip_side_header_line(line):
                continue
            letters = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", line)
            if len(letters) < 8:
                continue
            upper = sum(1 for c in letters if c.isupper())
            score = upper / max(len(letters), 1)
            if score > best_score and len(line) >= 10:
                best = line
                best_score = score

        return best

    def _extract_labeled_value(self, text: str, label_pattern: str) -> Optional[str]:
        """
        PURPOSE:
            Extracts a numeric value that appears after a label like PARTIDA/CAPÍTULO/PROGRAMA.

        MATCHES FORMATS LIKE:
            - PARTIDA : 11
            - PARTIDA:11
            - PARTIDA 11

        RETURNS:
            A zero-padded 2-digit string when appropriate, else raw numeric string.
            Returns None if not found.
        """
        if not text:
            return None

        rx = re.compile(label_pattern + r"\s*[:\-]?\s*([0-9]{1,3})", re.IGNORECASE)
        m = rx.search(text)
        if not m:
            return None

        val = m.group(1)
        return val.zfill(2) if len(val) <= 2 else val

    def _is_service_continuation(self, line: str) -> bool:
        """
        PURPOSE:
            Decide if a header line is a continuation of the service_component.

        SCENARIO THIS RESOLVES:
            Service components that wrap onto the next line starting with common
            Spanish prepositions/articles, e.g.:
                "Servicio Hidrográfico y Oceanográfico"
                "de la Armada de Chile"

        RETURNS:
            True if the line should be appended to service_component.
        """
        s = (line or "").strip()
        if not s:
            return False

        return bool(re.match(r"^(de|del|de la|de los|de las|la|las|los)\b", s, flags=re.IGNORECASE))

    def _dedupe_preserve_order(self, lines: List[str]) -> List[str]:
        """
        PURPOSE:
            Removes duplicate lines while preserving original order.

        RETURNS:
            De-duplicated list of strings.
        """
        seen = set()
        out: List[str] = []
        for s in lines:
            key = (s or "").strip()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _split_repeated_wrapped_header_blocks(self, captured: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        PURPOSE:
            Converts 'captured' header lines into service_component and sub_component.

        SCENARIOS THIS RESOLVES:
            1) Wrapped service component lines:
                ["Servicio Hidrográfico y Oceanográfico", "de la Armada de Chile", ...]
               Should become:
                service_component = "Servicio Hidrográfico y Oceanográfico de la Armada de Chile"

            2) Duplicate wrapped block repeated twice due to PDF layout:
                ["Servicio X", "de la Y", "Servicio X", "de la Y"]
               Should become:
                service_component = "Servicio X de la Y"
                sub_component = None

            3) Sub_component spanning multiple lines (e.g. long "(01, 02, ...)" lists)
               Should become:
                sub_component = "<all remainder lines joined>"

        RETURNS:
            (service_component, sub_component)
        """
        if not captured:
            return None, None

        # Clean + remove empties
        cleaned = [self._clean_header_artifacts(self._normalize_whitespace(x)) for x in captured if self._normalize_whitespace(x)]
        if not cleaned:
            return None, None

        # Detect repetition: if first half == second half, keep only first half
        if len(cleaned) % 2 == 0:
            half = len(cleaned) // 2
            if cleaned[:half] == cleaned[half:]:
                cleaned = cleaned[:half]

        # De-dupe (sometimes Camelot repeats a line)
        cleaned = self._dedupe_preserve_order(cleaned)

        # If after clean we only have 1 line
        if len(cleaned) == 1:
            return cleaned[0], None

        service = cleaned[0]
        remainder: List[str] = []

        # Try to attach continuation lines to service_component first
        for line in cleaned[1:]:
            if service and self._is_service_continuation(line):
                service = f"{service} {line}".strip()
            else:
                remainder.append(line)

        sub = None
        if remainder:
            sub = " ".join(remainder).strip()

        return service or None, sub or None

    # ---------------------------
    # Main header extraction
    # ---------------------------

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
            Extracts ONLY the main report header information (top-center header)
            from a single PDF page using Camelot.

        OUTPUT FIELDS:
            - ministry: str | None
            - service_component: str | None
            - sub_component: str | None
            - raw_main_header_lines: List[str] | None

        KEY FIXES INCLUDED:
            - Prevents spaced-letter bug via smart cell joining.
            - Captures up to 4 lines after ministry.
            - Properly keeps "Programa Fidae (01)" as part of main header values.
            - Handles duplicate wrapped header blocks.
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
                extracted_lines.extend(self._lines_from_camelot_df(t.df, drop_side_header=True))

        lines = self._clean_lines("\n".join(extracted_lines))
        head = lines[:40]

        if debug:
            print("\n" + "=" * 90)
            print(f"[DEBUG] header_main_area={header_main_area} | tables_found={main_tables.n}")
            print("=== MAIN REPORT HEADER AREA LINES (CAMELOT) ===")
            for i, l in enumerate(head):
                print(f"{i:02d}: {l}")

        ministry_idx = self._find_line_index(head, r"\bMINISTERIO\b")
        ministry = head[ministry_idx] if ministry_idx is not None else self._fallback_find_ministry(head)

        start_after_ministry_idx = ministry_idx if ministry_idx is not None else None

        captured: List[str] = []
        if start_after_ministry_idx is not None:
            # Capture up to 4 lines after ministry (service + possible wraps + subcomponent + possible wraps)
            for line in head[start_after_ministry_idx + 1 : start_after_ministry_idx + 15]:
                if self._skip_side_header_line(line):
                    continue
                captured.append(line)
                if len(captured) >= 4:
                    break

        service_component, sub_component = self._split_repeated_wrapped_header_blocks(captured)

        raw_main_header_lines: Optional[List[str]] = ([ministry] if ministry else []) + captured
        if not raw_main_header_lines:
            raw_main_header_lines = None

        if debug:
            print(f"[DEBUG] ministry_idx={ministry_idx}, ministry={ministry!r}")
            print(f"[DEBUG] captured={captured!r}")
            print(f"[DEBUG] service_component={service_component!r}")
            print(f"[DEBUG] sub_component={sub_component!r}")
            print(f"[DEBUG] raw_main_header_lines={raw_main_header_lines!r}")

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
        flavor: str = "stream",
        strip_text: str = "\n",
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        PURPOSE:
            Batch wrapper for extract_main_report_header over many pages.

        RETURNS:
            List of dicts, each dict includes page_num and main header fields.
        """
        results: List[Dict[str, Any]] = []
        for page in page_numbers:
            out = self.extract_main_report_header(
                pdf_path=pdf_path,
                page_num=page,
                header_main_area=header_main_area,
                flavor=flavor,
                strip_text=strip_text,
                debug=debug,
            )
            results.append({"page_num": page, **out})
        return results

    # ---------------------------
    # Side header extraction
    # ---------------------------

    def extract_side_report_header(
        self,
        pdf_path: str,
        page_num: int,
        *,
        header_side_area: str,
        flavor: str = "stream",
        strip_text: str = "\n",
        debug: bool = False,
    ) -> Dict[str, HeaderValue]:
        """
        PURPOSE:
            Extracts ONLY the report side header values (PARTIDA/CAPÍTULO/PROGRAMA)
            from the top-right grey box on a single PDF page using Camelot.

        RETURNS:
            Dict with:
              - partida: str | None
              - capitulo: str | None
              - programa: str | None
              - raw_side_header_lines: List[str] | None
        """
        camelot_page = str(page_num + 1)

        side_tables = camelot.read_pdf(
            pdf_path,
            pages=camelot_page,
            flavor=flavor,
            table_areas=[header_side_area],
            strip_text=strip_text,
        )

        side_lines: List[str] = []
        if side_tables.n > 0:
            for t in side_tables:
                # Do NOT drop side-header cells here; this region is the side header itself
                side_lines.extend(self._lines_from_camelot_df(t.df, drop_side_header=False))

        side_clean = self._clean_lines("\n".join(side_lines))
        side_text = self._normalize_whitespace(" ".join(side_clean))

        if debug:
            print("\n" + "=" * 90)
            print(f"[DEBUG] SIDE HEADER | page_num={page_num} -> camelot_page={camelot_page}")
            print(f"[DEBUG] header_side_area={header_side_area} | tables_found={side_tables.n}")
            print("=== SIDE HEADER AREA LINES (CAMELOT) ===")
            for i, l in enumerate(side_clean[:30]):
                print(f"{i:02d}: {l}")
            print(f"[DEBUG] side_text={side_text!r}")

        partida = self._extract_labeled_value(side_text, r"\bPARTIDA\b")
        capitulo = self._extract_labeled_value(side_text, r"\bCAP[IÍ]TULO\b")
        programa = self._extract_labeled_value(side_text, r"\bPROGRAMA\b")

        raw_side_header_lines: Optional[List[str]] = side_clean if side_clean else None

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
        flavor: str = "stream",
        strip_text: str = "\n",
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        PURPOSE:
            Batch wrapper for extract_side_report_header over many pages.

        RETURNS:
            List of dicts, each dict includes page_num and side header fields.
        """
        results: List[Dict[str, Any]] = []
        for page in page_nums:
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

    # ---------------------------
    # Combined extractor (merge)
    # ---------------------------

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
            Extracts BOTH main header and side header from multiple PDF pages,
            and merges results per page_num.

        RETURNS:
            Dict keyed by page_num (int). Each value is:
              {
                "page_num": <int>,
                "main_header": {...},
                "side_header": {...}
              }
        """
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

        # Index by page_num (force int), warn on duplicates
        main_by_page: Dict[int, Dict[str, Any]] = {}
        for d in main_list:
            if "page_num" not in d:
                continue
            k = int(d["page_num"])
            if k in main_by_page and debug:
                print(f"[WARN] duplicate main header page_num={k} overwriting previous entry")
            main_by_page[k] = d

        side_by_page: Dict[int, Dict[str, Any]] = {}
        for d in side_list:
            if "page_num" not in d:
                continue
            k = int(d["page_num"])
            if k in side_by_page and debug:
                print(f"[WARN] duplicate side header page_num={k} overwriting previous entry")
            side_by_page[k] = d

        merged: Dict[int, Dict[str, Any]] = {}

        for p in page_nums:
            main = main_by_page.get(p, {})
            side = side_by_page.get(p, {})

            # Remove duplicated "page_num" keys inside the child dicts
            main = {k: v for k, v in main.items() if k != "page_num"}
            side = {k: v for k, v in side.items() if k != "page_num"}

            if debug:
                print(f"[DEBUG] merge page={p} | main_keys={list(main.keys())} | side_keys={list(side.keys())}")
                print(f"[DEBUG] main_sub_component={main.get('sub_component')!r}")
                print(f"[DEBUG] main_raw_lines={main.get('raw_main_header_lines')!r}")

            merged[p] = {
                "page_num": p,
                "main_header": main,
                "side_header": side,
            }

        return merged
