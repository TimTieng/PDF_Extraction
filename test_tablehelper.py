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
def test_extract_report_header():
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
        debug=True,
    )

    print("\n=== EXTRACTED REPORT HEADER ===")
    for k, v in header.items():
        print(f"{k}: {v}")


def test_extract_main_report_header_single_pages():
    yaml_path = "config/chile_pdf.yaml"
    config = load_yaml(yaml_path)

    pdf_path = "data/chile_budget_2025.pdf"
    page_nums = [553,555,557,558,560,562,564,566,567,569,571,573,575,576,579,580,581,723]
    header_area = config["header_areas"]["header_main"]

    helper = TableHelper()

    for page in page_nums:
        header = helper.extract_main_report_header_return_list(
            pdf_path=pdf_path,
            page_numbers=[page],
            header_main_area=header_area,
            flavor="stream",
            debug=True,
        )

        print(f"\n=== PAGE {page} MAIN HEADER ===")
        # for k, v in header.items():
        #     print(f"{k}: {v}")
        for header in header:
            print(header)


# Primary Orchestration/Execution Function 
# This is the main function that will be executed when the script runs
def execute_orchestration() -> None:
    """
    PURPOSE:
        Wraps the main orchestration logic for the script. 
        Add step-by-step logic in function form here as needed.
    """
    print("\n-------- TESTING EXTRACT REPORT HEADER FUNCTION --------\n")
    test_extract_report_header()

    print("\n-------- TESTING EXTRACT MAINREPORT HEADER RETURN LIST FUNCTION --------\n")
    test_extract_main_report_header_single_pages()


if __name__ == "__main__":
    start_time = time.time()
    # Main execution code goes here
    execute_orchestration()
    
    end_time = time.time()
    print(f"\nScript Execution Complete.")
    print(f"\nExecution Time: {end_time - start_time} seconds")
# ----------- END OF SCRIPT ------------