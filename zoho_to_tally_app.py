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
# This path is not directly used for file upload but defines expected internal structure
# if manual placement was considered. For Streamlit, we use uploaded files directly.
# ZOHO_ZIP_FILENAME = "Plant Essentials Private Limited_2025-07-09.zip" # Not directly used for upload

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
    'Sales_Order.csv',
    'Purchase_Order.csv',
    'Item.csv'
]

# Company details (YOU MUST UPDATE THESE TO MATCH YOUR TALLY COMPANY EXACTLY)
TALLY_COMPANY_NAME = "Plant Essentials Private Limited"
BASE_CURRENCY_SYMBOL = "₹"
BASE_CURRENCY_NAME = "Rupees"
DEFAULT_COUNTRY = "India" # Assuming default country for addresses

# --- Helper Functions (Reused from previous scripts) ---

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
        st.warning(f"Invalid date format encountered: {date_str}. Returning empty string.")
        return ""

def format_tally_amount(amount):
    """Formats a numeric amount for Tally, handling NaN."""
    if pd.isna(amount):
        return "0.00"
    return f"{amount:.2f}" # Format to 2 decimal places

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
    if column_name in df.columns and not df[column_name].empty:
        df[column_name] = pd.to_datetime(df[column_name], errors='coerce')
        df[column_name] = df[column_name].dt.strftime('%Y-%m-%d').fillna('')
    return df

def clean_numeric_column(df, column_name):
    if column_name in df.columns and not df[column_name].empty:
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
        'TCS': 'Duties & Taxes', 'Advance Tax': 'Duties & & Taxes',
        'Secured Loan': 'Secured Loans', 'Unsecured Loan': 'Unsecured Loans',
        'Provisions': 'Provisions', 'Branch / Division': 'Branch / Divisions',
        'Statutory': 'Duties & Taxes', 'Other Liability': 'Current Liabilities',
        'Retained Earnings': 'Reserves & Surplus', 'Long Term Liability': 'Loans (Liability)',
        'Long Term Asset': 'Fixed Assets', 'Loan & Advance (Asset)': 'Loans & Advances (Asset)',
        'Stock Adjustment Account': 'Direct Expenses', 'Uncategorized': 'Suspense A/c'
    }

    df['Tally_Parent_Group'] = df['Account Type'].astype(str).apply(lambda x: account_type_map.get(x, 'Suspense A/c'))

    df_mapped = df.rename(columns={
        'Account Name': 'Tally_Ledger_Name',
        'Account Code': 'Tally_Account_Code',
        'Description': 'Tally_Description',
        'Account Status': 'Tally_Status',
    })

    df_mapped['Tally_Description'] = df_mapped['Tally_Description'].fillna('')
    df_mapped['Tally_Account_Code'] = df_mapped['Tally_Account_Code'].fillna('')
    df_mapped['Parent Account'] = df_mapped['Parent Account'].fillna('')

    # --- FIX START ---
    # Check if 'Opening Balance' column exists before trying to select it
    columns_to_select = [
        'Account ID', 'Tally_Ledger_Name', 'Tally_Account_Code', 'Tally_Description',
        'Account Type', 'Tally_Parent_Group', 'Tally_Status', 'Currency', 'Parent Account'
    ]
    if 'Opening Balance' in df_mapped.columns:
        columns_to_select.append('Opening Balance')
        st.info("Found 'Opening Balance' column in Chart_of_Accounts.csv. Including it.")
    else:
        st.warning("No 'Opening Balance' column found in Chart_of_Accounts.csv. Ledgers will be created with 0.00 opening balance unless specified otherwise in Contacts/Vendors.")
    
    df_processed = df_mapped[columns_to_select].copy()
    # --- FIX END ---

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
        'Contact Name', 'Contact Type', 'Place Of Contact', 'Place of Contact(With State Code)',
        'Taxable', 'TaxID', 'Tax Name', 'Tax Type', 'Exemption Reason', 'Source'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    numeric_cols = ['Credit Limit', 'Opening Balance', 'Opening Balance Exchange Rate', 'Tax Percentage']
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    df_cleaned['Tally_Billing_Address_Line1'] = df_cleaned['Billing Address'].fillna('')
    df_cleaned['Tally_Billing_Address_Line2'] = df_cleaned['Billing Street2'].fillna('')
    df_cleaned['Tally_Shipping_Address_Line1'] = df_cleaned['Shipping Address'].fillna('')
    df_cleaned['Tally_Shipping_Address_Line2'] = df_cleaned['Shipping Street2'].fillna('')
    df_cleaned['Tally_Billing_State'] = df_cleaned['Billing State']
    df_cleaned['Tally_Shipping_State'] = df_cleaned['Shipping State']

    df_processed = df_cleaned.rename(columns={
        'Display Name': 'Tally_Party_Name',
        'GST Identification Number (GSTIN)': 'Tally_GSTIN',
        'EmailID': 'Tally_Email',
        'Phone': 'Tally_Phone',
        'MobilePhone': 'Tally_Mobile',
        'Credit Limit': 'Tally_Credit_Limit',
        'Place of Contact(With State Code)': 'Tally_Place_of_Supply_Code'
    })

    df_final = df_processed[[
        'Contact ID', 'Tally_Party_Name', 'Company Name', 'Tally_Email',
        'Tally_Phone', 'Tally_Mobile', 'Tally_GSTIN',
        'Tally_Billing_Address_Line1', 'Tally_Billing_Address_Line2', 'Billing City',
        'Tally_Billing_State', 'Billing Country', 'Billing Code',
        'Tally_Shipping_Address_Line1', 'Tally_Shipping_Address_Line2', 'Shipping City',
        'Tally_Shipping_State', 'Shipping Country', 'Shipping Code',
        'Tally_Credit_Limit', 'Opening Balance', 'Status', 'Tally_Place_of_Supply_Code', 'GST Treatment'
    ]].copy()
    st.success(f"Processed {len(df_final)} Contacts entries.")
    return df_final

def process_vendors(df):
    st.info("Processing Vendors...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Last Modified Time')

    string_cols = [
        'Contact Name', 'Company Name', 'Display Name', 'Salutation', 'First Name',
        'Last Name', 'EmailID', 'Phone', 'MobilePhone', 'Payment Terms', 'Currency Code',
        'Notes', 'Website', 'Status', 'Location Name', 'Payment Terms Label',
        'Source of Supply', 'Skype Identity', 'Department', 'Designation', 'Facebook', 'Twitter',
        'GST Treatment', 'GST Identification Number (GSTIN)', 'MSME/Udyam No', 'MSME/Udyam Type',
        'TDS Name', 'TDS Section', 'Price List', 'Contact Address ID', 'Billing Attention',
        'Billing Address', 'Billing Street2', 'Billing City', 'Billing State', 'Billing Country',
        'Billing Code', 'Billing Phone', 'Billing Fax', 'Shipping Attention', 'Shipping Address',
        'Shipping Street2', 'Shipping City', 'Shipping State', 'Shipping Country',
        'Shipping Code', 'Shipping Phone', 'Shipping Fax', 'Source', 'Owner Name', 'Primary Contact ID',
        'Beneficiary Name', 'Vendor Bank Account Number', 'Vendor Bank Name', 'Vendor Bank Code'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    numeric_cols = ['Opening Balance', 'TDS Percentage', 'Exchange Rate']
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    df_cleaned['Tally_Billing_Address_Line1'] = df_cleaned['Billing Address'].fillna('')
    df_cleaned['Tally_Billing_Address_Line2'] = df_cleaned['Billing Street2'].fillna('')
    df_cleaned['Tally_Shipping_Address_Line1'] = df_cleaned['Shipping Address'].fillna('')
    df_cleaned['Tally_Shipping_Address_Line2'] = df_cleaned['Shipping Street2'].fillna('')
    df_cleaned['Tally_Billing_State'] = df_cleaned['Billing State']
    df_cleaned['Tally_Shipping_State'] = df_cleaned['Shipping State']

    df_processed = df_cleaned.rename(columns={
        'Display Name': 'Tally_Party_Name',
        'GST Identification Number (GSTIN)': 'Tally_GSTIN',
        'EmailID': 'Tally_Email',
        'Phone': 'Tally_Phone',
        'MobilePhone': 'Tally_Mobile',
        'Vendor Bank Account Number': 'Tally_Bank_Account_No',
        'Vendor Bank Name': 'Tally_Bank_Name',
        'Vendor Bank Code': 'Tally_IFSC_Code'
    })

    df_final = df_processed[[
        'Contact ID', 'Tally_Party_Name', 'Company Name', 'Tally_Email',
        'Tally_Phone', 'Tally_Mobile', 'Tally_GSTIN',
        'Tally_Billing_Address_Line1', 'Tally_Billing_Address_Line2', 'Billing City',
        'Tally_Billing_State', 'Billing Country', 'Billing Code',
        'Tally_Shipping_Address_Line1', 'Tally_Shipping_Address_Line2', 'Shipping City',
        'Tally_Shipping_State', 'Shipping Country', 'Shipping Code',
        'Opening Balance', 'Status', 'GST Treatment',
        'Tally_Bank_Account_No', 'Tally_Bank_Name', 'Tally_IFSC_Code'
    ]].copy()
    st.success(f"Processed {len(df_final)} Vendors entries.")
    return df_final


def process_invoices(df):
    st.info("Processing Invoices...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Invoice Date')
    df_cleaned = format_date_column(df_cleaned, 'Due Date')
    df_cleaned = format_date_column(df_cleaned, 'Expected Payment Date')
    df_cleaned = format_date_column(df_cleaned, 'Last Payment Date')

    numeric_cols = [
        'Exchange Rate', 'Entity Discount Percent', 'TCS Percentage', 'TDS Percentage',
        'TDS Amount', 'SubTotal', 'Total', 'Balance', 'Adjustment', 'Shipping Charge',
        'Shipping Charge Tax Amount', 'Shipping Charge Tax %', 'Quantity', 'Discount',
        'Discount Amount', 'Item Total', 'Item Price', 'CGST Rate %', 'SGST Rate %',
        'IGST Rate %', 'CESS Rate %', 'CGST', 'SGST', 'IGST', 'CESS',
        'Reverse Charge Tax Rate', 'Item TDS Percentage', 'Item TDS Amount',
        'Round Off', 'Shipping Bill Total', 'Item Tax', 'Item Tax %', 'Item Tax Amount',
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Invoice Number', 'Invoice Status', 'Customer Name', 'Place of Supply',
        'Place of Supply(With State Code)', 'GST Treatment', 'PurchaseOrder',
        'Discount Type', 'Template Name', 'TCS Tax Name', 'TDS Calculation Type',
        'TDS Name', 'TDS Section Code', 'TDS Section', 'Adjustment Description',
        'Payment Terms', 'Payment Terms Label', 'Notes', 'Terms & Conditions',
        'E-WayBill Number', 'E-WayBill Status', 'Transporter Name', 'Transporter ID',
        'Invoice Type', 'Location Name', 'Shipping Charge Tax ID', 'Shipping Charge Tax Name',
        'Shipping Charge Tax Type', 'Shipping Charge Tax Exemption Code', 'Shipping Charge SAC Code',
        'Item Name', 'Item Desc', 'Usage unit', 'Product ID', 'Brand', 'Sales Order Number',
        'subscription_id', 'Expense Reference ID', 'Recurrence Name',
        'Billing Attention', 'Billing Address', 'Billing Street2', 'Billing City',
        'Billing State', 'Billing Country', 'Billing Code', 'Billing Phone', 'Billing Fax',
        'Shipping Attention', 'Shipping Address', 'Shipping Street2', 'Shipping City',
        'Shipping State', 'Shipping Country', 'Shipping Code', 'Shipping Fax',
        'Shipping Phone Number', 'Supplier Org Name', 'Supplier GST Registration Number',
        'Supplier Street Address', 'Supplier City', 'Supplier State', 'Supplier Country',
        'Supplier ZipCode', 'Supplier Phone', 'Supplier E-Mail', 'Reverse Charge Tax Name',
        'Reverse Charge Tax Type', 'Item TDS Name', 'Item TDS Section Code', 'Item TDS Section',
        'Nature Of Collection', 'SKU', 'Project ID', 'Project Name', 'HSN/SAC',
        'Sales person', 'Subject', 'Primary Contact EmailID', 'Primary Contact Mobile',
        'Primary Contact Phone', 'Estimate Number', 'Item Type', 'Custom Charges',
        'Shipping Bill#', 'PortCode', 'Reference Invoice#', 'Reference Invoice Type',
        'GST Registration Number(Reference Invoice)', 'Reason for issuing Debit Note',
        'E-Commerce Operator Name', 'E-Commerce Operator GSTIN', 'Account',
        'Account Code', 'Line Item Location Name', 'Supply Type', 'Tax ID',
        'Item Tax Type', 'Item Tax Exemption Reason', 'Kit Combo Item Name', 'CF.Brand Name'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Sales_Ledger_Name'] = df_cleaned['Account'].fillna('Sales Account')
    df_cleaned['Tally_Output_CGST_Ledger'] = 'Output CGST'
    df_cleaned['Tally_Output_SGST_Ledger'] = 'Output SGST'
    df_cleaned['Tally_Output_IGST_Ledger'] = 'Output IGST'
    df_cleaned['Tally_Round_Off_Ledger'] = 'Round Off'

    df_cleaned['Customer ID'] = df_cleaned['Customer ID'].fillna('').astype(str)

    st.success(f"Processed {len(df_cleaned)} Invoices entries (including line items).")
    return df_cleaned

def process_customer_payments(df):
    st.info("Processing Customer Payments...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Date')
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Invoice Date')
    df_cleaned = format_date_column(df_cleaned, 'Invoice Payment Applied Date')

    numeric_cols = [
        'Amount', 'Unused Amount', 'Bank Charges', 'Exchange Rate',
        'Tax Percentage', 'Amount Applied to Invoice', 'Withholding Tax Amount'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Payment Number', 'Mode', 'Description', 'Currency Code', 'Branch ID',
        'Payment Number Prefix', 'Payment Number Suffix', 'Customer Name',
        'Place of Supply', 'Place of Supply(With State Code)', 'GST Treatment',
        'GST Identification Number (GSTIN)', 'Description of Supply', 'Tax Name',
        'Tax Type', 'Payment Type', 'Location Name', 'Deposit To',
        'Deposit To Account Code', 'Tax Account', 'Invoice Number'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Deposit_Ledger'] = df_cleaned['Deposit To'].apply(
        lambda x: x if x else 'Cash-in-Hand'
    )
    df_cleaned['CustomerID'] = df_cleaned['CustomerID'].fillna('').astype(str)

    st.success(f"Processed {len(df_cleaned)} Customer Payments entries.")
    return df_cleaned

def process_vendor_payments(df):
    st.info("Processing Vendor Payments...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Date')
    df_cleaned = format_date_column(df_cleaned, 'Bill Date')
    df_cleaned = format_date_column(df_cleaned, 'Bill Payment Applied Date')

    numeric_cols = [
        'Amount', 'Unused Amount', 'TDSAmount', 'Exchange Rate', 'ReverseCharge Tax Percentage',
        'ReverseCharge Tax Amount', 'TDS Percentage', 'Bill Amount', 'Withholding Tax Amount',
        'Withholding Tax Amount (BCY)'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Payment Number', 'Payment Number Prefix', 'Payment Number Suffix',
        'Mode', 'Description', 'Reference Number', 'Currency Code', 'Branch ID',
        'Payment Status', 'Payment Type', 'Location Name', 'Vendor Name',
        'Debit A/c no', 'Vendor Bank Account Number', 'Vendor Bank Name',
        'Vendor Bank Code', 'Source of Supply', 'Destination of Supply',
        'GST Treatment', 'GST Identification Number (GSTIN)', 'EmailID',
        'Description of Supply', 'Paid Through', 'Paid Through Account Code',
        'Tax Account', 'ReverseCharge Tax Type', 'ReverseCharge Tax Name',
        'TDS Name', 'TDS Section Code', 'TDS Section', 'TDS Account Name',
        'Bank Reference Number', 'PIPayment ID', 'Bill Number'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Paid_Through_Ledger'] = df_cleaned['Paid Through'].apply(
        lambda x: x if x else 'Cash-in-Hand'
    )
    st.success(f"Processed {len(df_cleaned)} Vendor Payments entries.")
    return df_cleaned

def process_credit_notes(df):
    st.info("Processing Credit Notes...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Credit Note Date')
    df_cleaned = format_date_column(df_cleaned, 'Associated Invoice Date')

    numeric_cols = [
        'Exchange Rate', 'Total', 'Balance', 'Entity Discount Percent',
        'Shipping Charge', 'Shipping Charge Tax Amount', 'Shipping Charge Tax %',
        'Adjustment', 'TCS Amount', 'TDS Amount', 'TDS Percentage',
        'Discount', 'Discount Amount', 'Quantity', 'Item Tax Amount', 'Item Total',
        'CGST Rate %', 'SGST Rate %', 'IGST Rate %', 'CESS Rate %',
        'CGST(FCY)', 'SGST(FCY)', 'IGST(FCY)', 'CESS(FCY)', 'CGST', 'SGST', 'IGST', 'CESS',
        'Reverse Charge Tax Rate', 'Item Tax %', 'TCS Percentage', 'Round Off',
        'Entity Discount Amount', 'Item Price'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Product ID', 'Credit Note Number', 'Credit Note Status', 'Customer Name',
        'Billing Attention', 'Billing Address', 'Billing Street 2', 'Billing City',
        'Billing State', 'Billing Country', 'Billing Code', 'Billing Phone', 'Billing Fax',
        'Shipping Attention', 'Shipping Address', 'Shipping Street 2', 'Shipping City',
        'Shipping State', 'Shipping Country', 'Shipping Phone', 'Shipping Code', 'Shipping Fax',
        'Currency Code', 'Notes', 'Terms & Conditions', 'Reference#', 'Shipping Charge Tax ID',
        'Shipping Charge Tax Name', 'Shipping Charge Tax Type', 'Shipping Charge Tax Exemption Code',
        'Shipping Charge SAC Code', 'Branch ID', 'Associated Invoice Number', 'TDS Name',
        'TDS Section Code', 'TDS Section', 'E-WayBill Number', 'E-WayBill Status',
        'Transporter Name', 'Transporter ID', 'Item Name', 'Item Desc', 'Usage unit',
        'Location Name', 'Reason', 'Project ID', 'Project Name', 'Supplier Org Name',
        'Supplier GST Registration Number', 'Supplier Street Address', 'Supplier City',
        'Supplier State', 'Supplier Country', 'Supplier ZipCode', 'Supplier Phone',
        'Supplier E-Mail', 'Supply Type', 'Tax1 ID', 'Item Tax Type', 'Reverse Charge Tax Name',
        'Reverse Charge Tax Type', 'Place of Supply(With State Code)', 'GST Treatment',
        'GST Identification Number (GSTIN)', 'TCS Tax Name', 'Nature Of Collection',
        'Sales person', 'Discount Type', 'Place of Supply', 'Adjustment Description',
        'Subject', 'Reference Invoice Type', 'Item Type', 'Template Name', 'HSN/SAC',
        'Account', 'Account Code', 'SKU', 'Item Tax Exemption Reason', 'Line Item Location Name',
        'Kit Combo Item Name'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Sales_Return_Ledger'] = df_cleaned['Account'].fillna('Sales Returns')
    df_cleaned['Tally_Output_CGST_Ledger'] = 'Output CGST'
    df_cleaned['Tally_Output_SGST_Ledger'] = 'Output SGST'
    df_cleaned['Tally_Output_IGST_Ledger'] = 'Output IGST'
    df_cleaned['Customer ID'] = df_cleaned['Customer ID'].fillna('').astype(str)

    st.success(f"Processed {len(df_cleaned)} Credit Notes entries.")
    return df_cleaned

def process_journals(df):
    st.info("Processing Journals...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Journal Date')

    numeric_cols = [
        'Exchange Rate', 'Tax Percentage', 'Tax Amount', 'Debit', 'Credit', 'Total'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Journal Number', 'Journal Number Prefix', 'Journal Number Suffix',
        'Journal Created By', 'Journal Type', 'Status', 'Journal Entity Type',
        'Reference Number', 'Notes', 'Location ID', 'Location Name', 'Item Order',
        'Tax Name', 'Tax Type', 'Project Name', 'Account', 'Account Code',
        'Contact Name', 'Currency', 'Description'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    st.success(f"Processed {len(df_cleaned)} Journal entries.")
    return df_cleaned

def process_bills(df):
    st.info("Processing Bills...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Bill Date')
    df_cleaned = format_date_column(df_cleaned, 'Due Date')
    df_cleaned = format_date_column(df_cleaned, 'Submitted Date')
    df_cleaned = format_date_column(df_cleaned, 'Approved Date')

    numeric_cols = [
        'Entity Discount Percent', 'Exchange Rate', 'SubTotal', 'Total', 'Balance',
        'TCS Amount', 'Adjustment', 'Quantity', 'Usage unit', 'Tax Amount',
        'Item Total', 'TDS Percentage', 'TCS Percentage', 'Rate', 'Discount',
        'Discount Amount', 'CGST Rate %', 'SGST Rate %', 'IGST Rate %', 'CESS Rate %',
        'CGST(FCY)', 'SGST(FCY)', 'IGST(FCY)', 'CESS(FCY)', 'CGST', 'SGST', 'IGST', 'CESS'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Vendor Name', 'Payment Terms', 'Payment Terms Label', 'Bill Number',
        'PurchaseOrder', 'Currency Code', 'Vendor Notes', 'Terms & Conditions',
        'Adjustment Description', 'Branch ID', 'Branch Name', 'Location Name',
        'Submitted By', 'Approved By', 'Bill Status', 'Created By', 'Product ID',
        'Item Name', 'Account', 'Account Code', 'Description', 'Reference Invoice Type',
        'Source of Supply', 'Destination of Supply', 'GST Treatment',
        'GST Identification Number (GSTIN)', 'TDS Calculation Type', 'TDS TaxID',
        'TDS Name', 'TDS Section Code', 'TDS Section', 'TCS Tax Name',
        'Nature Of Collection', 'SKU', 'Line Item Location Name', 'Discount Type',
        'HSN/SAC', 'Purchase Order Number', 'Tax ID', 'Tax Name', 'Tax Type',
        'Item TDS Name', 'Item TDS Section Code', 'Item TDS Section',
        'Item Exemption Code', 'Item Type', 'Reverse Charge Tax Name',
        'Reverse Charge Tax Rate', 'Reverse Charge Tax Type', 'Supply Type',
        'ITC Eligibility', 'Discount Account', 'Discount Account Code',
        'Customer Name', 'Project Name'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Purchase_Ledger_Name'] = df_cleaned['Account'].fillna('Purchase Account')
    df_cleaned['Tally_Input_CGST_Ledger'] = 'Input CGST'
    df_cleaned['Tally_Input_SGST_Ledger'] = 'Input SGST'
    df_cleaned['Tally_Input_IGST_Ledger'] = 'Input IGST'
    df_cleaned['Tally_Round_Off_Ledger'] = 'Round Off'

    st.success(f"Processed {len(df_cleaned)} Bills entries.")
    return df_cleaned

# --- XML Generation Functions (from 03_generate_tally_xml.py) ---

def generate_ledgers_xml(df_coa):
    st.info("Generating Ledgers XML...")
    if df_coa is None: return None

    envelope, tally_message = create_tally_envelope("All Masters", "ACCOUNTS")

    known_tally_primary_groups = [
        'Capital Account', 'Loans (Liability)', 'Fixed Assets', 'Investments',
        'Current Assets', 'Current Liabilities', 'Suspense A/c',
        'Sales Accounts', 'Purchase Accounts', 'Direct Incomes', 'Direct Expenses',
        'Indirect Incomes', 'Indirect Expenses', 'Bank Accounts', 'Cash-in-Hand',
        'Duties & Taxes', 'Stock-in-Hand', 'Branch / Divisions', 'Reserves & Surplus',
        'Secured Loans', 'Unsecured Loans', 'Provisions', 'Loans & Advances (Asset)'
    ]

    tally_groups_to_create = df_coa['Tally_Parent_Group'].unique().tolist()
    for group_name in sorted(tally_groups_to_create):
        if not group_name or group_name == 'Suspense A/c':
            continue

        parent_group_
