from enum import Enum
from datetime import datetime
import sys
import csv

class Classification(Enum):
    """ Classification object. Individual allocations may have different classifications """
    U = "Unclassified"
    C = "Confidential"
    S = "Secret"
    TS = "Top Secret"

class Version(Enum):
    """ Version object representing the funding phase of the reported allocation. """
    Requested = "Requested"
    Appropriated = "Appropriated"
    Disbursed = "Disbursed"

class Admin:
    """ Admin object tracking data about the creation of the National Budget object. """

    def __init__(self, date_created: datetime = None, date_reviewed: datetime = None, citation_list: list = None, classification: Classification = None):
        self.date_created = date_created
        self.date_reviewed = date_reviewed
        self.citation_list = citation_list
        self.classification = classification
        return None

    def __str__(self):
        """
        Create string representation for pretty printing.

        Output in the format of a formatted string.
        """
        return f"Admin: Created: {self.date_created.strftime('%Y-%m-%d')}, Reviewed: {self.date_reviewed.strftime('%Y-%m-%d')}, Sources: {len(self.citation_list)}, Class: {self.classification}."


class Pedigree:
    """ Pedigree object tracking data about the source of the National Budget object. """

    def __init__(self, citation: str = None, source_date: datetime = None):
        self.citation = citation
        self.source_date = source_date
        return None

    def __str__(self):
        """
        Create string representation for pretty printing.

        Output in the format of a formatted string.
        """
        return f"Pedigree: Citation is {self.citation} with source date {self.source_date.strftime('%Y-%m-%d')}"


class Subitem:
    """ Subitem object """

    def __init__(self, name: str = None, code: str = None, note_numbers = [], amount_pesos: float = None, amount_usd: float = None):
        self.name = name
        self.code = code
        self.note_numbers = note_numbers
        self.amount_pesos = amount_pesos
        self.amount_usd = amount_usd
        return None


    """
    Create string representation for pretty printing. Output is a formatted string.
    """

    def __str__(self):
        return f"SubItem: {self.name}, code {self.code}."


class Item:
    """ Item object """

    def __init__(self, name: str = None, code: str = None, note_numbers = [], total_amount_pesos: float = None, total_amount_usd: float = None):
        self.name = name
        self.code = code
        self.note_numbers = note_numbers
        self.total_amount_pesos = total_amount_pesos
        self.total_amount_usd = total_amount_usd
        self.subitems = {}
        return None

    """
    Add subitem to list of subitems
    """

    def add_item(self, subitem_name: str, subitem: Subitem):
        self.subitems[subitem_name] = subitem


    """
    Create string representation for pretty printing. Output is a formatted string.
    """

    def __str__(self):
        return f"Item: {self.name}, code {self.code}. ({len(self.subitems)} subitems)"


class Subtitle:
    """ Subtitle object """

    def __init__(self, name: str = None, code: str = None, note_numbers = [], total_amount_pesos: float = None, total_amount_usd: float = None):
        self.name = name
        self.code = code
        self.note_numbers = note_numbers
        self.total_amount_pesos = total_amount_pesos
        self.total_amount_usd = total_amount_usd
        self.items = {}
        return None

    """
    Add item to list of items
    """

    def add_item(self, item_name: str, item: Item):
        self.items[item_name] = Item
        return None

    """
    Create string representation for pretty printing. Output is a formatted string.
    """

    def __str__(self):
        return f"Subtitle: {self.name}, code {self.code} ({len(self.items)} Items)"


class Program:
    """ Program (the level below a Unit) object """

    def __init__(self, program_name: str = None, program_code: str = None,
                 total_income_pesos: float = None, total_expenses_pesos: float = None,
                 total_income_usd: float = None, total_expenses_usd: float = None):
        self.program_name = program_name
        self.program_code = program_code
        self.income_subtitles = {}
        self.expense_subtitles = {}
        self.total_income_pesos = total_income_pesos
        self.total_expenses_pesos = total_expenses_pesos
        self.total_income_usd = total_income_usd
        self.total_expenses_usd = total_expenses_usd
        self.notes = {}
        return None

    "add income subtitle to list of income subtitles"

    def add_income_subtitle(self, subtitle_code: str, subtitle: Subtitle):
        self.income_subtitles[subtitle_code] = subtitle
        return None

    "add expense subtitle to list of expense subtitles"

    def add_expense_subtitle(self, subtitle_code: str, subtitle: Subtitle):
        self.expense_subtitles[subtitle_code] = subtitle
        return None

    "add expense subtitle to list of expense subtitles"

    def add_note(self, note_code: str, note: str):
        self.notes[note_code] = note
        return None

    """
    Create string representation for pretty printing. Output is a formatted string.
    """

    def __str__(self):
        return f"Program: {self.program_name} ({len(self.subtitles)} subtitles)"


class Unit:
    """ Unit (the level below a Ministry) object """

    def __init__(self, unit_name: str = None, unit_code: str = None,
                 total_income_pesos: float = None, total_expenses_pesos: float = None,
                 total_income_usd: float = None, total_expenses_usd: float = None):
        self.unit_name = unit_name
        self.unit_code = unit_code
        self.programs = {}
        self.total_income_pesos = total_income_pesos
        self.total_expenses_pesos = total_expenses_pesos
        self.total_income_usd = total_income_usd
        self.total_expenses_usd = total_expenses_usd
        return None

    "add program to list of programs"

    def add_programs(self, subtitle_code: str, subtitle: Subtitle):
        self.income_subtitles[subtitle_code] = subtitle
        return None

    """
    Create string representation for pretty printing. Output is a formatted string.
    """

    def __str__(self):
        return f"Unit: {self.unit_name} ({len(self.programs)} programs)"


class Ministry:
    """
    Class for Ministry object. This contains unit objects.
    """

    def __init__(self, ministry_name: str = None, ministry_code: str = None):
        """
        initialize ministry object
        Parameters
        ----------
        ministry_name : this is ministry name. default is none
        ministry_code : this is ministry code. default is none

        Returns
        ----------
        None.
        """
        self.ministry_name = ministry_name
        self.ministry_code = ministry_code
        self.income_pesos = None
        self.income_usd = None
        self.spending_pesos = None
        self.spending_usd = None
        self.units = {}
        self.pcp = {}
        self.pages = []
        return None

    "add unit to list of units"

    def add_unit(self, unit_name: str, unit: Unit):
        self.units[unit_name] = unit
        return None

    """
    Create string representation for pretty printing. Output is a formatted string.
    """

    def __str__(self):
        return f"Ministry: {self.ministry_name} ({len(self.units)} units)"


class NationalBudget:
    """ National Budget object """
    """ Top level of the heirarchy which breaks down as ministries -> units -> subtitles -> assignments -> subassignments """

    def __init__(self, country: str = None, admin: Admin = None):
        self.country = country
        self.admin = admin
        self.ministries = {}
        return None

    "add ministry to list of ministries"

    def ministry(self, ministry_name: str, ministry: Ministry):
        self.ministries[ministry_name] = ministry
        return None
