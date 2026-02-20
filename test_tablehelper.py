"""
CREATED DATE: YYYY-MM-DD
AUTHOR: TIM T
PURPOSE: Main template for Python scripts

MODIFIED DATE: YYYY-MM-DD
MODIFIED BY: 
CHANGE DESCRIPTION: 

DATA SOURCES:

EXECUTION INSTRUCTIONS:

CONCEPTUAL OVERVIEW/LOGIC FLOW:
"""
# Standard Python Packages
import time
import camelot
import pandas as pd
import yaml

# Specialty/Custom Packages
from tablehelper import TableHelper

# Pandas display options
pd.set_option("display.max_rows", 100)
pd.set_option("display.max_colwidth", 60)
pd.set_option("display.width", 140)


# YAML Loader function
def load_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

# Function that will be tested
def test_extract_main_report_header():
    """
    PURPOSE:
        imports and calls the report header
    
    PARAMETERS:
        message (str): The message to be printed.
    
    RETURNS:
        None
    """
    print(f"Loading yaml configuration from 'chile_pdf.yaml")
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)

    pdf_path = "data/chile_budget_2025.pdf"
    page_num = 553 
    
    header_area = config['header_areas']['header_main']

    helper = TableHelper()

    header = helper.extract_main_report_header(
        pdf_path=pdf_path,
        page_num=page_num,
        header_main_area=header_area,
        flavor="stream",
        debug=False,
    )

    print("\n=== EXTRACTED REPORT HEADER ===")
    for k, v in header.items():
        print(f"{k}: {v}")


def test_extract_main_report_header_return_list():
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)

    pdf_path = "data/chile_budget_2025.pdf"
    pages = [553,555,557,558,560,562,564,566,567,569,571,572,573,575,576,579,580,581,723]
    header_area = config["header_areas"]["header_main"]

    helper = TableHelper()

    main_header_list = helper.extract_main_report_header_return_list(
        pdf_path=pdf_path,
        page_numbers=pages,
        header_main_area=header_area,
        flavor="stream",
        debug=False,
    )
    print(main_header_list)


def test_extract_side_report_header_return_list():
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)

    pdf_path = "data/chile_budget_2025.pdf"
    pages = [553,555,557,558,560,562,564,566,567,569,571,572,573,575,576,579,580,581,723]
    header_area = config["header_areas"]["header_side"]

    helper = TableHelper()

    side_header_list = helper.extract_side_report_header_return_list(
        pdf_path=pdf_path,
        page_numbers=pages,
        header_side_area=header_area,
        flavor="stream",
        debug=False,
    )
    print(side_header_list)
    print("=" * 90)


def teset_combined_report_header_return_list():
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)

    pdf_path = "data/chile_budget_2025.pdf"
    pages = [553,555,557,558,560,562,564,566,567,569,571,572,573,575,576,579,580,581,723]
    header_main_area = config["header_areas"]["header_main"]
    header_side_area = config["header_areas"]["header_side"]

    helper = TableHelper()

    combined_header_list = helper.extract_combined_report_headers_return_list(
        pdf_path=pdf_path,
        page_nums=pages,
        header_main_area=header_main_area,
        header_side_area=header_side_area,
        flavor="stream",
        debug=False,
    )

    # Print to the terminal
    for page_num, information in combined_header_list.items():
        print("\n" + "=" * 90)
        print(f"PAGE NUMBER: {page_num}")
        print(f"\nMAIN REPORT HEADERS\n")
        for k, v in information['main_header'].items():
            print(f"    {k}:    {v}")
        print(f"\nSIDE REPORT HEADERS\n")
        for k, v in information['side_header'].items():
            print(f"    {k}:    {v}")


def test_service_component_table_template_a():
    """
    testing the extraction of service component table template A
    """
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)
    pdf_path = "data/chile_budget_2025.pdf"
    page = 554
    service_component_table_area = config['service_component_table_areas']['template_a_with_usd']['table_area_preview']
    helper = TableHelper()

    df = helper.extract_service_component_table_template_a(
        pdf_path=pdf_path,
        page=page,
        config=config,
    )

    print(df)
    print(f"Extracted rows={df.shape[0]}, cols={df.shape[1]} from page={page}")


def test_sc_table_template_a_from_list():
    """
    Testing extraction of service component table template A
    page-by-page with readable terminal output.
    """
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)
    pdf_path = "data/chile_budget_2025.pdf"
    pages = [554, 559, 565,582]

    helper = TableHelper()

    for page in pages:
        print("\n" + "=" * 80)
        print(f"PAGE {page} — SERVICE COMPONENT TABLE (TEMPLATE A)")
        print("=" * 80)

        try:
            df = helper.extract_service_component_table_template_a(
                pdf_path=pdf_path,
                page=page,
                config=config,
            )

            print(df)
            print(
                f"\nExtracted rows={df.shape[0]}, cols={df.shape[1]} "
                f"from page={page}"
            )

        except Exception as e:
            print(f"\n FAILED on page {page}")
            print(e)


def test_service_component_table_template_b_single_page():
    """
    Test extraction of a single 5-column Template B service component table.
    """
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)
    pdf_path = "data/chile_budget_2025.pdf"
    page = 556

    helper = TableHelper()

    df = helper.extract_service_component_table_template_b(
        pdf_path=pdf_path,
        page=page,
        config=config,
    )

    print("\n" + "=" * 80)
    print(f"PAGE {page} — SERVICE COMPONENT TABLE (TEMPLATE B, 5 COL)")
    print("=" * 80)
    print(df)
    print(f"\nExtracted rows={df.shape[0]}, cols={df.shape[1]} from page={page}")


def test_sc_table_template_b_from_list():
    """
    Testing extraction of service component table Template B from a list of pages.
    """
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)
    pdf_path = "data/chile_budget_2025.pdf"
    # pages = [556,558,561,563,567,568,570]
    pages = [556,558,561,563,567,568,570,572,573,574,576,577,580,581]

    helper = TableHelper()

    df = helper.extract_service_component_tables_template_b_from_list(
        pdf_path=pdf_path,
        pages=pages,
        config=config,
    )

    for page in pages:
        page_df = df[df["source_page"] == int(page)].copy()
        page_df = page_df.drop(columns=["source_page", "has_glosas"], errors="ignore")

        print("\n" + "=" * 80)
        print(f"PAGE {page} — SERVICE COMPONENT TABLE (TEMPLATE B, 5 COL)")
        print("=" * 80)
        with pd.option_context(
            "display.max_columns", None,
            "display.max_colwidth", None,
            "display.width", 2000,
            "display.expand_frame_repr", False,
        ):
            print(page_df.reset_index(drop=True).to_string(index=True))
        print(
            f"\nExtracted rows={page_df.shape[0]}, cols={page_df.shape[1]} "
            f"from page={page}"
        )


def test_extract_glosas_section_from_list():
    """
    PURPOSE:
        Test extraction of the GLOSAS section using PyMuPDF text extraction,
        stitching continuation pages when needed.

    NOTES:
        - This test reads the page height/width directly from the PDF via PyMuPDF
          to avoid hard-coding dimensions.
        - Update `pages` to the pages where you expect a GLOSAS section to start.
    """
    import pymupdf  # local import to keep dependencies obvious

    yaml_path = "config/chile_pdf.yaml"
    _ = load_yaml(yaml_path)  # currently unused, but kept for consistency with other tests

    pdf_path = "data/chile_budget_2025.pdf"

    # Pages the GLOSAS heading  appear (start pages)
    pages = [555, 556, 558, 559, 561, 563,566,567,568, 570, 572, 573, 575,576, 577, 580, 581, 582]

    helper = TableHelper()

    with pymupdf.open(pdf_path) as doc:
        for page in pages:
            print("\n" + "=" * 80)
            print(f"PAGE {page} — GLOSAS SECTION")
            print("=" * 80)

            page_idx = int(page) - 1
            if page_idx < 0 or page_idx >= doc.page_count:
                print(f"SKIP: page {page} out of range (doc has {doc.page_count} pages)")
                continue

            # Pull page dimensions straight from the PDF
            page_obj = doc[page_idx]
            page_height = float(page_obj.rect.height)
            page_width = float(page_obj.rect.width)

            try:
                res = helper.extract_glosas_section(
                    pdf_path=pdf_path,
                    page=int(page),
                    page_height=page_height,
                    page_width=page_width,
                    keyword="GLOSAS",
                    max_pages=3,
                    footer_cut_points=45.0,
                    debug=True,
                )

                if not res.get("found"):
                    print("GLOSAS heading not found on this page.")
                    continue

                print(f"Start page: {res.get('start_page')} | End page: {res.get('end_page')}")
                pages_used = [p.get("page") for p in res.get("pages", [])]
                print(f"Pages stitched: {pages_used}")

                full_text = res.get("text", "") or ""
                # Print Full Text
                print("\n--- FULL EXTRACTED TEXT ---")
                print(full_text)

                # Uncomment below for quick preview of text segments in terminal (adjust char counts as needed)
                # print("\n--- TEXT (first 800 chars) ---")
                # print(full_text[:800])

                # if len(full_text) > 800:
                #     print("\n--- TEXT (last 400 chars) ---")
                #     print(full_text[-400:])

                # Quick sanity checks: page number leakage is a common failure mode
                # (this is heuristic; adjust if your PDFs contain numeric-only lines legitimately)
                leaked = [ln for ln in full_text.splitlines()[-8:] if ln.strip().isdigit()]
                if leaked:
                    print("\nWARNING: potential footer/page-number leakage near end:")
                    print(leaked)

                if res.get("debug"):
                    # Print bbox diagnostics (PDF-space regions)
                    print("\n--- DEBUG REGIONS ---")
                    for r in res["debug"].get("regions", []):
                        print(f"page={r['page']} region_pdf={r['region_pdf']} lines={r['lines']}")

            except Exception as e:
                print(f"FAILED on page {page}")
                print(e)

# Primary Orchestration/Execution Function 
# This is the main function that will be executed when the script runs
def execute_tests() -> None:
    """
    PURPOSE:
        Wraps the main orchestration logic for the script. 
        Add step-by-step logic in function form here as needed.
    """
    # print("\n-------- TESTING EXTRACT REPORT HEADER FUNCTION --------\n")
    # test_extract_main_report_header()

    # print("\n-------- TESTING EXTRACT MAINREPORT HEADER RETURN LIST FUNCTION --------\n")
    # test_extract_main_report_header_return_list()

    # print("\n-------- TESTING EXTRACT SIDE REPORT HEADER RETURN LIST FUNCTION --------\n")
    # test_extract_side_report_header_return_list()

    print("\n-------- TESTING EXTRACT COMBINED REPORT HEADER RETURN LIST FUNCTION --------\n")
    teset_combined_report_header_return_list()

    # print("-------- TESTING SERVICE COMPONENT TABLE TEMPLATE A FUNCTION --------\n")
    # test_service_component_table_template_a()

    print("-------- TESTING SERVICE COMPONENT TABLE TEMPLATE A FROM LIST FUNCTION --------\n")
    test_sc_table_template_a_from_list()

    # print("-------- TESTING SERVICE COMPONENT TABLE TEMPLATE B SINGLE PAGE FUNCTION --------\n")
    # test_service_component_table_template_b_single_page()

    print("-------- TESTING SERVICE COMPONENT TABLE TEMPLATE B FROM LIST FUNCTION --------\n")
    test_sc_table_template_b_from_list()

    print("-------- TESTING GLOSAS EXTRACTION FROM LIST FUNCTION --------\n")
    test_extract_glosas_section_from_list()
    


if __name__ == "__main__":
    start_time = time.time()
    # Main execution code goes here
    execute_tests()
    
    end_time = time.time()
    print(f"\nScript Execution Complete.")
    print(f"\nExecution Time: {end_time - start_time} seconds")
# ----------- END OF SCRIPT ------------
