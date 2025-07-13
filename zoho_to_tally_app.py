import streamlit as st
import zipfile
import os
import pandas as pd
from lxml import etree
from datetime import datetime
import io
import tempfile
import shutil
import math
from xml.sax.saxutils import escape as xml_escape

# --- Configuration (Streamlit App) ---
# List of expected Zoho CSV files from the ZIP backup
ZOHO_CSVS = [
    'Chart_of_Accounts.csv',
    'Contacts.csv',
    'Vendors.csv',
    'Invoice.csv',
    'Customer_Payment.csv',
    'Vendor_Payment.csv',
    'Credit_Note.csv',
    'Journal.csv',
    'Bill.csv',
    'Sales_Order.csv', # Included in list but not fully processed for Tally XML in current scope
    'Purchase_Order.csv', # Included in list but not fully processed for Tally XML in current scope
    'Item.csv' # Included in list but not fully processed for Tally XML in current scope
]

# Company details (YOU MUST UPDATE THESE TO MATCH YOUR TALLY COMPANY EXACTLY)
TALLY_COMPANY_NAME = "Plant Essentials Private Limited"
BASE_CURRENCY_SYMBOL = "₹"
BASE_CURRENCY_NAME = "Rupees"
DEFAULT_COUNTRY = "India" # Assuming default country for addresses

# --- Helper Functions ---

def safe_str(value):
    """
    Converts a value to string, handling NaN/None gracefully,
    and escapes XML special characters.
    """
    if pd.isna(value):
        return ""
    s_val = str(value).strip()
    return xml_escape(s_val) # Apply XML escaping here

def format_tally_date(date_str):
    """Converts 'YYYY-MM-DD' string to Tally's 'YYYYMMDD' format."""
    if not date_str:
        return ""
    try:
        dt_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return dt_obj.strftime('%Y%m%d')
    except ValueError:
        st.warning(f"Invalid date format encountered: {date_str}. Returning empty string for date.")
        return ""

def format_tally_amount(amount):
    """Formats a numeric amount for Tally, handling NaN."""
    if pd.isna(amount):
        return "0.00"
    try:
        # Ensure conversion to float happens right before formatting
        return f"{float(amount):.2f}"
    except (ValueError, TypeError): # Catch both Value and Type errors for robustness
        st.warning(f"Invalid amount encountered: {amount}. Returning '0.00'.")
        return "0.00"


def create_tally_envelope(report_name="All Masters", request_xml_tags="ACCOUNTS"):
    """
    Creates the basic Tally XML envelope structure.
    report_name: "All Masters" for ledgers/groups, "Vouchers" for transactions.
    request_xml_tags: "ACCOUNTS" for masters, "VOUCHERS" for transactions.
    """
    envelope = etree.Element("ENVELOPE")
    header = etree.SubElement(envelope, "HEADER")
    etree.SubElement(header, "TALLYREQUEST").text = "Import"
    etree.SubElement(header, "VERSION").text = "1" # Or higher based on Tally version
    body = etree.SubElement(envelope, "BODY")
    import_data = etree.SubElement(body, "IMPORTDATA")
    request_desc = etree.SubElement(import_data, "REQUESTDESC")
    etree.SubElement(request_desc, "REPORTNAME").text = report_name
    etree.SubElement(request_desc, "STATICVARIABLES")
    etree.SubElement(etree.SubElement(request_desc.find('STATICVARIABLES'), "SVEXPORTFORMAT"), "IMPORTDATA.ENDFORMTYPE").text = "XML Software"
    etree.SubElement(etree.SubElement(request_desc.find('STATICVARIABLES'), "SVEXPORTFORMAT"), "IMPORTDATA.REQUEST.XMLTAGS").text = request_xml_tags

    request_data = etree.SubElement(import_data, "REQUESTDATA")
    tally_message = etree.SubElement(request_data, "TALLYMESSAGE")
    return envelope, tally_message

# --- Data Cleaning and Mapping Functions (from 02_clean_map.py) ---

def format_date_column(df, column_name):
    """Converts a column to datetime objects and then formats as 'YYYY-MM-DD' string."""
    if column_name in df.columns:
        # Attempt to convert to datetime, coercing errors
        df[column_name] = pd.to_datetime(df[column_name], errors='coerce')
        # Format valid dates, set invalid/NaT dates to empty string
        df[column_name] = df[column_name].dt.strftime('%Y-%m-%d').fillna('')
    return df

def clean_numeric_column(df, column_name):
    """Converts a column to numeric, filling NaNs with 0.0."""
    if column_name in df.columns:
        df[column_name] = pd.to_numeric(df[column_name], errors='coerce').fillna(0.0)
    return df

def process_chart_of_accounts(df):
    st.info("Processing Chart of Accounts...")
    if df is None: return None

    account_type_map = {
        'Asset': 'Current Assets', 'Bank': 'Bank Accounts', 'Cash': 'Cash-in-Hand',
        'Expense': 'Indirect Expenses', 'Cost of Goods Sold': 'Direct Expenses',
        'Equity': 'Capital Account', 'Income': 'Indirect Incomes',
        'Other Income': 'Indirect Incomes', 'Liability': 'Current Liabilities',
        'Other Current Asset': 'Current Assets', 'Other Current Liability': 'Current Liabilities',
        'Account Receivable': 'Sundry Debtors', 'Account Payable': 'Sundry Creditors',
        'Fixed Asset': 'Fixed Assets', 'Loan (Liability)': 'Loans (Liability)',
        'Other Asset': 'Current Assets', 'Stock': 'Stock-in-Hand',
        'Cess': 'Duties & Taxes', 'TDS Receivable': 'Duties & Taxes',
        'TDS Payable': 'Duties & Taxes', 'CGST': 'Duties & Taxes',
        'SGST': 'Duties & Taxes', 'IGST': 'Duties & Taxes',
        'Service Tax': 'Duties & Taxes', 'Professional Tax': 'Duties & Taxes',
        'TCS': 'Duties & Taxes', 'Advance Tax': 'Duties & Taxes',
        'Secured Loan': 'Secured Loans', 'Unsecured Loan': 'Unsecured Loans',
        'Provisions': 'Provisions', 'Branch / Division': 'Branch / Divisions',
        'Statutory': 'Duties & Taxes', 'Other Liability': 'Current Liabilities',
        'Retained Earnings': 'Reserves & Surplus', 'Long Term Liability': 'Loans (Liability)',
        'Long Term Asset': 'Fixed Assets', 'Loan & Advance (Asset)': 'Loans & Advances (Asset)',
        'Stock Adjustment Account': 'Direct Expenses', 'Uncategorized': 'Suspense A/c'
    }

    if 'Account Type' in df.columns:
        df['Tally_Parent_Group'] = df['Account Type'].astype(str).apply(lambda x: account_type_map.get(x, 'Suspense A/c'))
    else:
        df['Tally_Parent_Group'] = 'Suspense A/c' # Default if Account Type is missing

    # Use .get() method for renaming to avoid KeyError if original column does not exist
    df_mapped = df.rename(columns={
        'Account Name': 'Tally_Ledger_Name',
        'Account Code': 'Tally_Account_Code',
        'Description': 'Tally_Description',
        'Account Status': 'Tally_Status',
    }, errors='ignore') # 'errors=ignore' will keep original column name if new is not found

    # Fill missing values for string columns - check for column existence first
    if 'Tally_Description' in df_mapped.columns:
        df_mapped['Tally_Description'] = df_mapped['Tally_Description'].fillna('')
    if 'Tally_Account_Code' in df_mapped.columns:
        df_mapped['Tally_Account_Code'] = df_mapped['Tally_Account_Code'].fillna('')
    if 'Parent Account' in df_mapped.columns:
        df_mapped['Parent Account'] = df_mapped['Parent Account'].fillna('')

    columns_to_select = [
        'Account ID', 'Tally_Ledger_Name', 'Tally_Account_Code', 'Tally_Description',
        'Account Type', 'Tally_Parent_Group', 'Tally_Status', 'Currency', 'Parent Account'
    ]
    # Check if 'Opening Balance' column exists before trying to select it
    if 'Opening Balance' in df_mapped.columns:
        columns_to_select.append('Opening Balance')
        st.info("Found 'Opening Balance' column in Chart_of_Accounts.csv. Including it.")
    else:
        st.warning("No 'Opening Balance' column found in Chart_of_Accounts.csv. Ledgers will be created with 0.00 opening balance unless specified otherwise in Contacts/Vendors.")
    
    # Filter columns to only those that exist in df_mapped to prevent KeyError
    existing_columns_to_select = [col for col in columns_to_select if col in df_mapped.columns]
    df_processed = df_mapped[existing_columns_to_select].copy()

    st.success(f"Processed {len(df_processed)} Chart of Accounts entries.")
    return df_processed

def process_contacts(df):
    st.info("Processing Contacts...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Last Modified Time')

    string_cols = [
        'Display Name', 'Company Name', 'Salutation', 'First Name', 'Last Name',
        'Phone', 'EmailID', 'MobilePhone', 'Website', 'Notes', 'Status',
        'Billing Attention', 'Billing Address', 'Billing Street2', 'Billing City',
        'Billing State', 'Billing Country', 'Billing Code', 'Billing Phone', 'Billing Fax',
        'Shipping Attention', 'Shipping Address', 'Shipping Street2', 'Shipping City',
        'Shipping State', 'Shipping Country', 'Shipping Code', 'Shipping Phone', 'Shipping Fax',
        'Skype Identity', 'Facebook', 'Twitter', 'Department', 'Designation',
        'Price List', 'Payment Terms', 'Payment Terms Label', 'GST Treatment',
        'GST Identification Number (GSTIN)', 'Owner Name', 'Primary Contact ID',
        'Contact ID', 'Contact Name', 'Contact Type', 'Place Of Contact', 'Place of Contact(With State Code)',
        'Taxable', 'TaxID', 'Tax Name', 'Tax Type', 'Exemption Reason', 'Source'
    ]
    for col in string_cols:
        if col in df_cleaned.columns: # Check for column existence
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    numeric_cols = ['Credit Limit', 'Opening Balance', 'Opening Balance Exchange Rate', 'Tax Percentage']
    for col in numeric_cols
