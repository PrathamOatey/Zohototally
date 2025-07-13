import pandas as pd
import os
import numpy as np # For numerical operations, e.g., isnan

# --- Configuration ---
# Directory where the Zoho backup ZIP contents were extracted
EXTRACT_TO_DIR = "/mnt/data/zoho_extracted"

# Directory where cleaned and processed CSVs will be saved
PROCESSED_DATA_DIR = "processed_data"

# Define input CSVs (from 01_extract.py's analysis)
ZOHO_FILES = {
    'chart_of_accounts': 'Chart_of_Accounts.csv',
    'contacts': 'Contacts.csv',
    'vendors': 'Vendors.csv',
    'invoices': 'Invoice.csv',
    'customer_payments': 'Customer_Payment.csv',
    'vendor_payments': 'Vendor_Payment.csv',
    'credit_notes': 'Credit_Note.csv',
    'journals': 'Journal.csv',
    'bills': 'Bill.csv',
    'sales_orders': 'Sales_Order.csv', # Not processed in detail in initial financial focus
    'purchase_orders': 'Purchase_Order.csv', # Not processed in detail in initial financial focus
    'items': 'Item.csv', # Not processed in detail in initial financial focus
}

# --- Helper Functions ---

def load_csv(file_name):
    """
    Loads a CSV file into a pandas DataFrame.
    Includes robust error handling for file not found and parsing issues.
    """
    file_path = os.path.join(EXTRACT_TO_DIR, file_name)
    if not os.path.exists(file_path):
        print(f"❌ Error: Input file not found: {file_path}")
        return None
    try:
        # Use low_memory=False to avoid DtypeWarning for mixed types in columns
        # on_bad_lines='skip' to gracefully handle malformed rows
        df = pd.read_csv(file_path, encoding='utf-8', on_bad_lines='skip', low_memory=False)
        print(f"Loaded {file_name} with {len(df)} rows and {len(df.columns)} columns.")
        return df
    except Exception as e:
        print(f"❌ Error loading {file_name}: {e}")
        return None

def save_processed_csv(df, output_name):
    """
    Saves a processed DataFrame to the PROCESSED_DATA_DIR.
    Creates the directory if it doesn't exist.
    """
    if df is None:
        print(f"⚠️ Cannot save {output_name}: DataFrame is None.")
        return
    if not os.path.exists(PROCESSED_DATA_DIR):
        os.makedirs(PROCESSED_DATA_DIR)
        print(f"Created processed data directory: '{PROCESSED_DATA_DIR}'")
    output_path = os.path.join(PROCESSED_DATA_DIR, output_name)
    try:
        df.to_csv(output_path, index=False, encoding='utf-8')
        print(f"✅ Saved processed data to: {output_path}")
    except Exception as e:
        print(f"❌ Error saving {output_name} to {output_path}: {e}")

def format_date_column(df, column_name):
    """Converts a column to datetime objects and then formats as 'YYYY-MM-DD' string."""
    if column_name in df.columns and not df[column_name].empty:
        # Attempt to convert to datetime, coercing errors
        df[column_name] = pd.to_datetime(df[column_name], errors='coerce')
        # Format valid dates, set invalid/NaT dates to empty string
        df[column_name] = df[column_name].dt.strftime('%Y-%m-%d').fillna('')
    return df

def clean_numeric_column(df, column_name):
    """Converts a column to numeric, filling NaNs with 0.0."""
    if column_name in df.columns and not df[column_name].empty:
        df[column_name] = pd.to_numeric(df[column_name], errors='coerce').fillna(0.0)
    return df

# --- Data Cleaning and Mapping Functions ---

def process_chart_of_accounts(df):
    """
    Cleans and maps Zoho Chart of Accounts to Tally Ledgers/Groups.
    - Renames key columns for clarity.
    - Maps Zoho Account Types to common Tally Parent Groups.
    - Handles missing descriptions.
    """
    print("\n--- Processing Chart of Accounts ---")
    if df is None: return None

    # Define a robust mapping for Zoho Account Type to Tally Parent Groups.
    # THIS IS CRITICAL AND MUST BE CUSTOMIZED TO YOUR TALLY'S CHART OF ACCOUNTS.
    # Default Tally groups you might use: Capital Account, Current Assets, Current Liabilities,
    # Direct Expenses, Direct Incomes, Indirect Expenses, Indirect Incomes, Bank Accounts, Cash-in-Hand,
    # Loans (Liability), Loans & Advances (Asset), Fixed Assets, Duties & Taxes, Sundry Debtors, Sundry Creditors etc.
    account_type_map = {
        'Asset': 'Current Assets',
        'Bank': 'Bank Accounts',
        'Cash': 'Cash-in-Hand',
        'Expense': 'Indirect Expenses', # Often, Zoho expenses map to indirect
        'Cost of Goods Sold': 'Direct Expenses',
        'Equity': 'Capital Account',
        'Income': 'Indirect Incomes', # Often, Zoho incomes map to indirect
        'Other Income': 'Indirect Incomes',
        'Liability': 'Current Liabilities',
        'Other Current Asset': 'Current Assets',
        'Other Current Liability': 'Current Liabilities',
        'Account Receivable': 'Sundry Debtors', # Special handling for default Zoho types
        'Account Payable': 'Sundry Creditors',
        # Add more mappings based on your specific Zoho types and desired Tally groups
        'Fixed Asset': 'Fixed Assets',
        'Loan (Liability)': 'Loans (Liability)',
        'Other Asset': 'Current Assets',
        'Stock': 'Stock-in-Hand', # If you treat inventory as a ledger
        'Cess': 'Duties & Taxes',
        'TDS Receivable': 'Duties & Taxes',
        'TDS Payable': 'Duties & Taxes',
        'CGST': 'Duties & Taxes',
        'SGST': 'Duties & Taxes',
        'IGST': 'Duties & Taxes',
        'Service Tax': 'Duties & Taxes', # Old tax, but just in case
        'Professional Tax': 'Duties & Taxes',
        'TCS': 'Duties & Taxes',
        'Advance Tax': 'Duties & Taxes',
        'Secured Loan': 'Secured Loans',
        'Unsecured Loan': 'Unsecured Loans',
        'Provisions': 'Provisions',
        'Branch / Division': 'Branch / Divisions',
        # Fallback for types not explicitly mapped - adjust as needed
        'Statutory': 'Duties & Taxes',
        'Other Liability': 'Current Liabilities',
        'Retained Earnings': 'Reserves & Surplus',
        'Long Term Liability': 'Loans (Liability)',
        'Long Term Asset': 'Fixed Assets',
        'Loan & Advance (Asset)': 'Loans & Advances (Asset)',
        'Stock Adjustment Account': 'Direct Expenses', # Or specific stock adjustment group
        'Uncategorized': 'Suspense A/c'
    }

    # Apply the mapping, defaulting to 'Primary' or a 'Suspense A/c' if not found
    df['Tally_Parent_Group'] = df['Account Type'].astype(str).apply(lambda x: account_type_map.get(x, 'Suspense A/c'))

    # Rename columns for easier Tally mapping later
    df_mapped = df.rename(columns={
        'Account Name': 'Tally_Ledger_Name',
        'Account Code': 'Tally_Account_Code',
        'Description': 'Tally_Description',
        'Account Status': 'Tally_Status', # Active/Inactive
    })

    # Fill missing values for string columns
    df_mapped['Tally_Description'] = df_mapped['Tally_Description'].fillna('')
    df_mapped['Tally_Account_Code'] = df_mapped['Tally_Account_Code'].fillna('')
    df_mapped['Parent Account'] = df_mapped['Parent Account'].fillna('') # Zoho's parent account, might not directly map to Tally parent groups

    # Select relevant columns for output
    df_processed = df_mapped[[
        'Account ID',
        'Tally_Ledger_Name',
        'Tally_Account_Code',
        'Tally_Description',
        'Account Type', # Keep original Zoho type for reference
        'Tally_Parent_Group', # The mapped Tally parent group
        'Tally_Status',
        'Currency',
        'Parent Account' # Original Zoho parent
    ]].copy()

    print(f"Processed {len(df_processed)} Chart of Accounts entries.")
    return df_processed

def process_contacts(df):
    """
    Cleans and maps Zoho Contacts to Tally Sundry Debtors.
    - Combines name fields.
    - Cleans address, phone, email, GSTIN.
    - Formats date fields.
    """
    print("\n--- Processing Contacts ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Last Modified Time')

    # Fill NaN/None with empty strings for text fields that will go into XML
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

    # Clean numeric columns
    numeric_cols = ['Credit Limit', 'Opening Balance', 'Opening Balance Exchange Rate', 'Tax Percentage']
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    # Create a unified address block for Tally (consider multiline addresses)
    # Tally has separate fields for address lines, city, state, country, pincode.
    df_cleaned['Tally_Billing_Address_Line1'] = df_cleaned['Billing Address'].fillna('')
    df_cleaned['Tally_Billing_Address_Line2'] = df_cleaned['Billing Street2'].fillna('')
    df_cleaned['Tally_Shipping_Address_Line1'] = df_cleaned['Shipping Address'].fillna('')
    df_cleaned['Tally_Shipping_Address_Line2'] = df_cleaned['Shipping Street2'].fillna('')

    # Map Zoho State to Tally-compatible State Name (if different)
    # This might require a separate CSV mapping for state codes/names
    # For now, just use Zoho's state name
    df_cleaned['Tally_Billing_State'] = df_cleaned['Billing State']
    df_cleaned['Tally_Shipping_State'] = df_cleaned['Shipping State']

    # Rename Display Name for clarity as it typically becomes the Ledger Name
    df_processed = df_cleaned.rename(columns={
        'Display Name': 'Tally_Party_Name',
        'GST Identification Number (GSTIN)': 'Tally_GSTIN',
        'EmailID': 'Tally_Email',
        'Phone': 'Tally_Phone',
        'MobilePhone': 'Tally_Mobile',
        'Credit Limit': 'Tally_Credit_Limit',
        'Place of Contact(With State Code)': 'Tally_Place_of_Supply_Code' # For GST implications
    })

    # Filter out essential columns for the output
    df_final = df_processed[[
        'Contact ID',
        'Tally_Party_Name',
        'Company Name',
        'Tally_Email',
        'Tally_Phone',
        'Tally_Mobile',
        'Tally_GSTIN',
        'Tally_Billing_Address_Line1',
        'Tally_Billing_Address_Line2',
        'Billing City',
        'Tally_Billing_State',
        'Billing Country',
        'Billing Code',
        'Tally_Shipping_Address_Line1',
        'Tally_Shipping_Address_Line2',
        'Shipping City',
        'Tally_Shipping_State',
        'Shipping Country',
        'Shipping Code',
        'Tally_Credit_Limit',
        'Opening Balance', # For potential opening balance migration
        'Status', # Active/Inactive
        'Tally_Place_of_Supply_Code',
        'GST Treatment'
    ]].copy()

    print(f"Processed {len(df_final)} Contacts entries.")
    return df_final

def process_vendors(df):
    """
    Cleans and maps Zoho Vendors to Tally Sundry Creditors.
    Similar logic to contacts.
    """
    print("\n--- Processing Vendors ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Last Modified Time')

    # Fill NaN/None with empty strings for text fields
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

    # Clean numeric columns
    numeric_cols = ['Opening Balance', 'TDS Percentage', 'Exchange Rate']
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    # Create unified address blocks
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
        'Vendor Bank Code': 'Tally_IFSC_Code' # Assuming Bank Code is IFSC for Tally
    })

    df_final = df_processed[[
        'Contact ID',
        'Tally_Party_Name',
        'Company Name',
        'Tally_Email',
        'Tally_Phone',
        'Tally_Mobile',
        'Tally_GSTIN',
        'Tally_Billing_Address_Line1',
        'Tally_Billing_Address_Line2',
        'Billing City',
        'Tally_Billing_State',
        'Billing Country',
        'Billing Code',
        'Tally_Shipping_Address_Line1',
        'Tally_Shipping_Address_Line2',
        'Shipping City',
        'Tally_Shipping_State',
        'Shipping Country',
        'Shipping Code',
        'Opening Balance',
        'Status',
        'GST Treatment',
        'Tally_Bank_Account_No',
        'Tally_Bank_Name',
        'Tally_IFSC_Code'
    ]].copy()

    print(f"Processed {len(df_final)} Vendors entries.")
    return df_final


def process_invoices(df):
    """
    Cleans and maps Zoho Invoices to Tally Sales Vouchers.
    This CSV often has item details flattened into a single row per invoice, or multiple rows if there are many items.
    The goal here is to prepare data for easy grouping in the XML generation script.
    - Formats dates.
    - Cleans numeric amounts.
    - Handles item-level details (assuming they are present per row for simplicity).
    """
    print("\n--- Processing Invoices ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Invoice Date')
    df_cleaned = format_date_column(df_cleaned, 'Due Date')
    df_cleaned = format_date_column(df_cleaned, 'Expected Payment Date')
    df_cleaned = format_date_column(df_cleaned, 'Last Payment Date')

    # Clean numeric columns (amounts, quantities, rates, percentages)
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

    # Fill NaN/None with empty strings for text fields
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

    # Map Tally Ledger Names for sales/purchase/tax accounts
    # This is a critical mapping that might need a separate configuration file
    df_cleaned['Tally_Sales_Ledger_Name'] = df_cleaned['Account'].fillna('Sales Account') # Default Sales Ledger
    df_cleaned['Tally_Output_CGST_Ledger'] = 'Output CGST' # Customize to your Tally ledger names
    df_cleaned['Tally_Output_SGST_Ledger'] = 'Output SGST'
    df_cleaned['Tally_Output_IGST_Ledger'] = 'Output IGST'
    df_cleaned['Tally_Round_Off_Ledger'] = 'Round Off' # Create this if it doesn't exist

    # Ensure Customer ID is consistent
    df_cleaned['Customer ID'] = df_cleaned['Customer ID'].fillna('').astype(str)

    df_processed = df_cleaned.copy()
    print(f"Processed {len(df_processed)} Invoices entries (including line items).")
    return df_processed

def process_customer_payments(df):
    """
    Cleans and maps Zoho Customer Payments to Tally Receipt Vouchers.
    - Formats dates.
    - Cleans numeric amounts.
    - Identifies deposit account (Cash/Bank).
    - Links to invoices where possible.
    """
    print("\n--- Processing Customer Payments ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Date')
    df_cleaned = format_date_column(df_cleaned, 'Created Time')
    df_cleaned = format_date_column(df_cleaned, 'Invoice Date')
    df_cleaned = format_date_column(df_cleaned, 'Invoice Payment Applied Date')

    # Clean numeric columns
    numeric_cols = [
        'Amount', 'Unused Amount', 'Bank Charges', 'Exchange Rate',
        'Tax Percentage', 'Amount Applied to Invoice', 'Withholding Tax Amount'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    # Fill NaN/None with empty strings for text fields
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

    # Map Zoho's 'Deposit To' to actual Tally Bank/Cash Ledger Names
    df_cleaned['Tally_Deposit_Ledger'] = df_cleaned['Deposit To'].apply(
        lambda x: x if x else 'Cash-in-Hand' # Use Zoho's 'Deposit To' if available, else default
    )
    # Ensure CustomerID is consistent
    df_cleaned['CustomerID'] = df_cleaned['CustomerID'].fillna('').astype(str)

    df_processed = df_cleaned.copy()
    print(f"Processed {len(df_processed)} Customer Payments entries.")
    return df_processed

def process_vendor_payments(df):
    """
    Cleans and maps Zoho Vendor Payments to Tally Payment Vouchers.
    Similar logic to customer payments.
    """
    print("\n--- Processing Vendor Payments ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Date')
    df_cleaned = format_date_column(df_cleaned, 'Bill Date')
    df_cleaned = format_date_column(df_cleaned, 'Bill Payment Applied Date')

    # Clean numeric columns
    numeric_cols = [
        'Amount', 'Unused Amount', 'TDSAmount', 'Exchange Rate', 'ReverseCharge Tax Percentage',
        'ReverseCharge Tax Amount', 'TDS Percentage', 'Bill Amount', 'Withholding Tax Amount',
        'Withholding Tax Amount (BCY)'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    # Fill NaN/None with empty strings for text fields
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
        'Bank Reference Number', 'Bill Number'
    ]
    for col in string_cols:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].fillna('').astype(str)

    # Map Zoho's 'Paid Through' to actual Tally Bank/Cash Ledger Names
    df_cleaned['Tally_Paid_Through_Ledger'] = df_cleaned['Paid Through'].apply(
        lambda x: x if x else 'Cash-in-Hand'
    )
    df_processed = df_cleaned.copy()
    print(f"Processed {len(df_processed)} Vendor Payments entries.")
    return df_processed

def process_credit_notes(df):
    """
    Cleans and maps Zoho Credit Notes to Tally Credit Note Vouchers.
    Handles item-level details and linking to original invoices.
    """
    print("\n--- Processing Credit Notes ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Credit Note Date')
    df_cleaned = format_date_column(df_cleaned, 'Associated Invoice Date')

    # Clean numeric columns
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

    # Fill NaN/None with empty strings for text fields
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

    # Map Tally Ledger Names for sales returns/tax accounts
    df_cleaned['Tally_Sales_Return_Ledger'] = df_cleaned['Account'].fillna('Sales Returns') # Default Sales Return Ledger
    df_cleaned['Tally_Output_CGST_Ledger'] = 'Output CGST' # Customize to your Tally ledger names
    df_cleaned['Tally_Output_SGST_Ledger'] = 'Output SGST'
    df_cleaned['Tally_Output_IGST_Ledger'] = 'Output IGST'

    # Ensure Customer ID is consistent
    df_cleaned['Customer ID'] = df_cleaned['Customer ID'].fillna('').astype(str)

    df_processed = df_cleaned.copy()
    print(f"Processed {len(df_processed)} Credit Notes entries.")
    return df_processed

def process_journals(df):
    """
    Cleans and maps Zoho Journals to Tally Journal Vouchers.
    Important: Zoho Journal CSVs often list debit and credit as separate rows.
    You might need to group them by 'Journal Number' to form a single Tally Journal Voucher.
    This function will primarily clean, and the grouping will be done in XML generation.
    """
    print("\n--- Processing Journals ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Journal Date')

    # Clean numeric columns
    numeric_cols = [
        'Exchange Rate', 'Tax Percentage', 'Tax Amount', 'Debit', 'Credit', 'Total'
    ]
    for col in numeric_cols:
        if col in df_cleaned.columns:
            df_cleaned = clean_numeric_column(df_cleaned, col)

    # Fill NaN/None with empty strings for text fields
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

    # The Zoho Journal CSV can sometimes list multiple debit/credit lines for one journal.
    # We'll rely on the 'Journal Number' to group them in the XML generation step.
    df_processed = df_cleaned.copy()
    print(f"Processed {len(df_processed)} Journal entries.")
    return df_processed

def process_bills(df):
    """
    Cleans and maps Zoho Bills to Tally Purchase Vouchers.
    Similar to invoices, prepares data for potential line item processing in XML generation.
    """
    print("\n--- Processing Bills ---")
    if df is None: return None

    df_cleaned = df.copy()

    # Format date columns
    df_cleaned = format_date_column(df_cleaned, 'Bill Date')
    df_cleaned = format_date_column(df_cleaned, 'Due Date')
    df_cleaned = format_date_column(df_cleaned, 'Submitted Date')
    df_cleaned = format_date_column(df_cleaned, 'Approved Date')

    # Clean numeric columns
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

    # Fill NaN/None with empty strings for text fields
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

    # Map Tally Ledger Names for purchase/tax accounts
    df_cleaned['Tally_Purchase_Ledger_Name'] = df_cleaned['Account'].fillna('Purchase Account') # Default Purchase Ledger
    df_cleaned['Tally_Input_CGST_Ledger'] = 'Input CGST' # Customize to your Tally ledger names
    df_cleaned['Tally_Input_SGST_Ledger'] = 'Input SGST'
    df_cleaned['Tally_Input_IGST_Ledger'] = 'Input IGST'
    df_cleaned['Tally_Round_Off_Ledger'] = 'Round Off' # Create this if it doesn't exist

    df_processed = df_cleaned.copy()
    print(f"Processed {len(df_processed)} Bills entries.")
    return df_processed

# --- Placeholder functions for modules not in initial financial focus ---
def process_sales_orders(df):
    print("\n--- Skipping Sales Orders processing for now (Financials priority) ---")
    return None

def process_purchase_orders(df):
    print("\n--- Skipping Purchase Orders processing for now (Financials priority) ---")
    return None

def process_items(df):
    print("\n--- Skipping Items processing for now (Financials priority) ---")
    return None

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Starting 02_clean_map.py: Data Cleaning and Mapping ---")

    # Ensure output directory exists
    if not os.path.exists(PROCESSED_DATA_DIR):
        os.makedirs(PROCESSED_DATA_DIR)

    # --- Load and Process each file ---
    # Chart of Accounts
    coa_df = load_csv(ZOHO_FILES['chart_of_accounts'])
    processed_coa_df = process_chart_of_accounts(coa_df)
    save_processed_csv(processed_coa_df, 'cleaned_chart_of_accounts.csv')

    # Contacts
    contacts_df = load_csv(ZOHO_FILES['contacts'])
    processed_contacts_df = process_contacts(contacts_df)
    save_processed_csv(processed_contacts_df, 'cleaned_contacts.csv')

    # Vendors
    vendors_df = load_csv(ZOHO_FILES['vendors'])
    processed_vendors_df = process_vendors(vendors_df)
    save_processed_csv(processed_vendors_df, 'cleaned_vendors.csv')

    # Invoices (complex - will likely need item-level processing in XML gen)
    invoices_df = load_csv(ZOHO_FILES['invoices'])
    processed_invoices_df = process_invoices(invoices_df)
    save_processed_csv(processed_invoices_df, 'cleaned_invoices.csv')

    # Customer Payments
    customer_payments_df = load_csv(ZOHO_FILES['customer_payments'])
    processed_customer_payments_df = process_customer_payments(customer_payments_df)
    save_processed_csv(processed_customer_payments_df, 'cleaned_customer_payments.csv')

    # Vendor Payments
    vendor_payments_df = load_csv(ZOHO_FILES['vendor_payments'])
    processed_vendor_payments_df = process_vendor_payments(vendor_payments_df)
    save_processed_csv(processed_vendor_payments_df, 'cleaned_vendor_payments.csv')

    # Credit Notes
    credit_notes_df = load_csv(ZOHO_FILES['credit_notes'])
    processed_credit_notes_df = process_credit_notes(credit_notes_df)
    save_processed_csv(processed_credit_notes_df, 'cleaned_credit_notes.csv')

    # Journals
    journals_df = load_csv(ZOHO_FILES['journals'])
    processed_journals_df = process_journals(journals_df)
    save_processed_csv(processed_journals_df, 'cleaned_journals.csv')

    # Bills
    bills_df = load_csv(ZOHO_FILES['bills'])
    processed_bills_df = process_bills(bills_df)
    save_processed_csv(processed_bills_df, 'cleaned_bills.csv')

    # Placeholder calls for other modules (not generating processed CSVs for now)
    process_sales_orders(load_csv(ZOHO_FILES['sales_orders']))
    process_purchase_orders(load_csv(ZOHO_FILES['purchase_orders']))
    process_items(load_csv(ZOHO_FILES['items']))


    print("\n--- 02_clean_map.py: Data cleaning and mapping complete. ---")
    print(f"Check the '{PROCESSED_DATA_DIR}' directory for cleaned CSV files.")
    print("Review these CSVs to ensure data accuracy and correct mappings.")
    print("Next, proceed to generate Tally XML using '03_generate_tally_xml.py'.")