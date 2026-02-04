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
import yaml

# Specialty/Custom Packages
from tablehelper import TableHelper

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
    


if __name__ == "__main__":
    start_time = time.time()
    # Main execution code goes here
    execute_tests()
    
    end_time = time.time()
    print(f"\nScript Execution Complete.")
    print(f"\nExecution Time: {end_time - start_time} seconds")
# ----------- END OF SCRIPT ------------