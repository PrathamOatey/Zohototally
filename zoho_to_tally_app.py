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
TALLY_COMPANY_NAME = "Pratham's" # Ensure this matches your Tally company name
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
        'Expense': 'Indirect Expenses', # Often, Zoho expenses map to indirect
        'Cost of Goods Sold': 'Direct Expenses',
        'Equity': 'Capital Account', 'Income': 'Indirect Incomes',
        'Other Income': 'Indirect Incomes', 'Liability': 'Current Liabilities',
        'Other Current Asset': 'Current Assets', 'Other Current Liability': 'Current Liabilities',
        'Account Receivable': 'Sundry Debtors', # Special handling for default Zoho types
        'Account Payable': 'Sundry Creditors',
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
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    numeric_cols = ['Credit Limit', 'Opening Balance', 'Opening Balance Exchange Rate', 'Tax Percentage']
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    df_cleaned['Tally_Billing_Address_Line1'] = df_cleaned['Billing Address'].fillna('') if 'Billing Address' in df_cleaned.columns else ''
    df_cleaned['Tally_Billing_Address_Line2'] = df_cleaned['Billing Street2'].fillna('') if 'Billing Street2' in df_cleaned.columns else ''
    df_cleaned['Tally_Shipping_Address_Line1'] = df_cleaned['Shipping Address'].fillna('') if 'Shipping Address' in df_cleaned.columns else ''
    df_cleaned['Tally_Shipping_Address_Line2'] = df_cleaned['Shipping Street2'].fillna('') if 'Shipping Street2' in df_cleaned.columns else ''
    df_cleaned['Tally_Billing_State'] = df_cleaned['Billing State'] if 'Billing State' in df_cleaned.columns else ''
    df_cleaned['Tally_Shipping_State'] = df_cleaned['Shipping State'] if 'Shipping State' in df_cleaned.columns else ''


    df_processed = df_cleaned.rename(columns={
        'Display Name': 'Tally_Party_Name',
        'GST Identification Number (GSTIN)': 'Tally_GSTIN',
        'EmailID': 'Tally_Email',
        'Phone': 'Tally_Phone',
        'MobilePhone': 'Tally_Mobile',
        'Credit Limit': 'Tally_Credit_Limit',
        'Place of Contact(With State Code)': 'Tally_Place_of_Supply_Code'
    }, errors='ignore')

    # Dynamically select columns to avoid KeyError
    final_cols_contacts = [
        'Contact ID', 'Tally_Party_Name', 'Company Name', 'Tally_Email',
        'Tally_Phone', 'Tally_Mobile', 'Tally_GSTIN',
        'Tally_Billing_Address_Line1', 'Tally_Billing_Address_Line2', 'Billing City',
        'Tally_Billing_State', 'Billing Country', 'Billing Code',
        'Tally_Shipping_Address_Line1', 'Tally_Shipping_Address_Line2', 'Shipping City',
        'Tally_Shipping_State', 'Shipping Country', 'Shipping Code',
        'Tally_Credit_Limit', 'Opening Balance', 'Status', 'Tally_Place_of_Supply_Code', 'GST Treatment'
    ]
    # Filter to only include columns that actually exist in the DataFrame
    final_cols_contacts = [col for col in final_cols_contacts if col in df_processed.columns]
    
    df_final = df_processed[final_cols_contacts].copy()
    st.success(f"Processed {len(df_final)} Contacts entries.")
    return df_final

def process_vendors(df):
    st.info("Processing Vendors...")
    if df is None: return None

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Last Modified Time')

    string_cols = [
        'Contact ID', 'Contact Name', 'Company Name', 'Display Name', 'Salutation', 'First Name',
        'Last Name', 'EmailID', 'Phone', 'MobilePhone', 'Payment Terms', 'Currency Code',
        'Notes', 'Website', 'Status', 'Location ID', 'Location Name', 'Payment Terms Label',
        'Source of Supply', 'Skype Identity', 'Department', 'Designation', 'Facebook', 'Twitter',
        'GST Treatment', 'GST Identification Number (GSTIN)', 'MSME/Udyam No', 'MSME/Udyam Type',
        'TDS Name', 'TDS Section', 'Price List', 'Contact Address ID', 'Billing Attention',
        'Billing Address', 'Billing Street2', 'Billing City', 'Billing State', 'Billing Country',
        'Billing Code', 'Billing Phone', 'Billing Fax', 'Shipping Attention', 'Shipping Address',
        'Shipping Street2', 'Shipping City', 'Shipping State', 'Shipping Country',
        'Shipping Code', 'Shipping Phone', 'Shipping Fax', 'Source', 'Last Sync Time', 'Owner Name', 'Primary Contact ID',
        'Beneficiary Name', 'Vendor Bank Account Number', 'Vendor Bank Name', 'Vendor Bank Code'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    numeric_cols = ['Opening Balance', 'TDS Percentage', 'Exchange Rate']
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    df_cleaned['Tally_Billing_Address_Line1'] = df_cleaned['Billing Address'].fillna('') if 'Billing Address' in df_cleaned.columns else ''
    df_cleaned['Tally_Billing_Address_Line2'] = df_cleaned['Billing Street2'].fillna('') if 'Billing Street2' in df_cleaned.columns else ''
    df_cleaned['Tally_Shipping_Address_Line1'] = df_cleaned['Shipping Address'].fillna('') if 'Shipping Address' in df_cleaned.columns else ''
    df_cleaned['Tally_Shipping_Address_Line2'] = df_cleaned['Shipping Street2'].fillna('') if 'Shipping Street2' in df_cleaned.columns else ''
    df_cleaned['Tally_Billing_State'] = df_cleaned['Billing State'] if 'Billing State' in df_cleaned.columns else ''
    df_cleaned['Tally_Shipping_State'] = df_cleaned['Shipping State'] if 'Shipping State' in df_cleaned.columns else ''

    df_processed = df_cleaned.rename(columns={
        'Display Name': 'Tally_Party_Name',
        'GST Identification Number (GSTIN)': 'Tally_GSTIN',
        'EmailID': 'Tally_Email',
        'Phone': 'Tally_Phone',
        'MobilePhone': 'Tally_Mobile',
        'Vendor Bank Account Number': 'Tally_Bank_Account_No',
        'Vendor Bank Name': 'Tally_Bank_Name',
        'Vendor Bank Code': 'Tally_IFSC_Code'
    }, errors='ignore')

    final_cols_vendors = [
        'Contact ID', 'Tally_Party_Name', 'Company Name', 'Tally_Email',
        'Tally_Phone', 'Tally_Mobile', 'Tally_GSTIN',
        'Tally_Billing_Address_Line1', 'Tally_Billing_Address_Line2', 'Billing City',
        'Tally_Billing_State', 'Billing Country', 'Billing Code',
        'Tally_Shipping_Address_Line1', 'Tally_Shipping_Address_Line2', 'Shipping City',
        'Tally_Shipping_State', 'Shipping Country', 'Shipping Code',
        'Opening Balance', 'Status', 'GST Treatment',
        'Tally_Bank_Account_No', 'Tally_Bank_Name', 'Tally_IFSC_Code'
    ]
    final_cols_vendors = [col for col in final_cols_vendors if col in df_processed.columns]

    df_final = df_processed[final_cols_vendors].copy()
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
        'Reverse Charge Tax Name', 'Reverse Charge Tax Rate', 'Reverse Charge Tax Type',
        'Item TDS Percentage', 'Item TDS Amount',
        'Round Off', 'Shipping Bill Total', 'Item Tax', 'Item Tax %', 'Item Tax Amount',
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    string_cols = [
        'Invoice Date', 'Invoice ID', 'Invoice Number', 'Invoice Status', 'Customer ID', 'Customer Name',
        'Place of Supply', 'Place of Supply(With State Code)', 'GST Treatment', 'Is Inclusive Tax', 'Due Date',
        'PurchaseOrder', 'Currency Code', 'Exchange Rate', 'Discount Type', 'Is Discount Before Tax',
        'Template Name', 'Entity Discount Percent', 'TCS Tax Name', 'TCS Percentage',
        'TDS Calculation Type', 'TDS Name', 'TDS Percentage', 'TDS Section Code', 'TDS Section', 'TDS Amount',
        'SubTotal', 'Total', 'Balance', 'Adjustment', 'Adjustment Description', 'Expected Payment Date',
        'Last Payment Date', 'Payment Terms', 'Payment Terms Label', 'Notes', 'Terms & Conditions',
        'E-WayBill Number', 'E-WayBill Generated Time', 'E-WayBill Status', 'E-WayBill Cancelled Time', 'E-WayBill Expired Time',
        'Transporter Name', 'Transporter ID', 'TCS Amount', 'Invoice Type', 'Entity Discount Amount',
        'Location ID', 'Location Name', 'Shipping Charge', 'Shipping Charge Tax ID', 'Shipping Charge Tax Amount',
        'Shipping Charge Tax Name', 'Shipping Charge Tax %', 'Shipping Charge Tax Type',
        'Shipping Charge Tax Exemption Code', 'Shipping Charge SAC Code', 'Item Name', 'Item Desc', 'Quantity',
        'Discount', 'Discount Amount', 'Item Total', 'Usage unit', 'Item Price', 'Product ID', 'Brand',
        'Sales Order Number', 'subscription_id', 'Expense Reference ID', 'Recurrence Name',
        'PayPal', 'Authorize.Net', 'Google Checkout', 'Payflow Pro', 'Stripe', 'Paytm', '2Checkout',
        'Braintree', 'Forte', 'WorldPay', 'Payments Pro', 'Square', 'WePay', 'Razorpay',
        'ICICI EazyPay', 'GoCardless', 'Partial Payments', # Payment gateway fields
        'Billing Attention', 'Billing Address', 'Billing Street2', 'Billing City',
        'Billing State', 'Billing Country', 'Billing Code', 'Billing Phone', 'Billing Fax',
        'Shipping Attention', 'Shipping Address', 'Shipping Street2', 'Shipping City',
        'Shipping State', 'Shipping Country', 'Shipping Code', 'Shipping Fax',
        'Shipping Phone Number', 'Supplier Org Name', 'Supplier GST Registration Number',
        'Supplier Street Address', 'Supplier City', 'Supplier State', 'Supplier Country',
        'Supplier ZipCode', 'Supplier Phone', 'Supplier E-Mail',
        'Reverse Charge Tax Name', 'Reverse Charge Tax Type', 'Item TDS Name',
        'Item TDS Section Code', 'Item TDS Section',
        'GST Identification Number (GSTIN)', 'Nature Of Collection', 'SKU', 'Project ID', 'Project Name', 'HSN/SAC',
        'Round Off', 'Sales person', 'Subject', 'Primary Contact EmailID', 'Primary Contact Mobile',
        'Primary Contact Phone', 'Estimate Number', 'Item Type', 'Custom Charges',
        'Shipping Bill#', 'Shipping Bill Date', 'Shipping Bill Total', 'PortCode', 'Reference Invoice#', 'Reference Invoice Date', 'Reference Invoice Type',
        'GST Registration Number(Reference Invoice)', 'Reason for issuing Debit Note',
        'E-Commerce Operator Name', 'E-Commerce Operator GSTIN', 'Account',
        'Account Code', 'Line Item Location Name', 'Supply Type', 'Tax ID',
        'Item Tax', 'Item Tax %', 'Item Tax Amount', 'Item Tax Type', 'Item Tax Exemption Reason', 'Kit Combo Item Name', 'CF.Brand Name'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    # Simplified to a fixed Sales Account as per standard Tally practice, and relying on mandatory ledgers
    df_cleaned['Tally_Sales_Ledger_Name'] = 'Sales Account'
    df_cleaned['Tally_Output_CGST_Ledger'] = 'Output CGST'
    df_cleaned['Tally_Output_SGST_Ledger'] = 'Output SGST'
    df_cleaned['Tally_Output_IGST_Ledger'] = 'Output IGST'
    df_cleaned['Tally_Round_Off_Ledger'] = 'Round Off'

    if 'Customer ID' in df_cleaned.columns:
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
        'Payment Number', 'CustomerPayment ID', 'Mode', 'CustomerID', 'Description', 'Currency Code', 'Branch ID',
        'Payment Number Prefix', 'Payment Number Suffix', 'Customer Name',
        'Place of Supply', 'Place of Supply(With State Code)', 'GST Treatment',
        'GST Identification Number (GSTIN)', 'Description of Supply', 'Tax Name',
        'Tax Type', 'Payment Type', 'Location Name', 'Deposit To',
        'Deposit To Account Code', 'Tax Account', 'InvoicePayment ID', 'Invoice Number'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Deposit_Ledger'] = df_cleaned['Deposit To'].apply(
        lambda x: x if x else 'Cash-in-Hand'
    ) if 'Deposit To' in df_cleaned.columns else 'Cash-in-Hand'
    
    if 'CustomerID' in df_cleaned.columns:
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
        'Payment Number', 'Payment Number Prefix', 'Payment Number Suffix', 'VendorPayment ID',
        'Mode', 'Description', 'Reference Number', 'Currency Code', 'Branch ID',
        'Payment Status', 'Payment Type', 'Location Name', 'Vendor Name',
        'Debit A/c no', 'Vendor Bank Account Number', 'Vendor Bank Name',
        'Vendor Bank Code', 'Source of Supply', 'Destination of Supply',
        'GST Treatment', 'GST Identification Number (GSTIN)', 'EmailID',
        'Description of Supply', 'Paid Through', 'Paid Through Account Code',
        'Tax Account', 'ReverseCharge Tax Type', 'ReverseCharge Tax Name',
        'TDS Name', 'TDS Section Code', 'TDS Section', 'TDS Account Name',
        'Bank Reference Number', 'PIPayment ID', 'Bill Number', 'Withholding Tax Amount (BCY)'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    df_cleaned['Tally_Paid_Through_Ledger'] = df_cleaned['Paid Through'].apply(
        lambda x: x if x else 'Cash-in-Hand'
    ) if 'Paid Through' in df_cleaned.columns else 'Cash-in-Hand'
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
        'Product ID', 'CreditNotes ID', 'Credit Note Number', 'Credit Note Status', 'Customer Name',
        'Billing Attention', 'Billing Address', 'Billing Street 2', 'Billing City',
        'Billing State', 'Billing Country', 'Billing Code', 'Billing Phone', 'Billing Fax',
        'Shipping Attention', 'Shipping Address', 'Shipping Street 2', 'Shipping City',
        'Shipping State', 'Shipping Country', 'Shipping Phone', 'Shipping Code', 'Shipping Fax',
        'Customer ID', 'Currency Code', 'Notes', 'Terms & Conditions', 'Reference#', 'Shipping Charge Tax ID',
        'Shipping Charge Tax Name', 'Shipping Charge Tax Type', 'Shipping Charge Tax Exemption Code',
        'Shipping Charge SAC Code', 'Branch ID', 'Associated Invoice Number', 'TDS Name',
        'TDS Section Code', 'TDS Section', 'E-WayBill Number', 'E-WayBill Status',
        'Transporter Name', 'Transporter ID', 'Is Discount Before Tax', 'Item Name', 'Item Desc', 'Usage unit',
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

    # Simplified to a fixed Sales Returns Account, relying on mandatory ledgers
    df_cleaned['Tally_Sales_Return_Ledger'] = 'Sales Returns'
    df_cleaned['Tally_Output_CGST_Ledger'] = 'Output CGST'
    df_cleaned['Tally_Output_SGST_Ledger'] = 'Output SGST'
    df_cleaned['Tally_Output_IGST_Ledger'] = 'Output IGST'
    
    if 'Customer ID' in df_cleaned.columns:
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
        'Reference Number', 'Notes', 'Is Inclusive Tax', 'Location ID', 'Location Name', 'Item Order',
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
        'Bill Date', 'Due Date', 'Bill ID', 'Vendor Name', 'Entity Discount Percent',
        'Payment Terms', 'Payment Terms Label', 'Bill Number', 'PurchaseOrder',
        'Currency Code', 'Exchange Rate', 'SubTotal', 'Total', 'Balance', 'TCS Amount',
        'Vendor Notes', 'Terms & Conditions', 'Adjustment', 'Adjustment Description',
        'Branch ID', 'Branch Name', 'Location Name', 'Is Inclusive Tax', 'Submitted By',
        'Approved By', 'Submitted Date', 'Approved Date', 'Bill Status', 'Created By',
        'Product ID', 'Item Name', 'Account', 'Account Code', 'Description', 'Quantity',
        'Usage unit', 'Tax Amount', 'Item Total', 'Is Billable', 'Reference Invoice Type',
        'Source of Supply', 'Destination of Supply', 'GST Treatment',
        'GST Identification Number (GSTIN)', 'TDS Calculation Type', 'TDS TaxID',
        'TDS Name', 'TDS Percentage', 'TDS Section Code', 'TDS Section', 'TDS Amount',
        'TCS Tax Name', 'TCS Percentage', 'Nature Of Collection', 'SKU',
        'Line Item Location Name', 'Rate', 'Discount Type', 'Is Discount Before Tax',
        'Discount', 'Discount Amount', 'HSN/SAC', 'Purchase Order Number', 'Tax ID',
        'Tax Name', 'Tax Percentage', 'Tax Type', 'Item TDS Name', 'Item TDS Percentage',
        'Item TDS Amount', 'Item TDS Section Code', 'Item TDS Section',
        'Item Exemption Code', 'Item Type', 'Reverse Charge Tax Name',
        'Reverse Charge Tax Rate', 'Reverse Charge Tax Type', 'Supply Type',
        'ITC Eligibility', 'Entity Discount Amount', 'Discount Account',
        'Discount Account Code', 'Is Landed Cost', 'Customer Name', 'Project Name'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    # Simplified to a fixed Purchase Account as per standard Tally practice, and relying on mandatory ledgers
    df_cleaned['Tally_Purchase_Ledger_Name'] = 'Purchase Account'
    df_cleaned['Tally_Input_CGST_Ledger'] = 'Input CGST'
    df_cleaned['Tally_Input_SGST_Ledger'] = 'Input SGST'
    df_cleaned['Tally_Input_IGST_Ledger'] = 'Input IGST'
    df_cleaned['Tally_Round_Off_Ledger'] = 'Round Off'

    st.success(f"Processed {len(df_cleaned)} Bills entries.")
    return df_cleaned

# --- XML Generation Functions ---

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

        parent_group_for_new_group = "Primary" if group_name not in known_tally_primary_groups else ""

        group_xml = etree.SubElement(tally_message, "GROUP", NAME=safe_str(group_name), ACTION="CREATE")
        etree.SubElement(group_xml, "NAME").text = safe_str(group_name)
        if parent_group_for_new_group:
            etree.SubElement(group_xml, "PARENT").text = parent_group_for_new_group
        etree.SubElement(group_xml, "ISADDABLE").text = "Yes"
        etree.SubElement(group_xml, "LANGUAGENAME.LIST").append(
            etree.fromstring(f"<NAME.LIST><NAME>{safe_str(group_name)}</NAME></NAME.LIST>")
        )

    # Define mandatory ledgers that should always exist in Tally,
    # mapping to a sensible Tally Parent Group.
    # THESE NAMES MUST EXACTLY MATCH WHAT YOUR TALLY VOUCHERS WILL USE.
    mandatory_tally_ledgers_data = [
        {'Tally_Ledger_Name': 'Sales Account', 'Tally_Parent_Group': 'Sales Accounts', 'Account Type': 'Income', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Sales Returns', 'Tally_Parent_Group': 'Sales Accounts', 'Account Type': 'Income', 'Opening Balance': 0.0}, # For Credit Notes
        {'Tally_Ledger_Name': 'Purchase Account', 'Tally_Parent_Group': 'Purchase Accounts', 'Account Type': 'Expense', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Round Off', 'Tally_Parent_Group': 'Indirect Expenses', 'Account Type': 'Expense', 'Opening Balance': 0.0}, # Can be Indirect Incomes/Expenses
        {'Tally_Ledger_Name': 'Output CGST', 'Tally_Parent_Group': 'Duties & Taxes', 'Account Type': 'Duties & Taxes', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Output SGST', 'Tally_Parent_Group': 'Duties & Taxes', 'Account Type': 'Duties & Taxes', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Output IGST', 'Tally_Parent_Group': 'Duties & Taxes', 'Account Type': 'Duties & Taxes', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Input CGST', 'Tally_Parent_Group': 'Duties & Taxes', 'Account Type': 'Duties & Taxes', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Input SGST', 'Tally_Parent_Group': 'Duties & Taxes', 'Account Type': 'Duties & Taxes', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Input IGST', 'Tally_Parent_Group': 'Duties & Taxes', 'Account Type': 'Duties & Taxes', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Cash-in-Hand', 'Tally_Parent_Group': 'Cash-in-Hand', 'Account Type': 'Cash', 'Opening Balance': 0.0},
        {'Tally_Ledger_Name': 'Transportation Expense', 'Tally_Parent_Group': 'Indirect Expenses', 'Account Type': 'Expense', 'Opening Balance': 0.0}, # From Journal error
        # Add other common ledgers as needed for your specific Tally setup if they are not in your Zoho COA
        # Example: {'Tally_Ledger_Name': 'Bank Account', 'Tally_Parent_Group': 'Bank Accounts', 'Account Type': 'Bank', 'Opening Balance': 0.0},
    ]

    # Convert mandatory ledgers to a DataFrame
    df_mandatory_ledgers = pd.DataFrame(mandatory_tally_ledgers_data)
    # Ensure mandatory ledgers have all columns expected by generate_ledgers_xml loop
    for col in ['Account ID', 'Tally_Account_Code', 'Tally_Description', 'Tally_Status', 'Currency', 'Parent Account']:
        if col not in df_mandatory_ledgers.columns:
            df_mandatory_ledgers[col] = pd.NA # Or other suitable default like ''

    # Combine df_coa with mandatory ledgers, creating unique ledgers.
    # Prioritize Zoho COA entries if names conflict (keep='first' ensures df_coa entry wins)
    combined_df_coa = pd.concat([df_coa, df_mandatory_ledgers]).drop_duplicates(subset=['Tally_Ledger_Name'], keep='first')
    
    # Process Ledgers from the combined DataFrame
    for index, row in combined_df_coa.iterrows():
        ledger_name = safe_str(row['Tally_Ledger_Name'])
        if not ledger_name:
            st.warning(f"Skipping ledger due to empty name in Chart of Accounts: Row {index+2}")
            continue

        parent_group = safe_str(row['Tally_Parent_Group'])
        if not parent_group:
            st.warning(f"Ledger '{ledger_name}' has no mapped parent group. Assigning to 'Suspense A/c'.")
            parent_group = 'Suspense A/c'

        ledger_xml = etree.SubElement(tally_message, "LEDGER", NAME=ledger_name, ACTION="CREATE")
        etree.SubElement(ledger_xml, "NAME").text = ledger_name
        etree.SubElement(ledger_xml, "PARENT").text = parent_group
        
        if 'Opening Balance' in row.index: # Check in row.index because it might be a synthetic row from mandatory_tally_ledgers_data
            etree.SubElement(ledger_xml, "OPENINGBALANCE").text = format_tally_amount(row.get('Opening Balance', 0.0))
        else:
            etree.SubElement(ledger_xml, "OPENINGBALANCE").text = "0.00" 
            
        etree.SubElement(ledger_xml, "CURRENCYID").text = BASE_CURRENCY_NAME

        # Use .get() for Account Type as well, as it might be from mandatory_tally_ledgers_data
        if safe_str(row.get('Account Type')) == 'Bank':
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "No"
            etree.SubElement(ledger_xml, "ISCASHLEDGER").text = "No"
            etree.SubElement(ledger_xml, "ISBANKLEDGER").text = "Yes"
        elif safe_str(row.get('Account Type')) == 'Cash':
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "No"
            etree.SubElement(ledger_xml, "ISCASHLEDGER").text = "Yes"
            etree.SubElement(ledger_xml, "ISBANKLEDGER").text = "No"
        elif parent_group in ['Sundry Debtors', 'Sundry Creditors']:
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "Yes"
            etree.SubElement(ledger_xml, "ISCOSTCENTRESON").text = "No"

        description = safe_str(row.get('Tally_Description'))
        if description:
            etree.SubElement(ledger_xml, "DESCRIPTION").text = description

        etree.SubElement(ledger_xml, "LANGUAGENAME.LIST").append(
            etree.fromstring(f"<NAME.LIST><NAME>{safe_str(ledger_name)}</NAME></NAME.LIST>")
        )
    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Ledgers XML.")
    return xml_string

def generate_contacts_vendors_xml(df_contacts, df_vendors):
    st.info("Generating Contacts and Vendors XML...")
    envelope, tally_message = create_tally_envelope("All Masters", "ACCOUNTS")

    def add_address_details_to_party_xml(parent_element, row, is_shipping=False):
        prefix = "Shipping" if is_shipping else "Billing"
        
        # Fetch values using .get() with default empty string
        address1 = safe_str(row.get(f'Tally_{prefix}_Address_Line1', ''))
        address2 = safe_str(row.get(f'Tally_{prefix}_Address_Line2', ''))
        city = safe_str(row.get(f'{prefix} City', ''))
        state = safe_str(row.get(f'Tally_{prefix}_State', ''))
        country = safe_str(row.get(f'{prefix} Country', '')) or DEFAULT_COUNTRY
        pincode = safe_str(row.get(f'{prefix} Code', ''))

        address_list = etree.SubElement(parent_element, "ADDRESS.LIST") # Always create the list element
        
        # Only add address lines if they have content
        if address1:
            etree.SubElement(address_list, "ADDRESS").text = address1
        if address2:
            etree.SubElement(address_list, "ADDRESS").text = address2
        
        # Only add city/state/country/pincode if they have values to avoid empty tags or issues
        if city:
            etree.SubElement(parent_element, "CITY").text = city
        if state:
            etree.SubElement(parent_element, "STATENAME").text = state
        if country:
            etree.SubElement(parent_element, "COUNTRYNAME").text = country
        if pincode:
            etree.SubElement(parent_element, "PINCODE").text = pincode


    if df_contacts is not None:
        for index, row in df_contacts.iterrows():
            party_name = safe_str(row.get('Tally_Party_Name', ''))
            if not party_name:
                st.warning(f"Skipping contact due to empty name: Row {index+2}")
                continue

            ledger_xml = etree.SubElement(tally_message, "LEDGER", NAME=party_name, ACTION="CREATE")
            etree.SubElement(ledger_xml, "NAME").text = party_name
            etree.SubElement(ledger_xml, "PARENT").text = "Sundry Debtors"
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "Yes"
            etree.SubElement(ledger_xml, "OPENINGBALANCE").text = format_tally_amount(row.get('Opening Balance', 0.0))

            add_address_details_to_party_xml(ledger_xml, row, is_shipping=False)

            phone = safe_str(row.get('Tally_Phone'))
            mobile = safe_str(row.get('Tally_Mobile'))
            email = safe_str(row.get('Tally_Email'))

            if phone: etree.SubElement(ledger_xml, "PHONENUMBER").text = phone
            if mobile: etree.SubElement(ledger_xml, "MOBILENUMBER").text = mobile
            if email: etree.SubElement(ledger_xml, "EMAIL").text = email

            gstin = safe_str(row.get('Tally_GSTIN'))
            gst_treatment = safe_str(row.get('GST Treatment'))
            place_of_supply_code = safe_str(row.get('Tally_Place_of_Supply_Code'))

            if gstin:
                etree.SubElement(ledger_xml, "HASGSTIN").text = "Yes"
                etree.SubElement(ledger_xml, "GSTREGISTRATIONTYPE").text = gst_treatment if gst_treatment in ['Regular', 'Consumer', 'Unregistered', 'Composition', 'SEZ'] else "Regular"
                etree.SubElement(ledger_xml, "GSTIN").text = gstin
                if place_of_supply_code:
                    etree.SubElement(ledger_xml, "PLACEOFSUPPLY").text = place_of_supply_code.split('-')[0].strip()

            etree.SubElement(ledger_xml, "LANGUAGENAME.LIST").append(
                etree.fromstring(f"<NAME.LIST><NAME>{safe_str(party_name)}</NAME></NAME.LIST>")
            )

    if df_vendors is not None:
        for index, row in df_vendors.iterrows():
            party_name = safe_str(row.get('Tally_Party_Name', ''))
            if not party_name:
                st.warning(f"Skipping vendor due to empty name: Row {index+2}")
                continue

            ledger_xml = etree.SubElement(tally_message, "LEDGER", NAME=party_name, ACTION="CREATE")
            etree.SubElement(ledger_xml, "NAME").text = party_name
            etree.SubElement(ledger_xml, "PARENT").text = "Sundry Creditors"
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "Yes"
            etree.SubElement(ledger_xml, "OPENINGBALANCE").text = format_tally_amount(row.get('Opening Balance', 0.0))

            add_address_details_to_party_xml(ledger_xml, row, is_shipping=False)

            phone = safe_str(row.get('Tally_Phone'))
            mobile = safe_str(row.get('Tally_Mobile'))
            email = safe_str(row.get('Tally_Email'))

            if phone: etree.SubElement(ledger_xml, "PHONENUMBER").text = phone
            if mobile: etree.SubElement(ledger_xml, "MOBILENUMBER").text = mobile
            if email: etree.SubElement(ledger_xml, "EMAIL").text = email

            gstin = safe_str(row.get('Tally_GSTIN'))
            gst_treatment = safe_str(row.get('GST Treatment'))

            if gstin:
                etree.SubElement(ledger_xml, "HASGSTIN").text = "Yes"
                etree.SubElement(ledger_xml, "GSTREGISTRATIONTYPE").text = gst_treatment if gst_treatment in ['Regular', 'Consumer', 'Unregistered', 'Composition', 'SEZ'] else "Regular"
                etree.SubElement(ledger_xml, "GSTIN").text = gstin

            bank_acc_no = safe_str(row.get('Tally_Bank_Account_No'))
            bank_name = safe_str(row.get('Tally_Bank_Name'))
            ifsc_code = safe_str(row.get('Tally_IFSC_Code'))
            if bank_acc_no and bank_name:
                bank_details = etree.SubElement(ledger_xml, "BANKDETAILS.LIST")
                etree.SubElement(bank_details, "BANKACCOUNTNO").text = bank_acc_no
                etree.SubElement(bank_details, "BANKNAME").text = bank_name
                if ifsc_code:
                    etree.SubElement(bank_details, "IFSCCODE").text = ifsc_code

            etree.SubElement(ledger_xml, "LANGUAGENAME.LIST").append(
                etree.fromstring(f"<NAME.LIST><NAME>{safe_str(party_name)}</NAME></NAME.LIST>")
            )

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Contacts and Vendors XML.")
    return xml_string


def generate_sales_vouchers_xml(df_invoices):
    st.info("Generating Sales Vouchers XML...")
    if df_invoices is None: return None

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")
    df_invoices['Total'] = pd.to_numeric(df_invoices['Total'], errors='coerce').fillna(0)
    grouped_invoices = df_invoices.groupby('Invoice ID')

    for invoice_id, group in grouped_invoices:
        header = group.iloc[0]
        
        total_amount = header.get('Total', 0.0)
        if pd.isna(total_amount):
            total_amount = 0.0

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(header.get('Invoice ID', '')),
                                   VCHTYPE="Sales",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header.get('Invoice Date', ''))
        etree.SubElement(voucher, "GUID").text = f"SAL-{safe_str(header.get('Invoice ID', ''))}"
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Sales"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(header.get('Invoice Number', ''))
        etree.SubElement(voucher, "PARTYLEDGERNAME").text = safe_str(header.get('Customer Name', ''))
        etree.SubElement(voucher, "BASICBUYERNAME").text = safe_str(header.get('Customer Name', ''))
        etree.SubElement(voucher, "PERSISTEDVIEW").text = "Accounting Voucher"
        place_supply_code = safe_str(header.get('Place of Supply(With State Code)', '')).split('-')[0].strip()
        if place_supply_code:
            etree.SubElement(voucher, "PLACEOFSUPPLY").text = place_supply_code

        buyer_details = etree.SubElement(voucher, "BUYERDETAILS.LIST")
        etree.SubElement(buyer_details, "CONSNAME").text = safe_str(header.get('Customer Name', ''))
        cons_address_list = etree.SubElement(buyer_details, "ADDRESS.LIST")
        
        # Check for address columns before attempting to access
        if 'Shipping Address' in header and safe_str(header.get('Shipping Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Address'))
            if 'Shipping Street2' in header and safe_str(header.get('Shipping Street2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Street2'))
        elif 'Billing Address' in header and safe_str(header.get('Billing Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Address'))
            if 'Billing Street2' in header and safe_str(header.get('Billing Street2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Street2'))
        
        etree.SubElement(buyer_details, "STATENAME").text = safe_str(header.get('Shipping State', '') or header.get('Billing State', '') or '')
        etree.SubElement(buyer_details, "COUNTRYNAME").text = safe_str(header.get('Shipping Country', '') or header.get('Billing Country', '') or DEFAULT_COUNTRY)
        
        gstin = safe_str(header.get('GST Identification Number (GSTIN)'))
        if gstin:
            etree.SubElement(buyer_details, "GSTREGISTRATIONTYPE").text = safe_str(header.get('GST Treatment', 'Regular'))
            etree.SubElement(buyer_details, "GSTIN").text = gstin
        
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header.get('Invoice Date', ''))
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Notes', ''))
        
        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Credit the Party Ledger (Customer)
        party_ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(party_ledger_entry, "LEDGERNAME").text = safe_str(header.get('Customer Name', ''))
        etree.SubElement(party_ledger_entry, "ISDEEMEDPOSITIVE").text = "No"
        etree.SubElement(party_ledger_entry, "AMOUNT").text = format_tally_amount(-total_amount)
        
        bill_allocation_list = etree.SubElement(party_ledger_entry, "BILLALLOCATIONS.LIST")
        bill_allocation = etree.SubElement(bill_allocation_list, "BILLALLOCATIONS")
        etree.SubElement(bill_allocation, "NAME").text = safe_str(header.get('Invoice Number', ''))
        etree.SubElement(bill_allocation, "BILLTYPE").text = "New Ref"
        etree.SubElement(bill_allocation, "AMOUNT").text = format_tally_amount(-total_amount)

        # Process each line item
        for idx, item_row in group.iterrows():
            item_name = safe_str(item_row.get('Item Name'))
            if not item_name and not safe_str(item_row.get('Item Desc')): # Check for actual item data
                continue

            item_total = item_row.get('Item Total', 0.0)
            item_total = float(item_total) if not pd.isna(item_total) else 0.0 # Ensure float conversion

            sales_ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            # This now refers to the mandatory 'Sales Account' created in generate_ledgers_xml
            etree.SubElement(sales_ledger_entry, "LEDGERNAME").text = 'Sales Account' # Fixed to mandatory ledger name
            etree.SubElement(sales_ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes"
            etree.SubElement(sales_ledger_entry, "AMOUNT").text = format_tally_amount(item_total)

            # Ensure GST amounts are floats before comparison
            cgst_amount = float(item_row.get('CGST', 0.0)) if not pd.isna(item_row.get('CGST')) else 0.0
            sgst_amount = float(item_row.get('SGST', 0.0)) if not pd.isna(item_row.get('SGST')) else 0.0
            igst_amount = float(item_row.get('IGST', 0.0)) if not pd.isna(item_row.get('IGST')) else 0.0

            if igst_amount > 0: # Now comparison with float is safe
                gst_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry, "LEDGERNAME").text = 'Output IGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry, "AMOUNT").text = format_tally_amount(igst_amount)
            
            if cgst_amount > 0: # Now comparison with float is safe
                gst_entry_cgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry_cgst, "LEDGERNAME").text = 'Output CGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry_cgst, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry_cgst, "AMOUNT").text = format_tally_amount(cgst_amount)
            
            if sgst_amount > 0: # Now comparison with float is safe
                gst_entry_sgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry_sgst, "LEDGERNAME").text = 'Output SGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry_sgst, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry_sgst, "AMOUNT").text = format_tally_amount(sgst_amount)

        round_off_amount = header.get('Round Off', 0.0)
        # Ensure round_off_amount is float before math.isnan
        round_off_amount = float(round_off_amount) if not pd.isna(round_off_amount) else 0.0
        
        if round_off_amount != 0.0:
            round_off_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(round_off_entry, "LEDGERNAME").text = 'Round Off' # Fixed to mandatory ledger name
            etree.SubElement(round_off_entry, "ISDEEMEDPOSITIVE").text = "Yes" if round_off_amount > 0 else "No"
            etree.SubElement(round_off_entry, "AMOUNT").text = format_tally_amount(round_off_amount)

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Sales Vouchers XML.")
    return xml_string


def generate_customer_payments_xml(df_payments):
    st.info("Generating Customer Payments (Receipt Vouchers) XML...")
    if df_payments is None: return None

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    for index, row in df_payments.iterrows():
        payment_id = safe_str(row.get('CustomerPayment ID', ''))
        if not payment_id:
            st.warning(f"Skipping customer payment due to empty ID: Row {index+2}")
            continue

        amount = row.get('Amount', 0.0)
        if pd.isna(amount): amount = 0.0

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=payment_id,
                                   VCHTYPE="Receipt",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(row.get('Date', ''))
        etree.SubElement(voucher, "GUID").text = f"RCP-{payment_id}"
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Receipt"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(row.get('Payment Number', ''))
        etree.SubElement(voucher, "NARRATION").text = safe_str(row.get('Description', 'Customer Payment'))
        etree.SubElement(voucher, "BASICBASECURRENTBAL").text = format_tally_amount(amount)
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(row.get('Date', ''))

        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        debit_bank_cash = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        # This now refers to the mandatory 'Cash-in-Hand' or the actual bank name if present and created
        etree.SubElement(debit_bank_cash, "LEDGERNAME").text = safe_str(row.get('Tally_Deposit_Ledger', 'Cash-in-Hand'))
        etree.SubElement(debit_bank_cash, "ISDEEMEDPOSITIVE").text = "Yes"
        etree.SubElement(debit_bank_cash, "AMOUNT").text = format_tally_amount(amount)

        credit_customer = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(credit_customer, "LEDGERNAME").text = safe_str(row.get('Customer Name', ''))
        etree.SubElement(credit_customer, "ISDEEMEDPOSITIVE").text = "No"
        etree.SubElement(credit_customer, "AMOUNT").text = format_tally_amount(-amount)

        invoice_number = safe_str(row.get('Invoice Number'))
        amount_applied = row.get('Amount Applied to Invoice', 0.0)
        if pd.isna(amount_applied): amount_applied = 0.0

        if invoice_number and amount_applied != 0:
            bill_allocation = etree.SubElement(credit_customer, "BILLALLOCATIONS.LIST")
            bill_details = etree.SubElement(bill_allocation, "BILLALLOCATIONS")
            etree.SubElement(bill_details, "NAME").text = invoice_number
            etree.SubElement(bill_details, "BILLTYPE").text = "Agst Ref"
            etree.SubElement(bill_details, "AMOUNT").text = format_tally_amount(-amount_applied)

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Customer Payments XML.")
    return xml_string


def generate_vendor_payments_xml(df_payments):
    st.info("Generating Vendor Payments (Payment Vouchers) XML...")
    if df_payments is None: return None

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    for index, row in df_payments.iterrows():
        payment_id = safe_str(row.get('VendorPayment ID', ''))
        if not payment_id:
            st.warning(f"Skipping vendor payment due to empty ID: Row {index+2}")
            continue

        amount = row.get('Amount', 0.0)
        if pd.isna(amount): amount = 0.0

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=payment_id,
                                   VCHTYPE="Payment",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(row.get('Date', ''))
        etree.SubElement(voucher, "GUID").text = f"PAY-{payment_id}"
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Payment"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(row.get('Payment Number', ''))
        etree.SubElement(voucher, "NARRATION").text = safe_str(row.get('Description', 'Vendor Payment'))
        etree.SubElement(voucher, "BASICBASECURRENTBAL").text = format_tally_amount(amount)
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(row.get('Date', ''))

        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        debit_vendor = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(debit_vendor, "LEDGERNAME").text = safe_str(row.get('Vendor Name', ''))
        etree.SubElement(debit_vendor, "ISDEEMEDPOSITIVE").text = "Yes"
        etree.SubElement(debit_vendor, "AMOUNT").text = format_tally_amount(amount)

        bill_number = safe_str(row.get('Bill Number'))
        bill_amount_applied = row.get('Bill Amount', 0.0)
        if pd.isna(bill_amount_applied): bill_amount_applied = 0.0

        if bill_number and bill_amount_applied != 0:
            bill_allocation = etree.SubElement(debit_vendor, "BILLALLOCATIONS.LIST")
            bill_details = etree.SubElement(bill_allocation, "BILLALLOCATIONS")
            etree.SubElement(bill_details, "NAME").text = bill_number
            etree.SubElement(bill_details, "BILLTYPE").text = "Agst Ref"
            etree.SubElement(bill_details, "AMOUNT").text = format_tally_amount(bill_amount_applied)

        credit_bank_cash = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        # This now refers to the mandatory 'Cash-in-Hand' or the actual bank name if present and created
        etree.SubElement(credit_bank_cash, "LEDGERNAME").text = safe_str(row.get('Tally_Paid_Through_Ledger', 'Cash-in-Hand'))
        etree.SubElement(credit_bank_cash, "ISDEEMEDPOSITIVE").text = "No"
        etree.SubElement(credit_bank_cash, "AMOUNT").text = format_tally_amount(-amount)

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Vendor Payments XML.")
    return xml_string


def generate_credit_notes_xml(df_credit_notes):
    st.info("Generating Credit Notes XML...")
    if df_credit_notes is None: return None

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")
    df_credit_notes['Total'] = pd.to_numeric(df_credit_notes['Total'], errors='coerce').fillna(0)
    grouped_credit_notes = df_credit_notes.groupby('CreditNotes ID')

    for credit_note_id, group in grouped_credit_notes:
        header = group.iloc[0]
        
        total_amount = header.get('Total', 0.0)
        if pd.isna(total_amount): total_amount = 0.0

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(header.get('CreditNotes ID', '')),
                                   VCHTYPE="Credit Note",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header.get('Credit Note Date', ''))
        etree.SubElement(voucher, "GUID").text = f"CRN-{safe_str(header.get('CreditNotes ID', ''))}"
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Credit Note"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(header.get('Credit Note Number', ''))
        etree.SubElement(voucher, "PARTYLEDGERNAME").text = safe_str(header.get('Customer Name', ''))
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Reason', 'Credit Note issued'))
        etree.SubElement(voucher, "BASICBUYERNAME").text = safe_str(header.get('Customer Name', ''))
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header.get('Credit Note Date', ''))
        etree.SubElement(voucher, "ISORIGINAL").text = "Yes"

        buyer_details = etree.SubElement(voucher, "BUYERDETAILS.LIST")
        etree.SubElement(buyer_details, "CONSNAME").text = safe_str(header.get('Customer Name', ''))
        cons_address_list = etree.SubElement(buyer_details, "ADDRESS.LIST")
        
        # Check for address columns before attempting to access
        if 'Shipping Address' in header and safe_str(header.get('Shipping Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Address'))
            if 'Shipping Street 2' in header and safe_str(header.get('Shipping Street 2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Street 2'))
        elif 'Billing Address' in header and safe_str(header.get('Billing Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Address'))
            if 'Billing Street 2' in header and safe_str(header.get('Billing Street 2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Street 2'))
        
        etree.SubElement(buyer_details, "STATENAME").text = safe_str(header.get('Shipping State', '') or header.get('Billing State', '') or '')
        etree.SubElement(buyer_details, "COUNTRYNAME").text = safe_str(header.get('Shipping Country', '') or header.get('Billing Country', '') or DEFAULT_COUNTRY)

        gstin = safe_str(header.get('GST Identification Number (GSTIN)'))
        if gstin:
            etree.SubElement(buyer_details, "GSTREGISTRATIONTYPE").text = safe_str(header.get('GST Treatment', 'Regular'))
            etree.SubElement(buyer_details, "GSTIN").text = gstin
        
        if safe_str(header.get('Associated Invoice Number')):
            original_invoice_details = etree.SubElement(voucher, "ORIGINALINVOICEDETAILS.LIST")
            orig_inv_item = etree.SubElement(original_invoice_details, "ORIGINALINVOICEDETAILS")
            etree.SubElement(orig_inv_item, "DATE").text = format_tally_date(header.get('Associated Invoice Date', ''))
            etree.SubElement(orig_inv_item, "REFNUM").text = safe_str(header.get('Associated Invoice Number'))


        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        for idx, item_row in group.iterrows():
            item_name = safe_str(item_row.get('Item Name'))
            if not item_name and not safe_str(item_row.get('Item Desc')):
                continue

            item_total = item_row.get('Item Total', 0.0)
            item_total = float(item_total) if not pd.isna(item_total) else 0.0

            debit_sales_return = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            # This now refers to the mandatory 'Sales Returns' created in generate_ledgers_xml
            etree.SubElement(debit_sales_return, "LEDGERNAME").text = 'Sales Returns' # Fixed to mandatory ledger name
            etree.SubElement(debit_sales_return, "ISDEEMEDPOSITIVE").text = "Yes"
            etree.SubElement(debit_sales_return, "AMOUNT").text = format_tally_amount(item_total)

            cgst_amount = float(item_row.get('CGST', 0.0)) if not pd.isna(item_row.get('CGST')) else 0.0
            sgst_amount = float(item_row.get('SGST', 0.0)) if not pd.isna(item_row.get('SGST')) else 0.0
            igst_amount = float(item_row.get('IGST', 0.0)) if not pd.isna(item_row.get('IGST')) else 0.0

            if igst_amount > 0:
                gst_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry, "LEDGERNAME").text = 'Output IGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry, "ISDEEMEDPOSITIVE").text = "No"
                etree.SubElement(gst_entry, "AMOUNT").text = format_tally_amount(-igst_amount)
            
            if cgst_amount > 0:
                gst_entry_cgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry_cgst, "LEDGERNAME").text = 'Output CGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry_cgst, "ISDEEMEDPOSITIVE").text = "No"
                etree.SubElement(gst_entry_cgst, "AMOUNT").text = format_tally_amount(-cgst_amount)
            
            if sgst_amount > 0:
                gst_entry_sgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry_sgst, "LEDGERNAME").text = 'Output SGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry_sgst, "ISDEEMEDPOSITIVE").text = "No"
                etree.SubElement(gst_entry_sgst, "AMOUNT").text = format_tally_amount(-sgst_amount)
        
        credit_customer = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(credit_customer, "LEDGERNAME").text = safe_str(header.get('Customer Name', ''))
        etree.SubElement(credit_customer, "ISDEEMEDPOSITIVE").text = "No"
        etree.SubElement(credit_customer, "AMOUNT").text = format_tally_amount(-total_amount)

        associated_invoice_number = safe_str(header.get('Associated Invoice Number'))
        if associated_invoice_number:
            bill_allocation = etree.SubElement(credit_customer, "BILLALLOCATIONS.LIST")
            bill_details = etree.SubElement(bill_allocation, "BILLALLOCATIONS")
            etree.SubElement(bill_details, "NAME").text = associated_invoice_number
            etree.SubElement(bill_details, "BILLTYPE").text = "Agst Ref"
            etree.SubElement(bill_details, "AMOUNT").text = format_tally_amount(-total_amount)

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Credit Notes XML.")
    return xml_string


def generate_journal_vouchers_xml(df_journals):
    st.info("Generating Journal Vouchers XML...")
    if df_journals is None: return None

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")
    grouped_journals = df_journals.groupby('Journal Number')

    for journal_num, group in grouped_journals:
        header = group.iloc[0]

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(journal_num),
                                   VCHTYPE="Journal",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header.get('Journal Date', ''))
        etree.SubElement(voucher, "GUID").text = f"JRN-{safe_str(journal_num)}"
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Journal"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(journal_num)
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Notes', 'Journal Entry'))
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header.get('Journal Date', ''))


        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        current_debit_total = 0.0
        current_credit_total = 0.0

        for idx, entry_row in group.iterrows():
            ledger_name = safe_str(entry_row.get('Account', ''))
            debit_amount = entry_row.get('Debit', 0.0)
            credit_amount = entry_row.get('Credit', 0.0)

            if pd.isna(debit_amount): debit_amount = 0.0
            if pd.isna(credit_amount): credit_amount = 0.0

            if debit_amount > 0:
                ledger_entry = etree.SubElement(all_
