import streamlit as st
import zipfile
import os
import pandas as pd
from lxml import etree
from datetime import datetime
import io
import tempfile
import shutil
import math # For math.isnan

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

# --- Helper Functions ---

def safe_str(value):
    """Converts a value to a string, handling NaN and None gracefully."""
    if pd.isna(value) or value is None:
        return ""
    # Ensure no floating point decimals on numbers that are actually integers
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)

def format_date_column(df, column_name):
    """
    Converts a date column to Tally-compatible 'yyyyMMdd' string format.
    Handles various input formats and gracefully ignores errors or empty values.
    """
    if column_name in df.columns:
        # Convert column to datetime objects, coercing errors to NaT (Not a Time)
        # This prevents the script from crashing on bad date data.
        temp_date_col = pd.to_datetime(df[column_name], errors='coerce')
        
        # Format the valid dates into 'yyyyMMdd' format required by Tally.
        # Replace any conversion errors (NaT) with an empty string.
        df[column_name] = temp_date_col.dt.strftime('%Y%m%d').fillna('')
    return df

def clean_column_names(df):
    """Remove leading/trailing spaces and special characters from column names."""
    df.columns = df.columns.str.strip().str.replace('[^0-9a-zA-Z_]', '', regex=True)
    return df

# --- Data Processing Functions ---

def process_chart_of_accounts(df):
    """Processes the Chart_of_Accounts.csv to create Tally Master XML for ledgers."""
    if df is None or df.empty:
        return None, "Chart of Accounts data is missing or empty."

    # Filter out accounts we don't need to migrate (like system accounts)
    df_cleaned = df[~df['Account Name'].isin(['TDS Payable', 'TDS Receivable', 'Sales', 'Purchase'])].copy()
    
    # Map Zoho Account Types to Tally Parent Groups
    parent_map = {
        'Cash': 'Cash-in-Hand',
        'Bank': 'Bank Accounts',
        'Stock': 'Stock-in-Hand',
        'Other Current Asset': 'Current Assets',
        'Fixed Asset': 'Fixed Assets',
        'Other Asset': 'Current Assets', # Or investigate further if non-current
        'Other Current Liability': 'Current Liabilities',
        'Credit Card': 'Bank OD A/c',
        'Long Term Liability': 'Loans (Liability)',
        'Other Liability': 'Current Liabilities',
        'Equity': 'Capital Account',
        'Income': 'Direct Incomes', # Or Indirect Incomes
        'Other Income': 'Indirect Incomes',
        'Expense': 'Direct Expenses', # Or Indirect Expenses
        'Cost of Goods Sold': 'Purchase Accounts',
        'Other Expense': 'Indirect Expenses'
    }
    df_cleaned['TALLYGROUP'] = df_cleaned['Account Type'].map(parent_map).fillna('Suspense')
    
    # Create the root of the Tally XML
    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=safe_str(row['Account Name']), ACTION="Create")
        etree.SubElement(ledger, 'NAME').text = safe_str(row['Account Name'])
        etree.SubElement(ledger, 'PARENT').text = safe_str(row['TALLYGROUP'])
        etree.SubElement(ledger, 'ISBILLWISEON').text = "No" # Default, can be changed later
        
        # Add opening balances if they exist
        if 'Opening Balance' in df_cleaned.columns and pd.notna(row['Opening Balance']) and row['Opening Balance'] != 0:
             opening_balance = float(row['Opening Balance'])
             balance_text = f"{abs(opening_balance)} {'Dr' if opening_balance >= 0 else 'Cr'}"
             etree.SubElement(ledger, 'OPENINGBALANCE').text = balance_text

    return tally_message, None

def process_items(df):
    """Processes Item.csv to create Tally Master XML for Stock Items."""
    if df is None or df.empty:
        return None, "Items data is missing or empty."
    
    df_cleaned = df.copy()
    
    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        item_name = safe_str(row['Name'])
        
        # Create Stock Group (assuming 'Item Type' can be a group)
        stock_group_name = safe_str(row.get('Item Type', 'Primary'))
        if not stock_group_name:
            stock_group_name = 'Primary'
            
        group = etree.SubElement(tally_message, 'STOCKGROUP', NAME=stock_group_name, ACTION="Create")
        etree.SubElement(group, 'NAME').text = stock_group_name
        etree.SubElement(group, 'PARENT').text = ""

        # Create Stock Item
        stock_item = etree.SubElement(tally_message, 'STOCKITEM', NAME=item_name, ACTION="Create")
        etree.SubElement(stock_item, 'NAME').text = item_name
        etree.SubElement(stock_item, 'PARENT').text = stock_group_name
        
        # Assuming base units are 'Nos' or 'Pcs'. This should be configured.
        etree.SubElement(stock_item, 'BASEUNITS').text = "Nos" 

    return tally_message, None

def process_contacts(df):
    """Processes Contacts.csv to create Tally Ledger Masters for Debtors."""
    if df is None or df.empty:
        return None, "Contacts (Customers) data is missing or empty."
        
    df_cleaned = df.copy()
    # Fill NaN values in address fields to prevent errors
    address_cols = ['Billing Street', 'Billing City', 'Billing State', 'Billing Code', 'Billing Country']
    for col in address_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('')

    df_cleaned = format_date_column(df_cleaned, 'Created Time')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    
    for _, row in df_cleaned.iterrows():
        customer_name = f"{safe_str(row['First Name'])} {safe_str(row['Last Name'])}".strip()
        if not customer_name:
             customer_name = safe_str(row['Company Name'])

        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=customer_name, ACTION="Create")
        etree.SubElement(ledger, 'NAME').text = customer_name
        etree.SubElement(ledger, 'PARENT').text = 'Sundry Debtors'
        etree.SubElement(ledger, 'ISBILLWISEON').text = "Yes"
        
        # Address Details
        address = etree.SubElement(ledger, 'ADDRESS.LIST', TYPE="String")
        etree.SubElement(address, 'ADDRESS').text = safe_str(row.get('Billing Street', ''))
        etree.SubElement(address, 'ADDRESS').text = safe_str(row.get('Billing City', ''))
        
        etree.SubElement(ledger, 'MAILINGNAME').text = customer_name
        etree.SubElement(ledger, 'STATE').text = safe_str(row.get('Billing State', ''))
        etree.SubElement(ledger, 'PINCODE').text = safe_str(row.get('Billing Code', ''))
        etree.SubElement(ledger, 'COUNTRYNAME').text = safe_str(row.get('Billing Country', DEFAULT_COUNTRY))
        
        # Opening Balance
        if 'Opening Balance' in df_cleaned.columns and pd.notna(row['Opening Balance']) and row['Opening Balance'] != 0:
            opening_balance = float(row['Opening Balance'])
            balance_text = f"{abs(opening_balance)} {'Dr' if opening_balance >= 0 else 'Cr'}"
            etree.SubElement(ledger, 'OPENINGBALANCE').text = balance_text

    return tally_message, None

def process_vendors(df):
    """Processes Vendors.csv to create Tally Ledger Masters for Creditors."""
    if df is None or df.empty:
        return None, "Vendors data is missing or empty."

    df_cleaned = df.copy()
    address_cols = ['Billing Street', 'Billing City', 'Billing State', 'Billing Code', 'Billing Country']
    for col in address_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('')
            
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    
    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        vendor_name = f"{safe_str(row['First Name'])} {safe_str(row['Last Name'])}".strip()
        if not vendor_name:
             vendor_name = safe_str(row['Company Name'])

        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=vendor_name, ACTION="Create")
        etree.SubElement(ledger, 'NAME').text = vendor_name
        etree.SubElement(ledger, 'PARENT').text = 'Sundry Creditors'
        etree.SubElement(ledger, 'ISBILLWISEON').text = "Yes"
        
        # Address Details
        address = etree.SubElement(ledger, 'ADDRESS.LIST', TYPE="String")
        etree.SubElement(address, 'ADDRESS').text = safe_str(row.get('Billing Street', ''))
        etree.SubElement(address, 'ADDRESS').text = safe_str(row.get('Billing City', ''))
        
        etree.SubElement(ledger, 'MAILINGNAME').text = vendor_name
        etree.SubElement(ledger, 'STATE').text = safe_str(row.get('Billing State', ''))
        etree.SubElement(ledger, 'PINCODE').text = safe_str(row.get('Billing Code', ''))
        etree.SubElement(ledger, 'COUNTRYNAME').text = safe_str(row.get('Billing Country', DEFAULT_COUNTRY))
        
        # Opening Balance
        if 'Opening Balance' in df_cleaned.columns and pd.notna(row['Opening Balance']) and row['Opening Balance'] != 0:
            opening_balance = float(row['Opening Balance'])
            balance_text = f"{abs(opening_balance)} {'Cr' if opening_balance >= 0 else 'Dr'}" # Note: Cr for Creditors
            etree.SubElement(ledger, 'OPENINGBALANCE').text = balance_text

    return tally_message, None


def process_invoices(df):
    """Processes Invoice.csv to create Tally Sales Vouchers."""
    if df is None or df.empty:
        return None, "Invoices data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Invoice Date')
    df_cleaned = format_date_column(df_cleaned, 'Due Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Sales", ACTION="Create")
        
        etree.SubElement(vch, 'DATE').text = safe_str(row['Invoice Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Invoice#'])
        etree.SubElement(vch, 'REFERENCE').text = safe_str(row['Order Number'])
        etree.SubElement(vch, 'NARRATION').text = f"Sales against Invoice {safe_str(row['Invoice#'])}. {safe_str(row['Notes'])}"
        
        # --- Ledger Entries ---
        customer_name = safe_str(row['Customer Name'])
        total_amount = float(row['Total'])

        # 1. Debtor Ledger (Debit)
        debtor_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(debtor_ledger, 'LEDGERNAME').text = customer_name
        etree.SubElement(debtor_ledger, 'ISDEEMEDPOSITIVE').text = "Yes" # Debit
        etree.SubElement(debtor_ledger, 'AMOUNT').text = f"-{total_amount}" # Negative for Dr in Tally XML

        # Bill-wise details for the debtor
        bill_alloc = etree.SubElement(debtor_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = safe_str(row['Invoice#'])
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "New Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = f"-{total_amount}"

        # 2. Sales Ledger (Credit) - Assuming a generic 'Sales' ledger
        sales_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(sales_ledger, 'LEDGERNAME').text = "Sales" # This should exist in Tally
        etree.SubElement(sales_ledger, 'ISDEEMEDPOSITIVE').text = "No" # Credit
        etree.SubElement(sales_ledger, 'AMOUNT').text = f"{total_amount}" # Positive for Cr

    return tally_message, None

def process_customer_payments(df):
    """Processes Customer_Payment.csv to create Tally Receipt Vouchers."""
    if df is None or df.empty:
        return None, "Customer Payments data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Payment Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Receipt", ACTION="Create")
        
        etree.SubElement(vch, 'DATE').text = safe_str(row['Payment Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Payment#'])
        etree.SubElement(vch, 'NARRATION').text = f"Received from {safe_str(row['Customer Name'])} via {safe_str(row['Payment Mode'])}. Ref: {safe_str(row['Reference#'])}"
        
        customer_name = safe_str(row['Customer Name'])
        amount_received = float(row['Amount Received'])
        
        # 1. Bank/Cash Ledger (Debit) - Assuming payment goes to a default 'Bank' account
        bank_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(bank_ledger, 'LEDGERNAME').text = "Bank" # This needs to be a real ledger in Tally
        etree.SubElement(bank_ledger, 'ISDEEMEDPOSITIVE').text = "Yes" # Debit
        etree.SubElement(bank_ledger, 'AMOUNT').text = f"-{amount_received}"
        
        # 2. Customer Ledger (Credit)
        customer_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(customer_ledger, 'LEDGERNAME').text = customer_name
        etree.SubElement(customer_ledger, 'ISDEEMEDPOSITIVE').text = "No" # Credit
        etree.SubElement(customer_ledger, 'AMOUNT').text = str(amount_received)

        # Bill-wise details for knocking off the invoice
        bill_alloc = etree.SubElement(customer_ledger, 'BILLALLOCATIONS.LIST')
        # We need the invoice number this payment is against. Assuming it's in a column.
        # This is a critical piece of information. Using Payment# as a placeholder if not found.
        invoice_ref = safe_str(row.get('Invoice#', row.get('Payment#')))
        etree.SubElement(bill_alloc, 'NAME').text = invoice_ref
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "Agst Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = str(amount_received)

    return tally_message, None

def process_bills(df):
    """Processes Bill.csv to create Tally Purchase Vouchers."""
    if df is None or df.empty:
        return None, "Bills (Purchases) data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Bill Date')
    df_cleaned = format_date_column(df_cleaned, 'Due Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Purchase", ACTION="Create")
        
        etree.SubElement(vch, 'DATE').text = safe_str(row['Bill Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Bill#'])
        etree.SubElement(vch, 'NARRATION').text = f"Purchase from {safe_str(row['Vendor Name'])}. Ref: {safe_str(row['Order Number'])}"

        vendor_name = safe_str(row['Vendor Name'])
        total_amount = float(row['Total'])

        # 1. Vendor Ledger (Credit)
        vendor_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(vendor_ledger, 'LEDGERNAME').text = vendor_name
        etree.SubElement(vendor_ledger, 'ISDEEMEDPOSITIVE').text = "No" # Credit
        etree.SubElement(vendor_ledger, 'AMOUNT').text = str(total_amount)

        # Bill-wise details for the vendor
        bill_alloc = etree.SubElement(vendor_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = safe_str(row['Bill#'])
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "New Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = str(total_amount)

        # 2. Purchase Ledger (Debit) - Assuming a generic 'Purchase' ledger
        purchase_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(purchase_ledger, 'LEDGERNAME').text = "Purchase" # Must exist in Tally
        etree.SubElement(purchase_ledger, 'ISDEEMEDPOSITIVE').text = "Yes" # Debit
        etree.SubElement(purchase_ledger, 'AMOUNT').text = f"-{total_amount}"

    return tally_message, None

def process_vendor_payments(df):
    """Processes Vendor_Payment.csv to create Tally Payment Vouchers."""
    if df is None or df.empty:
        return None, "Vendor Payments data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Payment Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Payment", ACTION="Create")
        
        etree.SubElement(vch, 'DATE').text = safe_str(row['Payment Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Payment#'])
        etree.SubElement(vch, 'NARRATION').text = f"Paid to {safe_str(row['Vendor Name'])} via {safe_str(row['Payment Mode'])}. Ref: {safe_str(row['Reference#'])}"
        
        vendor_name = safe_str(row['Vendor Name'])
        amount_paid = float(row['Amount'])
        
        # 1. Vendor Ledger (Debit)
        vendor_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(vendor_ledger, 'LEDGERNAME').text = vendor_name
        etree.SubElement(vendor_ledger, 'ISDEEMEDPOSITIVE').text = "Yes" # Debit
        etree.SubElement(vendor_ledger, 'AMOUNT').text = f"-{amount_paid}"

        # Bill-wise details for knocking off the bill
        bill_alloc = etree.SubElement(vendor_ledger, 'BILLALLOCATIONS.LIST')
        # This is a critical piece of info. Assuming it's available.
        bill_ref = safe_str(row.get('Bill#', row.get('Payment#'))) 
        etree.SubElement(bill_alloc, 'NAME').text = bill_ref
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "Agst Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = f"-{amount_paid}"
        
        # 2. Bank/Cash Ledger (Credit)
        bank_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(bank_ledger, 'LEDGERNAME').text = "Bank" # Must exist in Tally
        etree.SubElement(bank_ledger, 'ISDEEMEDPOSITIVE').text = "No" # Credit
        etree.SubElement(bank_ledger, 'AMOUNT').text = str(amount_paid)

    return tally_message, None


def process_credit_notes(df):
    """Processes Credit_Note.csv to create Tally Credit Note Vouchers."""
    if df is None or df.empty:
        return None, "Credit Notes data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Credit Note Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")

    for _, row in df_cleaned.iterrows():
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Credit Note", ACTION="Create")
        
        etree.SubElement(vch, 'DATE').text = safe_str(row['Credit Note Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Credit Note#'])
        etree.SubElement(vch, 'NARRATION').text = f"Credit note for {safe_str(row['Customer Name'])}. Reason: {safe_str(row['Reason'])}"
        
        customer_name = safe_str(row['Customer Name'])
        total_amount = float(row['Total'])
        
        # 1. Sales Return / Relevant Account (Debit)
        sales_return_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        # Assuming a 'Sales Return' ledger. This might need to be 'Sales' itself.
        etree.SubElement(sales_return_ledger, 'LEDGERNAME').text = "Sales" 
        etree.SubElement(sales_return_ledger, 'ISDEEMEDPOSITIVE').text = "Yes" # Debit
        etree.SubElement(sales_return_ledger, 'AMOUNT').text = f"-{total_amount}"
        
        # 2. Customer Ledger (Credit)
        customer_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(customer_ledger, 'LEDGERNAME').text = customer_name
        etree.SubElement(customer_ledger, 'ISDEEMEDPOSITIVE').text = "No" # Credit
        etree.SubElement(customer_ledger, 'AMOUNT').text = str(total_amount)
        
        # Bill-wise details
        bill_alloc = etree.SubElement(customer_ledger, 'BILLALLOCATIONS.LIST')
        # Usually against an existing invoice, or as a new credit
        etree.SubElement(bill_alloc, 'NAME').text = safe_str(row['Credit Note#'])
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "Agst Ref" # Or New Ref if it's a fresh credit
        etree.SubElement(bill_alloc, 'AMOUNT').text = str(total_amount)

    return tally_message, None

def process_journals(df):
    """Processes Journal.csv to create Tally Journal Vouchers."""
    if df is None or df.empty:
        return None, "Journals data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Journal Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    
    # Group by Journal ID to process each journal entry as one voucher
    for journal_id, group in df_cleaned.groupby('Journal ID'):
        first_row = group.iloc[0]
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Journal", ACTION="Create")
        
        etree.SubElement(vch, 'DATE').text = safe_str(first_row['Journal Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(first_row['Journal#'])
        etree.SubElement(vch, 'NARRATION').text = safe_str(first_row['Notes'])

        for _, row in group.iterrows():
            # Debit Entry
            debit_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
            etree.SubElement(debit_ledger, 'LEDGERNAME').text = safe_str(row['Account'])
            etree.SubElement(debit_ledger, 'ISDEEMEDPOSITIVE').text = "Yes" # Debit
            etree.SubElement(debit_ledger, 'AMOUNT').text = f"-{safe_str(row['Debits'])}"
            
            # Credit Entry
            credit_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
            etree.SubElement(credit_ledger, 'LEDGERNAME').text = safe_str(row['Account'])
            etree.SubElement(credit_ledger, 'ISDEEMEDPOSITIVE').text = "No" # Credit
            etree.SubElement(credit_ledger, 'AMOUNT').text = safe_str(row['Credits'])

    return tally_message, None

# --- Main Application Logic (Streamlit) ---

st.set_page_config(layout="wide", page_title="Zoho to Tally Migration Tool")

st.title("Zoho Books to Tally XML Migration Tool 🧾")
st.markdown("""
This tool converts a **Zoho Books backup ZIP file** into multiple **Tally-compatible XML files**. 
You can then import these XML files into Tally to migrate your data.

**⚠️ Important:**
1.  **Backup Tally:** Always back up your Tally company before importing any data.
2.  **Test First:** Import the generated XML files into a **test Tally company** first to verify correctness.
3.  **Company Name:** The Tally Company Name in the generated XML is set to `Plant Essentials Private Limited`. This must match your Tally company name *exactly*.
""")

uploaded_zip = st.file_uploader("1. Upload your Zoho Books Backup ZIP file", type="zip")

if uploaded_zip is not None:
    st.success(f"✅ Successfully uploaded `{uploaded_zip.name}`.")
    
    # Create a temporary directory to extract files
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, uploaded_zip.name)
        with open(zip_path, "wb") as f:
            f.write(uploaded_zip.getbuffer())
        
        # --- File Extraction and Reading ---
        st.subheader("2. Reading CSV files from ZIP")
        
        raw_dfs = {}
        errors = []
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Find the root folder inside the zip more robustly.
                # It finds the first expected CSV and assumes its directory is the root.
                root_folder = None
                # Create a list of files to check, starting with the most likely ones
                files_to_search = ['Chart_of_Accounts.csv', 'Invoice.csv', 'Contacts.csv'] + ZOHO_CSVS

                for file_name_to_find in files_to_search:
                    for member_path in zf.namelist():
                        # Normalize path separators for consistency
                        normalized_path = member_path.replace('\\', '/')
                        if normalized_path.endswith('/' + file_name_to_find) or normalized_path == file_name_to_find:
                            # The directory part of the path is our root folder
                            root_folder = os.path.dirname(normalized_path)
                            # Add a trailing slash if the folder is not the root of the zip
                            if root_folder:
                                root_folder += '/'
                            break # Exit inner loop once found
                    if root_folder is not None:
                        break # Exit outer loop once found

                if root_folder is None:
                     st.error("Could not determine the root data folder inside the ZIP file. Please ensure the ZIP structure is standard and contains expected CSVs.")
                     st.stop()


                with st.spinner("Extracting and reading CSV files..."):
                    for file_name in ZOHO_CSVS:
                        try:
                            # Construct the full path to the file inside the zip
                            full_file_path_in_zip = root_folder + file_name
                            
                            with zf.open(full_file_path_in_zip) as csv_file:
                                df = pd.read_csv(csv_file, low_memory=False)
                                raw_dfs[file_name] = df
                                st.write(f"  - Found and read `{file_name}` ({len(df)} rows)")
                        except KeyError:
                            st.warning(f"  - ⚠️ File `{file_name}` not found in the ZIP. It will be skipped.")
                            raw_dfs[file_name] = None
                        except Exception as e:
                            st.error(f"  - ❌ Error reading `{file_name}`: {e}")
                            errors.append(file_name)

        except zipfile.BadZipFile:
            st.error("The uploaded file is not a valid ZIP file.")
            st.stop()
        except Exception as e:
            st.error(f"An unexpected error occurred during ZIP file processing: {e}")
            st.stop()

        if errors:
            st.error(f"Could not process the following files: {', '.join(errors)}. Processing will continue without them.")
            
        # --- Data Processing and XML Generation ---
        st.subheader("3. Processing Data and Generating XML")
        
        processed_dfs = {}
        xml_outputs = {}
        
        # Define processing order
        processing_pipeline = {
            # Masters
            "chart_of_accounts": ("Chart_of_Accounts.csv", process_chart_of_accounts),
            "items": ("Item.csv", process_items),
            "contacts": ("Contacts.csv", process_contacts),
            "vendors": ("Vendors.csv", process_vendors),
            # Vouchers
            "invoices": ("Invoice.csv", process_invoices),
            "customer_payments": ("Customer_Payment.csv", process_customer_payments),
            "bills": ("Bill.csv", process_bills),
            "vendor_payments": ("Vendor_Payment.csv", process_vendor_payments),
            "credit_notes": ("Credit_Note.csv", process_credit_notes),
            "journals": ("Journal.csv", process_journals),
        }

        with st.spinner("Converting data to Tally XML format..."):
            for key, (csv_name, process_func) in processing_pipeline.items():
                st.write(f"Processing {key.replace('_', ' ').title()}...")
                try:
                    df = raw_dfs.get(csv_name)
                    if df is not None:
                        xml_tree, error_msg = process_func(df)
                        if error_msg:
                            st.warning(f"  - Skipped: {error_msg}")
                        elif xml_tree is not None:
                            processed_dfs[key] = xml_tree
                            st.write(f"  - ✅ Success")
                        else:
                            st.write(f"  - ⚪️ No data to process.")
                    else:
                        st.write(f"  - ⚪️ Skipped (CSV not found).")
                except Exception as e:
                    st.error(f"  - ❌ An error occurred during {key} processing: {e}")
                    # In-depth traceback for debugging
                    # import traceback
                    # st.code(traceback.format_exc())

        # --- XML File Generation and Download ---
        st.subheader("4. Download Your Tally XML Files")
        st.markdown("Import these files into Tally **one by one, in the order they are listed below**.")

        # Create a new temporary directory for the output zip
        output_zip_path = os.path.join(temp_dir, "tally_import_files.zip")

        with zipfile.ZipFile(output_zip_path, 'w') as zf:
            for i, (key, xml_tree) in enumerate(processed_dfs.items()):
                # Create the full XML structure
                envelope = etree.Element('ENVELOPE')
                header = etree.SubElement(envelope, 'HEADER')
                etree.SubElement(header, 'TALLYREQUEST').text = "Import Data"
                body = etree.SubElement(envelope, 'BODY')
                import_data = etree.SubElement(body, 'IMPORTDATA')
                req_desc = etree.SubElement(import_data, 'REQUESTDESC')
                etree.SubElement(req_desc, 'REPORTNAME').text = "All Masters" if "chart" in key or "item" in key or "contact" in key or "vendor" in key else "Vouchers"
                static_vars = etree.SubElement(req_desc, 'STATICVARIABLES')
                etree.SubElement(static_vars, 'SVCURRENTCOMPANY').text = TALLY_COMPANY_NAME
                
                req_data = etree.SubElement(import_data, 'REQUESTDATA')
                req_data.append(xml_tree)
                
                # Prettify and write XML to a string
                xml_string = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding='UTF-8')
                
                # Write to the zip file
                filename = f"{i+1:02d}_{key}.xml"
                zf.writestr(filename, xml_string)
        
        # Provide the zip file for download
        with open(output_zip_path, "rb") as f:
            st.download_button(
                label="📥 Download All XML Files (as .zip)",
                data=f,
                file_name="tally_import_files.zip",
                mime="application/zip",
            )
            
st.markdown("---")
st.info("""
**How to Import into Tally:**
1.  Go to `Gateway of Tally` > `Import Data` > `Masters` or `Vouchers`.
2.  Select the XML file path.
3.  Choose the appropriate behavior (e.g., 'Combine Opening Balances').
4.  Press `Enter` to import.
""")

st.markdown("""
---

### Migration Checklist & Verification Steps

This is a **critical** part of the process. Do not skip it.

#### Pre-Import Checklist:
* **Company Created:** You have created a new company in Tally with the **exact same name** (`Plant Essentials Private Limited`) and the correct financial year (`1-Apr-2024` to `31-Mar-2025`).
* **Features Enabled:** You have enabled relevant features in Tally (`F11` > `Features`). At a minimum:
    * `Enable Bill-wise entry` under Accounting Features.
    * `Maintain stock categories` and `Maintain batch-wise details` if needed under Inventory Features.
    * Enable Goods & Services Tax (GST) and enter your company's GSTIN and other details if applicable.
* **Base Ledgers:** Ensure that default ledgers like 'Sales', 'Purchase', 'Bank', 'Cash', 'CGST', 'SGST', 'IGST' (if applicable) exist in your Tally company. This script assumes they do. For example, `Output CGST`, `Output SGST`, `Output IGST`, `Input CGST`, `Input SGST`, `Input IGST` ledgers exist in Tally and are configured correctly as 'Duties & Taxes' with the appropriate GST types and percentages.

---

### Final Post-Import Verification

After successfully importing all XML files into your **test Tally company**:

* **Trial Balance:** Compare the Trial Balance generated in Tally with your Zoho's Trial Balance report as of the migration cut-off date.
* **Balance Sheet & Profit & Loss:** Review these financial statements for accuracy and consistency with Zoho.
* **Account Books:** Drill down into key ledger accounts (e.g., your Bank accounts, Cash, Sundry Debtors, Sundry Creditors) and cross-verify their balances and transactions with Zoho.
* **Outstanding Receivables/Payables:** Verify that the 'Bills Receivable' and 'Bills Payable' reports in Tally match the outstanding amounts in Zoho.
* **GST Reports (if applicable):** Generate GSTR-1 and GSTR-2 (or relevant GST reports) in Tally and compare them with your Zoho GST reports for the migrated period.
* **Sample Vouchers:** Randomly open 5-10 vouchers of each type (Sales, Purchase, Receipt, Payment, Journal, Credit Note) and compare every detail (date, amount, ledger allocation, narration, bill-wise details) against the original Zoho data.

Once you are confident in the accuracy of the imported data in your test company, you can proceed to import into your live Tally company (after taking a fresh backup!).
""")
