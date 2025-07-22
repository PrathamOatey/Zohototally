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
        'Reverse Charge Tax Rate', 'Item TDS Percentage', 'Item TDS Amount',
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
        'Reverse Charge Tax Name', 'Reverse Charge Tax Rate', 'Reverse Charge Tax Type', 'Item TDS Name',
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
        if pd.isna(bill_amount_applied): amount_applied = 0.0

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
                ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(ledger_entry, "LEDGERNAME").text = ledger_name
                etree.SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(ledger_entry, "AMOUNT").text = format_tally_amount(debit_amount)
                current_debit_total += debit_amount
            elif credit_amount > 0:
                ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(ledger_entry, "LEDGERNAME").text = ledger_name
                etree.SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "No"
                etree.SubElement(ledger_entry, "AMOUNT").text = format_tally_amount(-credit_amount)
                current_credit_total += credit_amount
        
        if abs(current_debit_total - current_credit_total) > 0.01:
            st.warning(f"Journal '{journal_num}' has an imbalanced debit/credit. Debit: {current_debit_total:.2f}, Credit: {current_credit_total:.2f}. Tally might reject this voucher.")

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Journal Vouchers XML.")
    return xml_string


def generate_purchase_vouchers_xml(df_bills):
    st.info("Generating Purchase Vouchers XML...")
    if df_bills is None: return None

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")
    df_bills['Total'] = pd.to_numeric(df_bills['Total'], errors='coerce').fillna(0)
    grouped_bills = df_bills.groupby('Bill ID')

    for bill_id, group in grouped_bills:
        header = group.iloc[0]

        total_amount = header.get('Total', 0.0)
        if pd.isna(total_amount): total_amount = 0.0

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(header.get('Bill ID', '')),
                                   VCHTYPE="Purchase",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header.get('Bill Date', ''))
        etree.SubElement(voucher, "GUID").text = f"PUR-{safe_str(header.get('Bill ID', ''))}"
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Purchase"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(header.get('Bill Number', ''))
        etree.SubElement(voucher, "PARTYLEDGERNAME").text = safe_str(header.get('Vendor Name', ''))
        etree.SubElement(voucher, "BASICSELLERNAME").text = safe_str(header.get('Vendor Name', ''))
        etree.SubElement(voucher, "PERSISTEDVIEW").text = "Accounting Voucher"
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header.get('Bill Date', ''))
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Vendor Notes', ''))
        
        seller_details = etree.SubElement(voucher, "SELLERDETAILS.LIST")
        etree.SubElement(seller_details, "CONSNAME").text = safe_str(header.get('Vendor Name', ''))
        gstin = safe_str(header.get('GST Identification Number (GSTIN)'))
        if gstin:
            etree.SubElement(seller_details, "GSTREGISTRATIONTYPE").text = safe_str(header.get('GST Treatment', 'Regular'))
            etree.SubElement(seller_details, "GSTIN").text = gstin
        
        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        credit_party = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(credit_party, "LEDGERNAME").text = safe_str(header.get('Vendor Name', ''))
        etree.SubElement(credit_party, "ISDEEMEDPOSITIVE").text = "No"
        etree.SubElement(credit_party, "AMOUNT").text = format_tally_amount(-total_amount)
        
        bill_allocation_list = etree.SubElement(credit_party, "BILLALLOCATIONS.LIST")
        bill_allocation = etree.SubElement(bill_allocation_list, "BILLALLOCATIONS")
        etree.SubElement(bill_allocation, "NAME").text = safe_str(header.get('Bill Number', ''))
        etree.SubElement(bill_allocation, "BILLTYPE").text = "New Ref"
        etree.SubElement(bill_allocation, "AMOUNT").text = format_tally_amount(-total_amount)

        for idx, item_row in group.iterrows():
            item_name = safe_str(item_row.get('Item Name'))
            if not item_name and not safe_str(item_row.get('Description')):
                continue
            
            item_total = item_row.get('Item Total', 0.0)
            item_total = float(item_total) if not pd.isna(item_total) else 0.0

            debit_purchase = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            # This now refers to the mandatory 'Purchase Account' created in generate_ledgers_xml
            etree.SubElement(debit_purchase, "LEDGERNAME").text = 'Purchase Account' # Fixed to mandatory ledger name
            etree.SubElement(debit_purchase, "ISDEEMEDPOSITIVE").text = "Yes"
            etree.SubElement(debit_purchase, "AMOUNT").text = format_tally_amount(item_total)

            cgst_amount = float(item_row.get('CGST', 0.0)) if not pd.isna(item_row.get('CGST')) else 0.0
            sgst_amount = float(item_row.get('SGST', 0.0)) if not pd.isna(item_row.get('SGST')) else 0.0
            igst_amount = float(item_row.get('IGST', 0.0)) if not pd.isna(item_row.get('IGST')) else 0.0

            if igst_amount > 0:
                gst_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry, "LEDGERNAME").text = 'Input IGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry, "AMOUNT").text = format_tally_amount(igst_amount)
            
            if cgst_amount > 0:
                gst_entry_cgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry_cgst, "LEDGERNAME").text = 'Input CGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry_cgst, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry_cgst, "AMOUNT").text = format_tally_amount(cgst_amount)
            
            if sgst_amount > 0:
                gst_entry_sgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry_sgst, "LEDGERNAME").text = 'Input SGST' # Fixed to mandatory ledger name
                etree.SubElement(gst_entry_sgst, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry_sgst, "AMOUNT").text = format_tally_amount(sgst_amount)

        adjustment_amount = header.get('Adjustment', 0.0)
        # Ensure adjustment_amount is float before math.isnan
        adjustment_amount = float(adjustment_amount) if not pd.isna(adjustment_amount) else 0.0
        
        if adjustment_amount != 0.0:
            round_off_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(round_off_entry, "LEDGERNAME").text = 'Round Off' # Fixed to mandatory ledger name
            etree.SubElement(round_off_entry, "ISDEEMEDPOSITIVE").text = "Yes" if adjustment_amount > 0 else "No"
            etree.SubElement(round_off_entry, "AMOUNT").text = format_tally_amount(adjustment_amount)

    xml_string = etree.tostring(envelope, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True).decode('utf-8')
    st.success("Generated Purchase Vouchers XML.")
    return xml_string


# --- Streamlit App Layout ---
st.set_page_config(layout="wide", page_title="Zoho to Tally Migration Tool")

st.title("🚀 Zoho to Tally Migration Tool")
st.markdown("Upload your Zoho backup ZIP file, and this tool will generate Tally-compatible XML files for financial data.")

st.header("1. Upload Zoho Backup ZIP")
uploaded_file = st.file_uploader("Choose a Zoho backup ZIP file", type="zip")

if uploaded_file is not None:
    st.success(f"File '{uploaded_file.name}' uploaded successfully.")

    with tempfile.TemporaryDirectory() as temp_dir:
        extract_path = os.path.join(temp_dir, "zoho_extracted")
        os.makedirs(extract_path)

        zip_temp_path = os.path.join(temp_dir, uploaded_file.name)
        try:
            with open(zip_temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            st.info("Extracting ZIP file...")
            with zipfile.ZipFile(zip_temp_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            st.info(f"Extracted Zoho ZIP to a temporary directory: {extract_path}")

            raw_dfs = {}
            missing_files = []
            st.info("Loading raw CSV files...")
            for zoho_csv_name in ZOHO_CSVS:
                csv_path = os.path.join(extract_path, zoho_csv_name)
                if os.path.exists(csv_path):
                    try:
                        raw_dfs[zoho_csv_name] = pd.read_csv(csv_path, encoding='utf-8', on_bad_lines='skip', low_memory=False)
                        st.write(f"Loaded {zoho_csv_name} (raw). Rows: {len(raw_dfs[zoho_csv_name])}")
                    except Exception as e:
                        st.error(f"Error loading raw {zoho_csv_name}: {e}")
                        st.exception(e) # Display full traceback for loading errors
                        missing_files.append(zoho_csv_name) # Treat loading error as missing
                else:
                    missing_files.append(zoho_csv_name)
            
            if missing_files:
                st.warning(f"⚠️ Warning: The following crucial Zoho CSV files were not found or could not be loaded from the ZIP: {', '.join(missing_files)}. Generated XMLs might be incomplete or inaccurate.")
            else:
                st.success("✅ All expected Zoho CSV files found and loaded.")

            st.header("2. Processing and Mapping Data")
            processed_dfs = {}
            
            # --- Call processing functions with robust error handling ---
            try:
                processed_dfs['coa'] = process_chart_of_accounts(raw_dfs.get('Chart_of_Accounts.csv'))
            except Exception as e:
                st.error("Error during Chart of Accounts processing:")
                st.exception(e)

            try:
                processed_dfs['contacts'] = process_contacts(raw_dfs.get('Contacts.csv'))
            except Exception as e:
                st.error("Error during Contacts processing:")
                st.exception(e)

            try:
                processed_dfs['vendors'] = process_vendors(raw_dfs.get('Vendors.csv'))
            except Exception as e:
                st.error("Error during Vendors processing:")
                st.exception(e)

            try:
                processed_dfs['invoices'] = process_invoices(raw_dfs.get('Invoice.csv'))
            except Exception as e:
                st.error("Error during Invoices processing:")
                st.exception(e)

            try:
                processed_dfs['customer_payments'] = process_customer_payments(raw_dfs.get('Customer_Payment.csv'))
            except Exception as e:
                st.error("Error during Customer Payments processing:")
                st.exception(e)

            try:
                processed_dfs['vendor_payments'] = process_vendor_payments(raw_dfs.get('Vendor_Payment.csv'))
            except Exception as e:
                st.error("Error during Vendor Payments processing:")
                st.exception(e)

            try:
                processed_dfs['credit_notes'] = process_credit_notes(raw_dfs.get('Credit_Note.csv'))
            except Exception as e:
                st.error("Error during Credit Notes processing:")
                st.exception(e)

            try:
                processed_dfs['journals'] = process_journals(raw_dfs.get('Journal.csv'))
            except Exception as e:
                st.error("Error during Journals processing:")
                st.exception(e)

            try:
                processed_dfs['bills'] = process_bills(raw_dfs.get('Bill.csv'))
            except Exception as e:
                st.error("Error during Bills processing:")
                st.exception(e)
            
            st.success("Data cleaning and mapping attempts complete. Check for any errors above.")

            st.header("3. Generate Tally XML Files")
            generated_xmls = {}

            # --- Generate XMLs in recommended order with empty DataFrame check ---
            try:
                if processed_dfs.get('coa') is not None and not processed_dfs['coa'].empty:
                    generated_xmls['tally_ledgers.xml'] = generate_ledgers_xml(processed_dfs['coa'])
                else:
                    st.info("Skipping tally_ledgers.xml generation as Chart of Accounts data is empty.")
            except Exception as e:
                st.error("Error generating Ledgers XML:")
                st.exception(e)


            try:
                contacts_df_present = processed_dfs.get('contacts') is not None and not processed_dfs['contacts'].empty
                vendors_df_present = processed_dfs.get('vendors') is not None and not processed_dfs['vendors'].empty
                
                if contacts_df_present and vendors_df_present:
                    generated_xmls['tally_contacts_vendors.xml'] = generate_contacts_vendors_xml(processed_dfs['contacts'], processed_dfs['vendors'])
                elif contacts_df_present:
                    st.warning("Only Contacts data found (Vendors data is empty/missing). Attempting to generate contacts-only XML.")
                    generated_xmls['tally_contacts_vendors.xml'] = generate_contacts_vendors_xml(processed_dfs['contacts'], None)
                elif vendors_df_present:
                    st.warning("Only Vendors data found (Contacts data is empty/missing). Attempting to generate vendors-only XML.")
                    generated_xmls['tally_contacts_vendors.xml'] = generate_contacts_vendors_xml(None, processed_dfs['vendors'])
                else:
                    st.info("Skipping Contacts/Vendors XML generation as both Contacts and Vendors data are empty/missing.")
            except Exception as e:
                st.error("Error generating Contacts/Vendors XML:")
                st.exception(e)


            try:
                if processed_dfs.get('invoices') is not None and not processed_dfs['invoices'].empty:
                    generated_xmls['tally_sales_vouchers.xml'] = generate_sales_vouchers_xml(processed_dfs['invoices'])
                else:
                    st.info("Skipping Sales Vouchers XML generation as Invoices data is empty.")
            except Exception as e:
                st.error("Error generating Sales Vouchers XML:")
                st.exception(e)
            
            try:
                if processed_dfs.get('bills') is not None and not processed_dfs['bills'].empty:
                    generated_xmls['tally_purchase_vouchers.xml'] = generate_purchase_vouchers_xml(processed_dfs['bills'])
                else:
                    st.info("Skipping Purchase Vouchers XML generation as Bills data is empty.")
            except Exception as e:
                st.error("Error generating Purchase Vouchers XML:")
                st.exception(e)

            try:
                if processed_dfs.get('customer_payments') is not None and not processed_dfs['customer_payments'].empty:
                    generated_xmls['tally_receipt_vouchers.xml'] = generate_customer_payments_xml(processed_dfs['customer_payments'])
                else:
                    st.info("Skipping Receipt Vouchers XML generation as Customer Payments data is empty.")
            except Exception as e:
                st.error("Error generating Customer Payments XML:")
                st.exception(e)

            try:
                if processed_dfs.get('vendor_payments') is not None and not processed_dfs['vendor_payments'].empty:
                    generated_xmls['tally_payment_vouchers.xml'] = generate_vendor_payments_xml(processed_dfs['vendor_payments'])
                else:
                    st.info("Skipping Payment Vouchers XML generation as Vendor Payments data is empty.")
            except Exception as e:
                st.error("Error generating Vendor Payments XML:")
                st.exception(e)
            
            try:
                if processed_dfs.get('credit_notes') is not None and not processed_dfs['credit_notes'].empty:
                    generated_xmls['tally_credit_notes.xml'] = generate_credit_notes_xml(processed_dfs['credit_notes'])
                else:
                    st.info("Skipping Credit Notes XML generation as Credit Notes data is empty.")
            except Exception as e:
                st.error("Error generating Credit Notes XML:")
                st.exception(e)

            try:
                if processed_dfs.get('journals') is not None and not processed_dfs['journals'].empty:
                    generated_xmls['tally_journal_vouchers.xml'] = generate_journal_vouchers_xml(processed_dfs['journals'])
                else:
                    st.info("Skipping Journal Vouchers XML generation as Journals data is empty.")
            except Exception as e:
                st.error("Error generating Journal Vouchers XML:")
                st.exception(e)
            
            st.success("Tally XML generation attempts complete. Check for any errors above.")

            st.header("4. Download Generated XML Files")
            if generated_xmls:
                st.success("Your Tally XML files are ready for download:")
                for filename, xml_content in generated_xmls.items():
                    st.download_button(
                        label=f"Download {filename}",
                        data=xml_content.encode('utf-8'),
                        file_name=filename,
                        mime="application/xml"
                    )
                st.info("Remember to import masters first, then vouchers, into your Tally ERP company.")
            else:
                st.warning("No XML files were generated. Please review the warnings/errors above.")

        except zipfile.BadZipFile:
            st.error("The uploaded file is not a valid ZIP file. Please upload a correctly formatted Zoho backup ZIP.")
        except Exception as e:
            st.error(f"An unexpected error occurred during the overall process: {e}")
            st.exception(e) # Show full traceback for high-level errors

    st.markdown("---")

# --- 04_batch_import_instructions.md content displayed directly ---
st.header("5. Tally Import Instructions & Troubleshooting")
st.markdown(f"""
# Importing Data into Tally ERP

This guide provides step-by-step instructions on how to import the generated XML files (`.xml`) into your Tally ERP company.

**🚨 IMPORTANT WARNINGS & BEST PRACTICES 🚨**

* **TEST FIRST:** **ALWAYS perform a test import** into a brand-new, empty Tally company before attempting to import into your live production company. This is the single most important step to identify and resolve any mapping issues or errors without corrupting your actual data.
* **BACKUP:** Before any import into your live Tally company, take a **complete backup** of your Tally data.
* **TALLY COMPANY NAME:** Ensure the Tally Company Name in the script's configuration (`{TALLY_COMPANY_NAME}`) **exactly matches** the company you are importing into in Tally.
* **<span style="color:red;font-weight:bold;">CRITICAL: TALLY FINANCIAL YEAR SETTING</span>**: Your previous import logs showed many "The date is Out of Range!" errors. This is because your Zoho transactions are from 2023, but your new Tally company likely defaults to the current financial year (e.g., Apr 2025 - Mar 2026). **The Python script CANNOT change this in Tally.**
    * **Action**: Before importing any transactions, you **MUST** change your Tally company's financial year to encompass your oldest transaction date.
        1.  Open Tally (Prime or ERP 9).
        2.  Select your company (`{TALLY_COMPANY_NAME}`).
        3.  Go to `Gateway of Tally`.
        4.  In Tally Prime: Press `Alt + K` (Company) -> `Alter`.
        5.  In Tally ERP 9: Press `Alt + F3` (Company Info) -> `Alter`.
        6.  Set `Financial year from` and `Books beginning from` to a date *before or equal to your oldest Zoho transaction*. For example, if your oldest Zoho transaction is `20-Jul-2023`, set both fields to **`1-Apr-2023`** (if your financial year is April-March) or **`1-Jan-2023`** (if your financial year is Jan-Dec).
        7.  Accept the changes (`Ctrl + A`).
* **LEDGER NAMES (Check if still needed after mandatory ledgers)**: The script now attempts to create essential ledgers like 'Sales Account', 'Purchase Account', 'Round Off', and standard GST ledgers (`Output/Input CGST/SGST/IGST`), and 'Transportation Expense'.
    * **Action for "Ledger does not exist!" errors if they persist**: If these errors still occur after using this updated script and importing `tally_ledgers.xml`, it means a specific ledger referenced in a transaction (especially from `Journal.csv`'s 'Account' column) is still not found. You will need to:
        1.  **Identify the exact ledger name** from the Tally error log.
        2.  **Manually create that ledger** in your Tally company (e.g., `Gateway of Tally > Create > Ledger`) under the appropriate Tally Group (e.g., "Indirect Expenses" for an expense, "Sales Accounts" for a revenue).
        3.  **Ensure its exact spelling and case** matches the error message.
        4.  Then, try importing the problematic XML file again.
* **DUPLICATE VOUCHER NUMBERS (HIGH RISK)**: You mentioned that duplicate entries are "ok". However, for `VOUCHERNUMBER` (e.g., Invoice Number, Payment Number, Bill Number, Journal Number), Tally typically expects these to be unique per voucher type. If your source Zoho data has truly distinct transactions sharing the *same* `Invoice Number` (etc.), Tally might:
    * Reject subsequent vouchers with the same number.
    * Overwrite existing vouchers.
    * Cause incorrect bill-wise adjustments.
    * The app uses the `Invoice Number`/`Bill Number`/`Payment Number` as is. If these are truly duplicated for *different logical transactions* in your Zoho export, you may still encounter import issues. The safest approach is always to make these numbers unique in your source CSVs before import.

---

## Import Sequence

Tally generally requires a specific sequence for importing data to maintain data integrity. It's crucial to import **Masters** (Ledgers, Contacts/Vendors) before **Vouchers** (Transactions) that refer to those masters.

1.  **Masters:**
    * `tally_ledgers.xml` (Chart of Accounts, general ledgers and groups, now including common mandatory ledgers)
    * `tally_contacts_vendors.xml` (Customers as Sundry Debtors, Vendors as Sundry Creditors)

2.  **Vouchers (Financial Transactions):**
    * `tally_sales_vouchers.xml` (from Zoho Invoices)
    * `tally_purchase_vouchers.xml` (from Zoho Bills)
    * `tally_receipt_vouchers.xml` (from Zoho Customer Payments)
    * `tally_payment_vouchers.xml` (from Zoho Vendor Payments)
    * `tally_credit_notes.xml` (from Zoho Credit Notes)
    * `tally_journal_vouchers.xml` (from Zoho Journals)

---

## Step-by-Step Import Process in Tally ERP

1.  **<span style="color:red;font-weight:bold;">CRITICAL PRE-STEP: Adjust Tally Financial Year (as instructed above).</span>**
2.  **Open your Tally ERP Company:**
    * Launch Tally ERP 9 or Tally Prime.
    * Select the **new, empty company** you created for testing purposes (e.g., `'{TALLY_COMPANY_NAME}'`).
3.  **Locate the Generated XML Files:**
    * The XML files are located in the `output/` directory relative to where you ran `zoho_to_tally_app.py`.
    * Example Path: `C:\path\to\your\ZohoTallyMigration\output\` (if running locally)
4.  **Navigate to Import Data in Tally:**
    * From the **Gateway of Tally**:
        * Press `Alt + O` (Import Data)
        * Select `Masters` for ledger/group XMLs.
        * Select `Vouchers` for transaction XMLs.
5.  **Specify the XML File and Behavior:**
    * **For Masters (Ledgers, Contacts/Vendors):**
        * Go to `Import Data` > `Masters`.
        * **File to Import (XML):** Enter the full path to the XML file (e.g., `C:\path\to\your\ZohoTallyMigration\output\tally_ledgers.xml`).
        * **Behavior of Masters already existing:** `Combine Opening Balances` (or `Add New Masters`).
    * **For Vouchers (Sales, Purchase, Payments, etc.):**
        * Go to `Import Data` > `Vouchers`.
        * **File to Import (XML):** Enter the full path to the XML file (e.g., `C:\path\to\your\ZohoTallyMigration\output\tally_sales_vouchers.xml`).
        * **Behavior of Vouchers already existing:** `Add New Vouchers`. (Avoid `Replace Existing Vouchers` unless you know exactly what you're doing).
6.  **Initiate Import:**
    * After specifying the file path and behavior, press `Enter` to start the import process.
7.  **Monitor the Import:**
    * Tally will display a progress bar and then a summary message indicating the number of masters/vouchers imported and/or skipped.
    * If errors occur, Tally will usually pop up an error window or provide details in the Tally.ERP9.err (or similar) log file located in your Tally installation directory.

---

## Detailed Import for Each XML File (Recommended Order)

### 1. Import Master Data

**a. Ledgers and Groups**
* **File:** `tally_ledgers.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Masters`
* **Behavior:** `Combine Opening Balances` (or `Add New Masters`)
* **Verification:** After import, navigate to `Gateway of Tally` > `Display More Reports` > `List of Accounts`. Check under various groups (e.g., 'Indirect Expenses', 'Bank Accounts', 'Sales Accounts', 'Purchase Accounts', 'Duties & Taxes') to ensure all your Zoho Chart of Accounts entries, plus the newly added mandatory ledgers, have been created as Ledgers in Tally with their correct parent groups.

**b. Contacts (Sundry Debtors) and Vendors (Sundry Creditors)**
* **File:** `tally_contacts_vendors.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Masters`
* **Behavior:** `Combine Opening Balances` (or `Add New Masters`)
* **Verification:** Check `Gateway of Tally` > `Display More Reports` > `List of Accounts` under `Sundry Debtors` and `Sundry Creditors`. Select a few parties and drill down (`Alt+L`) to verify their addresses, GSTINs, contact details, and opening balances.

### 2. Import Financial Vouchers

**a. Sales Vouchers (from Invoices)**
* **File:** `tally_sales_vouchers.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Vouchers`
* **Behavior:** `Add New Vouchers`
* **Verification:**
    * Check `Gateway of Tally` > `Display More Reports` > `Day Book`. Review a sample of imported Sales Vouchers.
    * Drill down into a few vouchers to verify: Party Name and details, Date and Voucher Number, Sales Ledger, amounts, and GST application (CGST/SGST/IGST), Narration.
    * **Crucially, check `Bill-wise Details` (Alt+B or specific button) for 'New Ref' against the invoice number.**
    * Check individual Customer Ledger accounts (`Display More Reports` > `Account Books` > `Ledger` > Select Customer) to ensure balances are correct and bill-wise details reflect the new invoices.

**b. Purchase Vouchers (from Bills)**
* **File:** `tally_purchase_vouchers.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Vouchers`
* **Behavior:** `Add New Vouchers`
* **Verification:**
    * Check `Gateway of Tally` > `Display More Reports` > `Day Book`. Review a sample of imported Purchase Vouchers.
    * Verify Party Name, Date, Voucher Number, Purchase Ledger, amounts, GST, and **`Bill-wise Details` for 'New Ref' against the bill number.**
    * Check individual Vendor Ledger accounts for correct balances and bill-wise details.

**c. Receipt Vouchers (from Customer Payments)**
* **File:** `tally_receipt_vouchers.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Vouchers`
* **Behavior:** `Add New Vouchers`
* **Verification:**
    * Check `Day Book`. Verify Bank/Cash ledger debit and Customer ledger credit.
    * **Crucially, verify `Bill-wise Details` (Alt+B or specific button) for 'Agst Ref' matching the invoice number(s) paid.**
    * Check customer ledgers to ensure payments have reduced outstanding invoices.

**d. Payment Vouchers (from Vendor Payments)**
* **File:** `tally_payment_vouchers.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Vouchers`
* **Behavior:** `Add New Vouchers`
* **Verification:**
    * Check `Day Book`. Verify Vendor ledger debit and Bank/Cash ledger credit.
    * **Crucially, verify `Bill-wise Details` (Alt+B or specific button) for 'Agst Ref' matching the bill number(s) paid.**
    * Check vendor ledgers to ensure payments have reduced outstanding bills.

**e. Credit Note Vouchers**
* **File:** `tally_credit_notes.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Vouchers`
* **Behavior:** `Add New Vouchers`
* **Verification:**
    * Check `Day Book`. Verify Sales Returns (or similar) ledger debit and Customer ledger credit.
    * **Check for linking to Original Invoice Details for GST purposes.**
    * Verify `Bill-wise Details` (Alt+B or specific button) for 'Agst Ref' if the credit note was applied against a specific invoice.

**f. Journal Vouchers**
* **File:** `tally_journal_vouchers.xml`
* **Tally Menu:** `Gateway of Tally` > `Import Data` > `Vouchers`
* **Behavior:** `Add New Vouchers`
* **Verification:**
    * Check `Day Book`. Drill down into a few journal vouchers to ensure the debit and credit legs for each entry are correct and balanced.
    * Check affected ledger accounts to see if the journal entries have the intended impact on balances.

---

## Troubleshooting Common Import Errors

When Tally throws an error during import, it often means:

1.  **"Ledger Not Found"**:
    * **Cause:** A ledger name specified in the XML (e.g., a customer, vendor, income, expense, or tax ledger) does not exist in your Tally company with the exact name.
    * **Solution:** The updated script attempts to create common ledgers. If this error still occurs, it means a specific ledger used in a transaction (particularly from `Journal.csv`'s 'Account' column) is not one of the mandatory ones and also not in your Zoho `Chart_of_Accounts.csv`. You **must manually create that ledger in Tally** with the exact name.

2.  **"Invalid Date Format"**:
    * **Cause:** The date format in the XML is not `YYYYMMDD`.
    * **Solution:** The Python script aims to format dates correctly. If this error occurs, investigate the original Zoho date format in your source CSVs.

3.  **"Error in XML Structure" / "Invalid XML Tag"**:
    * **Cause:** The XML generated has a syntax error, incorrect tag names, or improper nesting according to Tally's schema.
    * **Solution:** This is rare if the script runs without errors, but if it happens, there might be a subtle bug or an edge case in your data.

4.  **"Amount Mismatch" / "Debit-Credit Imbalance"**:
    * **Cause:** For a voucher (e.g., Sales, Purchase, Journal), the total debits do not equal total credits. This is a fundamental accounting principle.
    * **Solution:** Review your data in the original Zoho CSVs and how totals are calculated (e.g., `Item Total`, `SubTotal`, `Total`, `Adjustment`, taxes). The script includes warnings for imbalanced journals.

5.  **GST Related Errors**:
    * **Cause:** Incorrect GSTIN, wrong GST registration type, mismatch between state code and GSTIN, or incorrect tax ledgers being used for intra/inter-state transactions.
    * **Solution:** Verify the `GSTIN` and `GST Treatment` fields for your customers/vendors and invoices/bills. Confirm the mapping of `Place of Supply(With State Code)` in the script. Ensure your 'Output CGST', 'Output SGST', 'Output IGST', 'Input CGST', 'Input SGST', 'Input IGST' ledgers exist in Tally and are configured correctly as 'Duties & Taxes' with the appropriate GST types and percentages.

---

## Final Post-Import Verification

After successfully importing all XML files into your **test Tally company**:

* **Trial Balance:** Compare the Trial Balance generated in Tally with your Zoho's Trial Balance report as of the migration cut-off date.
* **Balance Sheet & Profit & Loss:** Review these financial statements for accuracy and consistency with Zoho.
* **Account Books:** Drill down into key ledger accounts (e.g., your Bank accounts, Cash, Sundry Debtors, Sundry Creditors) and cross-verify their balances and transactions with Zoho.
* **Outstanding Receivables/Payables:** Verify that the 'Bills Receivable' and 'Bills Payable' reports in Tally match the outstanding amounts in Zoho.
* **GST Reports (if applicable):** Generate GSTR-1 and GSTR-2 (or relevant GST reports) in Tally and compare them with your Zoho GST reports for the migrated period.
* **Sample Vouchers:** Randomly open 5-10 vouchers of each type (Sales, Purchase, Receipt, Payment, Journal, Credit Note) and compare every detail (date, amount, ledger allocation, narration, bill-wise details) against the original Zoho data.

Once you are confident in the accuracy of the imported data in your test company, you can proceed to import into your live Tally company (after taking a fresh backup!).
""")
