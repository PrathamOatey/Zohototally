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

# --- Global Mappings ---
# These dictionaries will hold mappings from Zoho IDs to the canonical name used in Tally.
# This ensures consistency between master and voucher files.
CUSTOMER_ID_TO_NAME_MAP = {}
VENDOR_ID_TO_NAME_MAP = {}


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
        temp_date_col = pd.to_datetime(df[column_name], errors='coerce')
        
        # Format the valid dates into 'yyyyMMdd' format required by Tally.
        # Replace any conversion errors (NaT) with an empty string.
        df[column_name] = temp_date_col.dt.strftime('%Y%m%d').fillna('')
    return df

# --- Data Processing Functions ---

def process_chart_of_accounts(df):
    """Processes the Chart_of_Accounts.csv to create Tally Master XML for ledgers."""
    if df is None or df.empty:
        return None, "Chart of Accounts data is missing or empty."

    df_cleaned = df[~df['Account Name'].isin(['TDS Payable', 'TDS Receivable', 'Sales', 'Purchase'])].copy()
    
    parent_map = {
        'Cash': 'Cash-in-Hand', 'Bank': 'Bank Accounts', 'Stock': 'Stock-in-Hand',
        'Other Current Asset': 'Current Assets', 'Fixed Asset': 'Fixed Assets',
        'Other Asset': 'Current Assets', 'Other Current Liability': 'Current Liabilities',
        'Credit Card': 'Bank OD A/c', 'Long Term Liability': 'Loans (Liability)',
        'Other Liability': 'Current Liabilities', 'Equity': 'Capital Account',
        'Income': 'Direct Incomes', 'Other Income': 'Indirect Incomes',
        'Expense': 'Direct Expenses', 'Cost of Goods Sold': 'Purchase Accounts',
        'Other Expense': 'Indirect Expenses'
    }
    # Use 'Suspense A/c' as the fallback, which is Tally's default.
    df_cleaned['TALLYGROUP'] = df_cleaned['Account Type'].map(parent_map).fillna('Suspense A/c')
    
    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    for _, row in df_cleaned.iterrows():
        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=safe_str(row['Account Name']), ACTION="Create")
        etree.SubElement(ledger, 'NAME').text = safe_str(row['Account Name'])
        etree.SubElement(ledger, 'PARENT').text = safe_str(row['TALLYGROUP'])
        etree.SubElement(ledger, 'ISBILLWISEON').text = "No"
        
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
    
    # --- Create Unit of Measure Master ---
    # This prevents the "Unit 'Nos' does not exist" error in Tally.
    unit = etree.SubElement(tally_message, 'UNIT', NAME="Nos", ACTION="Create")
    etree.SubElement(unit, 'NAME').text = "Nos"
    etree.SubElement(unit, 'ISSIMPLEUNIT').text = "Yes"
    etree.SubElement(unit, 'FORMALNAME').text = "Numbers"

    for _, row in df_cleaned.iterrows():
        item_name = safe_str(row['Item Name'])
        stock_group_name = safe_str(row.get('Item Type', 'Primary')) or 'Primary'
            
        group = etree.SubElement(tally_message, 'STOCKGROUP', NAME=stock_group_name, ACTION="Create")
        etree.SubElement(group, 'NAME').text = stock_group_name
        etree.SubElement(group, 'PARENT').text = ""

        stock_item = etree.SubElement(tally_message, 'STOCKITEM', NAME=item_name, ACTION="Create")
        etree.SubElement(stock_item, 'NAME').text = item_name
        etree.SubElement(stock_item, 'PARENT').text = stock_group_name
        etree.SubElement(stock_item, 'BASEUNITS').text = "Nos" 

    return tally_message, None

def process_contacts(df):
    """Processes Contacts.csv to create Tally Ledger Masters for Debtors."""
    if df is None or df.empty:
        return None, "Contacts (Customers) data is missing or empty."
        
    df_cleaned = df.copy()
    address_cols = ['Billing Street', 'Billing City', 'Billing State', 'Billing Code', 'Billing Country']
    for col in address_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('')
    df_cleaned = format_date_column(df_cleaned, 'Created Time')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    
    for _, row in df_cleaned.iterrows():
        customer_name = f"{safe_str(row['First Name'])} {safe_str(row['Last Name'])}".strip() or safe_str(row['Company Name'])
        
        # Skip rows where the name is blank to prevent "No Valid Names!" error.
        if not customer_name:
            continue
            
        # Populate the global map for later reference by vouchers
        customer_id = safe_str(row.get('Contact ID'))
        if customer_id:
            CUSTOMER_ID_TO_NAME_MAP[customer_id] = customer_name

        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=customer_name, ACTION="Create")
        etree.SubElement(ledger, 'NAME').text = customer_name
        etree.SubElement(ledger, 'PARENT').text = 'Sundry Debtors'
        etree.SubElement(ledger, 'ISBILLWISEON').text = "Yes"
        
        address = etree.SubElement(ledger, 'ADDRESS.LIST', TYPE="String")
        etree.SubElement(address, 'ADDRESS').text = safe_str(row.get('Billing Street', ''))
        
        etree.SubElement(ledger, 'MAILINGNAME').text = customer_name
        etree.SubElement(ledger, 'STATE').text = safe_str(row.get('Billing State', ''))
        
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
        vendor_name = f"{safe_str(row['First Name'])} {safe_str(row['Last Name'])}".strip() or safe_str(row['Company Name'])
        
        # Skip rows where the name is blank
        if not vendor_name:
            continue

        # Populate the global map for later reference
        vendor_id = safe_str(row.get('Contact ID'))
        if vendor_id:
            VENDOR_ID_TO_NAME_MAP[vendor_id] = vendor_name

        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=vendor_name, ACTION="Create")
        etree.SubElement(ledger, 'NAME').text = vendor_name
        etree.SubElement(ledger, 'PARENT').text = 'Sundry Creditors'
        etree.SubElement(ledger, 'ISBILLWISEON').text = "Yes"
        
        address = etree.SubElement(ledger, 'ADDRESS.LIST', TYPE="String")
        etree.SubElement(address, 'ADDRESS').text = safe_str(row.get('Billing Street', ''))
        
        etree.SubElement(ledger, 'MAILINGNAME').text = vendor_name
        
        if 'Opening Balance' in df_cleaned.columns and pd.notna(row['Opening Balance']) and row['Opening Balance'] != 0:
            opening_balance = float(row['Opening Balance'])
            balance_text = f"{abs(opening_balance)} {'Cr' if opening_balance >= 0 else 'Dr'}"
            etree.SubElement(ledger, 'OPENINGBALANCE').text = balance_text

    return tally_message, None

def create_ledger_if_not_exists(tally_message, ledger_name, parent_group, known_ledgers_set):
    """Helper to add a ledger creation block to the XML if it's new."""
    if ledger_name and ledger_name not in known_ledgers_set:
        ledger = etree.SubElement(tally_message, 'LEDGER', NAME=ledger_name, ACTION="Create")
        etree.SubElement(ledger, 'PARENT').text = parent_group
        etree.SubElement(ledger, 'ISBILLWISEON').text = "Yes" if "Sundry" in parent_group else "No"
        known_ledgers_set.add(ledger_name)

def process_invoices(df):
    """Processes Invoice.csv to create Tally Sales Vouchers."""
    if df is None or df.empty: return None, "Invoices data is missing or empty."
    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Invoice Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    ledgers_in_this_file = set()
    create_ledger_if_not_exists(tally_message, "Sales", "Sales Accounts", ledgers_in_this_file)

    for _, row in df_cleaned.iterrows():
        customer_id = safe_str(row.get('Customer ID'))
        customer_name = CUSTOMER_ID_TO_NAME_MAP.get(customer_id, safe_str(row['Customer Name']))
        
        create_ledger_if_not_exists(tally_message, customer_name, "Sundry Debtors", ledgers_in_this_file)
            
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Sales", ACTION="Create")
        etree.SubElement(vch, 'DATE').text = safe_str(row['Invoice Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Invoice Number'])
        
        total_amount = float(row['Total'])
        debtor_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(debtor_ledger, 'LEDGERNAME').text = customer_name
        etree.SubElement(debtor_ledger, 'ISDEEMEDPOSITIVE').text = "Yes"
        etree.SubElement(debtor_ledger, 'AMOUNT').text = f"-{total_amount}"

        bill_alloc = etree.SubElement(debtor_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = safe_str(row['Invoice Number'])
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "New Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = f"-{total_amount}"

        sales_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(sales_ledger, 'LEDGERNAME').text = "Sales"
        etree.SubElement(sales_ledger, 'ISDEEMEDPOSITIVE').text = "No"
        etree.SubElement(sales_ledger, 'AMOUNT').text = f"{total_amount}"

    return tally_message, None

def process_customer_payments(df):
    """Processes Customer_Payment.csv to create Tally Receipt Vouchers."""
    if df is None or df.empty: return None, "Customer Payments data is missing or empty."
    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    ledgers_in_this_file = set()
    create_ledger_if_not_exists(tally_message, "Bank", "Bank Accounts", ledgers_in_this_file)

    for _, row in df_cleaned.iterrows():
        customer_id = safe_str(row.get('CustomerID'))
        customer_name = CUSTOMER_ID_TO_NAME_MAP.get(customer_id, safe_str(row['Customer Name']))

        create_ledger_if_not_exists(tally_message, customer_name, "Sundry Debtors", ledgers_in_this_file)
            
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Receipt", ACTION="Create")
        etree.SubElement(vch, 'DATE').text = safe_str(row['Date'])
        
        amount_received = float(row['Amount'])
        bank_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(bank_ledger, 'LEDGERNAME').text = "Bank"
        etree.SubElement(bank_ledger, 'ISDEEMEDPOSITIVE').text = "Yes"
        etree.SubElement(bank_ledger, 'AMOUNT').text = f"-{amount_received}"
        
        customer_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(customer_ledger, 'LEDGERNAME').text = customer_name
        etree.SubElement(customer_ledger, 'ISDEEMEDPOSITIVE').text = "No"
        etree.SubElement(customer_ledger, 'AMOUNT').text = str(amount_received)

        invoice_ref = safe_str(row.get('Invoice Number', row.get('Payment Number')))
        bill_alloc = etree.SubElement(customer_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = invoice_ref
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "Agst Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = str(amount_received)

    return tally_message, None

def process_bills(df):
    """Processes Bill.csv to create Tally Purchase Vouchers."""
    if df is None or df.empty: return None, "Bills (Purchases) data is missing or empty."
    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Bill Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    ledgers_in_this_file = set()
    create_ledger_if_not_exists(tally_message, "Purchase", "Purchase Accounts", ledgers_in_this_file)

    for _, row in df_cleaned.iterrows():
        vendor_name = safe_str(row['Vendor Name'])

        create_ledger_if_not_exists(tally_message, vendor_name, "Sundry Creditors", ledgers_in_this_file)
            
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Purchase", ACTION="Create")
        etree.SubElement(vch, 'DATE').text = safe_str(row['Bill Date'])
        etree.SubElement(vch, 'VOUCHERNUMBER').text = safe_str(row['Bill Number'])

        total_amount = float(row['Total'])
        vendor_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(vendor_ledger, 'LEDGERNAME').text = vendor_name
        etree.SubElement(vendor_ledger, 'ISDEEMEDPOSITIVE').text = "No"
        etree.SubElement(vendor_ledger, 'AMOUNT').text = str(total_amount)

        bill_alloc = etree.SubElement(vendor_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = safe_str(row['Bill Number'])
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "New Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = str(total_amount)

        purchase_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(purchase_ledger, 'LEDGERNAME').text = "Purchase"
        etree.SubElement(purchase_ledger, 'ISDEEMEDPOSITIVE').text = "Yes"
        etree.SubElement(purchase_ledger, 'AMOUNT').text = f"-{total_amount}"

    return tally_message, None

def process_vendor_payments(df):
    """Processes Vendor_Payment.csv to create Tally Payment Vouchers."""
    if df is None or df.empty: return None, "Vendor Payments data is missing or empty."
    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    ledgers_in_this_file = set()
    create_ledger_if_not_exists(tally_message, "Bank", "Bank Accounts", ledgers_in_this_file)

    for _, row in df_cleaned.iterrows():
        vendor_name = safe_str(row['Vendor Name'])
        
        create_ledger_if_not_exists(tally_message, vendor_name, "Sundry Creditors", ledgers_in_this_file)

        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Payment", ACTION="Create")
        etree.SubElement(vch, 'DATE').text = safe_str(row['Date'])
        
        amount_paid = float(row['Amount'])
        vendor_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(vendor_ledger, 'LEDGERNAME').text = vendor_name
        etree.SubElement(vendor_ledger, 'ISDEEMEDPOSITIVE').text = "Yes"
        etree.SubElement(vendor_ledger, 'AMOUNT').text = f"-{amount_paid}"

        bill_ref = safe_str(row.get('Bill Number', row.get('Payment Number'))) 
        bill_alloc = etree.SubElement(vendor_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = bill_ref
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "Agst Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = f"-{amount_paid}"
        
        bank_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(bank_ledger, 'LEDGERNAME').text = "Bank"
        etree.SubElement(bank_ledger, 'ISDEEMEDPOSITIVE').text = "No"
        etree.SubElement(bank_ledger, 'AMOUNT').text = str(amount_paid)

    return tally_message, None


def process_credit_notes(df):
    """Processes Credit_Note.csv to create Tally Credit Note Vouchers."""
    if df is None or df.empty: return None, "Credit Notes data is missing or empty."
    df_cleaned = df.copy()
    df_cleaned = format_date_column(df_cleaned, 'Credit Note Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    ledgers_in_this_file = set()
    create_ledger_if_not_exists(tally_message, "Sales", "Sales Accounts", ledgers_in_this_file)

    for _, row in df_cleaned.iterrows():
        customer_id = safe_str(row.get('Customer ID'))
        customer_name = CUSTOMER_ID_TO_NAME_MAP.get(customer_id, safe_str(row['Customer Name']))

        create_ledger_if_not_exists(tally_message, customer_name, "Sundry Debtors", ledgers_in_this_file)
            
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Credit Note", ACTION="Create")
        etree.SubElement(vch, 'DATE').text = safe_str(row['Credit Note Date'])
        
        total_amount = float(row['Total'])
        sales_return_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(sales_return_ledger, 'LEDGERNAME').text = "Sales" 
        etree.SubElement(sales_return_ledger, 'ISDEEMEDPOSITIVE').text = "Yes"
        etree.SubElement(sales_return_ledger, 'AMOUNT').text = f"-{total_amount}"
        
        customer_ledger = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
        etree.SubElement(customer_ledger, 'LEDGERNAME').text = customer_name
        etree.SubElement(customer_ledger, 'ISDEEMEDPOSITIVE').text = "No"
        etree.SubElement(customer_ledger, 'AMOUNT').text = str(total_amount)
        
        bill_alloc = etree.SubElement(customer_ledger, 'BILLALLOCATIONS.LIST')
        etree.SubElement(bill_alloc, 'NAME').text = safe_str(row['Credit Note Number'])
        etree.SubElement(bill_alloc, 'BILLTYPE').text = "Agst Ref"
        etree.SubElement(bill_alloc, 'AMOUNT').text = str(total_amount)

    return tally_message, None

def process_journals(df):
    """Processes Journal.csv to create Tally Journal Vouchers."""
    if df is None or df.empty: return None, "Journals data is missing or empty."

    df_cleaned = df.copy()
    df_cleaned['Debit'] = pd.to_numeric(df_cleaned['Debit'], errors='coerce').fillna(0)
    df_cleaned['Credit'] = pd.to_numeric(df_cleaned['Credit'], errors='coerce').fillna(0)
    df_cleaned = format_date_column(df_cleaned, 'Journal Date')

    tally_message = etree.Element('TALLYMESSAGE', xmlns_UDF="TallyUDF")
    ledgers_in_this_file = set()
    
    for journal_id, group in df_cleaned.groupby('Journal Number'):
        if group.empty: continue
        first_row = group.iloc[0]
        vch = etree.SubElement(tally_message, 'VOUCHER', VCHTYPE="Journal", ACTION="Create")
        etree.SubElement(vch, 'DATE').text = safe_str(first_row['Journal Date'])
        etree.SubElement(vch, 'NARRATION').text = safe_str(first_row['Notes'])

        for _, row in group.iterrows():
            account_name = safe_str(row['Account'])
            # Journals can have any ledger. Auto-create them under Suspense if they are new.
            create_ledger_if_not_exists(tally_message, account_name, "Suspense A/c", ledgers_in_this_file)

            if row['Debit'] > 0:
                ledger_entry = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
                etree.SubElement(ledger_entry, 'LEDGERNAME').text = account_name
                etree.SubElement(ledger_entry, 'ISDEEMEDPOSITIVE').text = "Yes"
                etree.SubElement(ledger_entry, 'AMOUNT').text = f"-{row['Debit']}"
            
            if row['Credit'] > 0:
                ledger_entry = etree.SubElement(vch, 'ALLLEDGERENTRIES.LIST')
                etree.SubElement(ledger_entry, 'LEDGERNAME').text = account_name
                etree.SubElement(ledger_entry, 'ISDEEMEDPOSITIVE').text = "No"
                etree.SubElement(ledger_entry, 'AMOUNT').text = str(row['Credit'])

    return tally_message, None

# --- Main Application Logic (Streamlit) ---

st.set_page_config(layout="wide", page_title="Zoho to Tally Migration Tool")
st.title("Zoho Books to Tally XML Migration Tool 🧾")
st.markdown("This tool converts a **Zoho Books backup ZIP file** into multiple **Tally-compatible XML files**.")

uploaded_zip = st.file_uploader("1. Upload your Zoho Books Backup ZIP file", type="zip")

if uploaded_zip is not None:
    st.success(f"✅ Successfully uploaded `{uploaded_zip.name}`.")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, uploaded_zip.name)
        with open(zip_path, "wb") as f:
            f.write(uploaded_zip.getbuffer())
        
        st.subheader("2. Reading CSV files from ZIP")
        raw_dfs = {}
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                root_folder = None
                files_to_search = ['Chart_of_Accounts.csv', 'Invoice.csv', 'Contacts.csv'] + ZOHO_CSVS
                for file_name_to_find in files_to_search:
                    for member_path in zf.namelist():
                        normalized_path = member_path.replace('\\', '/')
                        if normalized_path.endswith('/' + file_name_to_find):
                            root_folder = os.path.dirname(normalized_path) + '/'
                            break
                    if root_folder: break

                if root_folder is None: root_folder = "" # Assume files are at root if no folder found

                with st.spinner("Extracting and reading CSV files..."):
                    for file_name in ZOHO_CSVS:
                        try:
                            full_file_path_in_zip = root_folder + file_name
                            with zf.open(full_file_path_in_zip) as csv_file:
                                raw_dfs[file_name] = pd.read_csv(csv_file, low_memory=False)
                                st.write(f"  - Read `{file_name}` ({len(raw_dfs[file_name])} rows)")
                        except KeyError:
                            st.warning(f"  - ⚠️ `{file_name}` not found in the ZIP. It will be skipped.")
                            raw_dfs[file_name] = None
        except Exception as e:
            st.error(f"An unexpected error occurred during ZIP file processing: {e}")
            st.stop()

        st.subheader("3. Processing Data and Generating XML")
        processed_xmls = {}
        
        processing_pipeline = {
            "chart_of_accounts": ("Chart_of_Accounts.csv", process_chart_of_accounts),
            "items": ("Item.csv", process_items),
            "contacts": ("Contacts.csv", process_contacts),
            "vendors": ("Vendors.csv", process_vendors),
            "invoices": ("Invoice.csv", process_invoices),
            "customer_payments": ("Customer_Payment.csv", process_customer_payments),
            "bills": ("Bill.csv", process_bills),
            "vendor_payments": ("Vendor_Payment.csv", process_vendor_payments),
            "credit_notes": ("Credit_Note.csv", process_credit_notes),
            "journals": ("Journal.csv", process_journals),
        }

        with st.spinner("Converting data to Tally XML format..."):
            # Clear global maps at the start of each run
            CUSTOMER_ID_TO_NAME_MAP.clear()
            VENDOR_ID_TO_NAME_MAP.clear()
            for key, (csv_name, process_func) in processing_pipeline.items():
                st.write(f"Processing {key.replace('_', ' ').title()}...")
                df = raw_dfs.get(csv_name)
                if df is not None:
                    try:
                        xml_tree, error_msg = process_func(df)
                        if error_msg: st.warning(f"  - Skipped: {error_msg}")
                        elif xml_tree is not None:
                            processed_xmls[key] = xml_tree
                            st.write(f"  - ✅ Success")
                        else: st.write(f"  - ⚪️ No data to process.")
                    except Exception as e:
                        st.error(f"  - ❌ An error occurred during {key} processing: {e}")
                        import traceback
                        st.code(traceback.format_exc())
                else: st.write(f"  - ⚪️ Skipped (CSV not found).")

        st.subheader("4. Download Your Tally XML Files")
        st.markdown("""
        Import these files into your test Tally company **one by one, strictly in the numbered order they appear in the ZIP file.** This is crucial because vouchers (like invoices) depend on masters (like customers) already being present in Tally.

        **Recommended Import Order:**
        1.  `01_chart_of_accounts.xml` (Ledger Groups & Ledgers)
        2.  `02_items.xml` (Stock Items & **Units of Measure**)
        3.  `03_contacts.xml` (Customers / Sundry Debtors)
        4.  `04_vendors.xml` (Suppliers / Sundry Creditors)
        5.  All subsequent voucher files (`05_invoices.xml`, `06_customer_payments.xml`, etc.)
        """)

        output_zip_path = os.path.join(temp_dir, "tally_import_files.zip")
        with zipfile.ZipFile(output_zip_path, 'w') as zf:
            sorted_keys = sorted(processed_xmls.keys(), key=lambda x: list(processing_pipeline.keys()).index(x))
            
            for i, key in enumerate(sorted_keys):
                xml_tree = processed_xmls[key]
                envelope = etree.Element('ENVELOPE')
                header = etree.SubElement(envelope, 'HEADER')
                etree.SubElement(header, 'TALLYREQUEST').text = "Import Data"
                body = etree.SubElement(envelope, 'BODY')
                import_data = etree.SubElement(body, 'IMPORTDATA')
                req_desc = etree.SubElement(import_data, 'REQUESTDESC')
                report_name = "All Masters" if "chart" in key or "item" in key or "contact" in key or "vendor" in key else "Vouchers"
                etree.SubElement(req_desc, 'REPORTNAME').text = report_name
                static_vars = etree.SubElement(req_desc, 'STATICVARIABLES')
                etree.SubElement(static_vars, 'SVCURRENTCOMPANY').text = TALLY_COMPANY_NAME
                
                req_data = etree.SubElement(import_data, 'REQUESTDATA')
                req_data.append(xml_tree)
                
                xml_string = etree.tostring(envelope, pretty_print=True, xml_declaration=True, encoding='UTF-8')
                filename = f"{i+1:02d}_{key}.xml"
                zf.writestr(filename, xml_string)
        
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
1.  Go to `Gateway of Tally` > `Import Data` > `Masters` (for files 1-4) or `Vouchers` (for all other files).
2.  Select the XML file path. **Start with `01_chart_of_accounts.xml`.**
3.  Import each file **one at a time**. Do not proceed to the next file until the previous one has imported successfully.
4.  For masters, choose the 'Modify with new data' or 'Combine Opening Balances' behavior as needed.
""")
