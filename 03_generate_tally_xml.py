import pandas as pd
from lxml import etree
import os
from datetime import datetime
import math # For math.isnan

# --- Configuration ---
PROCESSED_DATA_DIR = "processed_data"
OUTPUT_XML_DIR = "output"

# Company details (YOU MUST UPDATE THESE TO MATCH YOUR TALLY COMPANY EXACTLY)
TALLY_COMPANY_NAME = "Plant Essentials Private Limited" # Ensure this matches your Tally company
BASE_CURRENCY_SYMBOL = "₹"
BASE_CURRENCY_NAME = "Rupees"
DEFAULT_COUNTRY = "India" # Assuming default country for addresses

# --- Helper Functions ---

def load_processed_csv(file_name):
    """
    Loads a processed CSV file from the PROCESSED_DATA_DIR.
    Returns None if the file is not found, with an informative message.
    """
    file_path = os.path.join(PROCESSED_DATA_DIR, file_name)
    if not os.path.exists(file_path):
        print(f"❌ Error: Processed file not found: {file_path}. Please ensure '02_clean_map.py' was run successfully.")
        return None
    try:
        df = pd.read_csv(file_path, encoding='utf-8', low_memory=False)
        print(f"Loaded processed {file_name} with {len(df)} rows.")
        return df
    except Exception as e:
        print(f"❌ Error loading processed {file_name}: {e}")
        return None

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

def append_to_tally_message(tally_message, element):
    """Appends an element to the TallyMessage."""
    tally_message.append(element)

def write_xml_to_file(envelope, file_name):
    """Writes the generated XML to a file."""
    if not os.path.exists(OUTPUT_XML_DIR):
        os.makedirs(OUTPUT_XML_DIR)
    file_path = os.path.join(OUTPUT_XML_DIR, file_name)
    tree = etree.ElementTree(envelope)
    try:
        # Use a more Tally-friendly XML declaration and pretty_print for readability
        tree.write(file_path, pretty_print=True, encoding='utf-8', xml_declaration=True, standalone=True)
        print(f"✅ Generated Tally XML: {file_path}")
    except Exception as e:
        print(f"❌ Error writing XML to {file_path}: {e}")

def safe_str(value):
    """Converts a value to string, handling NaN/None gracefully."""
    if pd.isna(value):
        return ""
    return str(value).strip()

def format_tally_date(date_str):
    """Converts 'YYYY-MM-DD' string to Tally's 'YYYYMMDD' format."""
    if not date_str:
        return ""
    try:
        # Assuming date_str is already in 'YYYY-MM-DD' from 02_clean_map.py
        dt_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return dt_obj.strftime('%Y%m%d')
    except ValueError:
        print(f"⚠️ Invalid date format encountered: {date_str}. Returning empty string.")
        return ""

def format_tally_amount(amount):
    """Formats a numeric amount for Tally, handling NaN."""
    if pd.isna(amount):
        return "0.00"
    return f"{amount:.2f}" # Format to 2 decimal places

# --- XML Generation Functions ---

def generate_ledgers_xml(df_coa):
    """Generates Tally XML for Ledgers and Groups."""
    print("\n--- Generating Ledgers XML ---")
    if df_coa is None: return

    envelope, tally_message = create_tally_envelope("All Masters", "ACCOUNTS")

    # First, create/alter Tally Groups based on the mapped parent groups
    # This ensures parent groups exist before ledgers are created under them
    tally_groups_to_create = df_coa['Tally_Parent_Group'].unique().tolist()
    for group_name in sorted(tally_groups_to_create): # Sort for consistent XML output
        if not group_name or group_name == 'Suspense A/c': # Avoid creating blank or default Tally groups if not needed
            continue

        # Check if it's a known top-level Tally group; if not, set its parent to Primary
        # This is a simplification; you might need a more complex hierarchy.
        known_tally_primary_groups = [
            'Capital Account', 'Loans (Liability)', 'Fixed Assets', 'Investments',
            'Current Assets', 'Current Liabilities', 'Suspense A/c',
            'Sales Accounts', 'Purchase Accounts', 'Direct Incomes', 'Direct Expenses',
            'Indirect Incomes', 'Indirect Expenses', 'Bank Accounts', 'Cash-in-Hand',
            'Duties & Taxes', 'Stock-in-Hand', 'Branch / Divisions', 'Reserves & Surplus',
            'Secured Loans', 'Unsecured Loans', 'Provisions', 'Loans & Advances (Asset)'
        ]
        parent_group_for_new_group = "Primary" if group_name not in known_tally_primary_groups else "" # Blank parent for top-level

        group_xml = etree.SubElement(tally_message, "GROUP", NAME=group_name, ACTION="CREATE")
        etree.SubElement(group_xml, "NAME").text = group_name
        if parent_group_for_new_group:
            etree.SubElement(group_xml, "PARENT").text = parent_group_for_new_group
        etree.SubElement(group_xml, "ISADDABLE").text = "Yes" # Allow adding ledgers
        # Add a placeholder for Language name, required by Tally
        etree.SubElement(group_xml, "LANGUAGENAME.LIST").append(
            etree.fromstring(f"<NAME.LIST><NAME>{group_name}</NAME></NAME.LIST>")
        )

    # Now, add Ledgers
    for index, row in df_coa.iterrows():
        ledger_name = safe_str(row['Tally_Ledger_Name'])
        if not ledger_name:
            print(f"⚠️ Skipping ledger due to empty name: Row {index+2}") # +2 for header and 0-index
            continue

        parent_group = safe_str(row['Tally_Parent_Group'])
        # Fallback to a default if mapped parent group is empty or invalid
        if not parent_group:
            print(f"⚠️ Ledger '{ledger_name}' has no mapped parent group. Assigning to 'Suspense A/c'.")
            parent_group = 'Suspense A/c'

        ledger_xml = etree.SubElement(tally_message, "LEDGER", NAME=ledger_name, ACTION="CREATE")
        etree.SubElement(ledger_xml, "NAME").text = ledger_name
        etree.SubElement(ledger_xml, "PARENT").text = parent_group
        etree.SubElement(ledger_xml, "OPENINGBALANCE").text = format_tally_amount(row.get('Opening Balance', 0.0)) # Use Zoho's opening balance if available in COA CSV
        etree.SubElement(ledger_xml, "CURRENCYID").text = BASE_CURRENCY_NAME # Default to base currency

        # Basic properties based on Account Type from Zoho
        if row['Account Type'] == 'Bank':
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "No" # Banks usually not bill-wise
            etree.SubElement(ledger_xml, "ISCASHLEDGER").text = "No"
            etree.SubElement(ledger_xml, "ISBANKLEDGER").text = "Yes"
        elif row['Account Type'] == 'Cash':
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "No"
            etree.SubElement(ledger_xml, "ISCASHLEDGER").text = "Yes"
            etree.SubElement(ledger_xml, "ISBANKLEDGER").text = "No"
        elif row['Tally_Parent_Group'] in ['Sundry Debtors', 'Sundry Creditors']:
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "Yes" # Crucial for bill-wise accounting
            etree.SubElement(ledger_xml, "ISCOSTCENTRESON").text = "No"

        # Description
        description = safe_str(row.get('Tally_Description'))
        if description:
            etree.SubElement(ledger_xml, "DESCRIPTION").text = description

        # Required for Tally for display
        etree.SubElement(ledger_xml, "LANGUAGENAME.LIST").append(
            etree.fromstring(f"<NAME.LIST><NAME>{ledger_name}</NAME></NAME.LIST>")
        )

    write_xml_to_file(envelope, "tally_ledgers.xml")


def generate_contacts_vendors_xml(df_contacts, df_vendors):
    """Generates Tally XML for Sundry Debtors and Creditors (Parties)."""
    print("\n--- Generating Contacts and Vendors XML ---")

    # Both contacts and vendors are ledgers in Tally, so we use the same envelope
    envelope, tally_message = create_tally_envelope("All Masters", "ACCOUNTS")

    # Helper for adding address details
    def add_address_details(parent_element, row, is_shipping=False):
        prefix = "Shipping" if is_shipping else "Billing"
        address1 = safe_str(row.get(f'Tally_{prefix}_Address_Line1'))
        address2 = safe_str(row.get(f'Tally_{prefix}_Address_Line2'))
        city = safe_str(row.get(f'{prefix} City'))
        state = safe_str(row.get(f'Tally_{prefix}_State'))
        country = safe_str(row.get(f'{prefix} Country')) or DEFAULT_COUNTRY
        pincode = safe_str(row.get(f'{prefix} Code'))

        if address1 or address2 or city or state or country or pincode:
            address_list = etree.SubElement(parent_element, "ADDRESS.LIST")
            if address1:
                etree.SubElement(address_list, "ADDRESS").text = address1
            if address2:
                etree.SubElement(address_list, "ADDRESS").text = address2
            if city:
                etree.SubElement(parent_element, "CITY").text = city
            if state:
                etree.SubElement(parent_element, "STATENAME").text = state
            if country:
                etree.SubElement(parent_element, "COUNTRYNAME").text = country
            if pincode:
                etree.SubElement(parent_element, "PINCODE").text = pincode

    # Process Contacts (Sundry Debtors)
    if df_contacts is not None:
        for index, row in df_contacts.iterrows():
            party_name = safe_str(row['Tally_Party_Name'])
            if not party_name:
                print(f"⚠️ Skipping contact due to empty name: Row {index+2}")
                continue

            ledger_xml = etree.SubElement(tally_message, "LEDGER", NAME=party_name, ACTION="CREATE")
            etree.SubElement(ledger_xml, "NAME").text = party_name
            etree.SubElement(ledger_xml, "PARENT").text = "Sundry Debtors" # Fixed parent group for customers
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "Yes" # Crucial for bill-wise accounting
            etree.SubElement(ledger_xml, "OPENINGBALANCE").text = format_tally_amount(row.get('Opening Balance', 0.0))

            add_address_details(ledger_xml, row, is_shipping=False) # Billing address for ledger
            # Shipping address can be added via secondary address field if Tally supports or in voucher level.
            # For simplicity, main ledger address uses billing.

            phone = safe_str(row.get('Tally_Phone'))
            mobile = safe_str(row.get('Tally_Mobile'))
            email = safe_str(row.get('Tally_Email'))

            if phone: etree.SubElement(ledger_xml, "PHONENUMBER").text = phone
            if mobile: etree.SubElement(ledger_xml, "MOBILENUMBER").text = mobile
            if email: etree.SubElement(ledger_xml, "EMAIL").text = email

            gstin = safe_str(row.get('Tally_GSTIN'))
            gst_treatment = safe_str(row.get('GST Treatment')) # e.g., 'Regular', 'Consumer', 'Unregistered'
            place_of_supply_code = safe_str(row.get('Tally_Place_of_Supply_Code'))

            if gstin:
                etree.SubElement(ledger_xml, "HASGSTIN").text = "Yes"
                etree.SubElement(ledger_xml, "GSTREGISTRATIONTYPE").text = gst_treatment if gst_treatment in ['Regular', 'Consumer', 'Unregistered', 'Composition', 'SEZ'] else "Regular"
                etree.SubElement(ledger_xml, "GSTIN").text = gstin
                if place_of_supply_code:
                    etree.SubElement(ledger_xml, "PLACEOFSUPPLY").text = place_of_supply_code.split('-')[0].strip() # Assuming format '07-Maharashtra'

            etree.SubElement(ledger_xml, "LANGUAGENAME.LIST").append(
                etree.fromstring(f"<NAME.LIST><NAME>{party_name}</NAME></NAME.LIST>")
            )

    # Process Vendors (Sundry Creditors)
    if df_vendors is not None:
        for index, row in df_vendors.iterrows():
            party_name = safe_str(row['Tally_Party_Name'])
            if not party_name:
                print(f"⚠️ Skipping vendor due to empty name: Row {index+2}")
                continue

            ledger_xml = etree.SubElement(tally_message, "LEDGER", NAME=party_name, ACTION="CREATE")
            etree.SubElement(ledger_xml, "NAME").text = party_name
            etree.SubElement(ledger_xml, "PARENT").text = "Sundry Creditors" # Fixed parent group for vendors
            etree.SubElement(ledger_xml, "ISBILLWISEON").text = "Yes"
            etree.SubElement(ledger_xml, "OPENINGBALANCE").text = format_tally_amount(row.get('Opening Balance', 0.0))

            add_address_details(ledger_xml, row, is_shipping=False)

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

            # Bank details for vendors (optional, but good to include if available)
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
                etree.fromstring(f"<NAME.LIST><NAME>{party_name}</NAME></NAME.LIST>")
            )

    write_xml_to_file(envelope, "tally_contacts_vendors.xml")


def generate_sales_vouchers_xml(df_invoices):
    """Generates Tally XML for Sales Vouchers from Invoices."""
    print("\n--- Generating Sales Vouchers XML ---")
    if df_invoices is None: return

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    # Tally needs one VOUCHER element per invoice.
    # Group by 'Invoice ID' to handle multiple line items per invoice.
    # The 'Item Name', 'Quantity', 'Item Price', etc. are assumed to be on individual rows
    # within the group, or the main row itself if there's only one item.
    df_invoices['Total'] = pd.to_numeric(df_invoices['Total'], errors='coerce').fillna(0) # Ensure Total is numeric

    grouped_invoices = df_invoices.groupby('Invoice ID')

    for invoice_id, group in grouped_invoices:
        # Take the first row for header details (assuming consistent header info across item rows)
        header = group.iloc[0]

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(header['Invoice ID']),
                                   VCHTYPE="Sales",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header['Invoice Date'])
        etree.SubElement(voucher, "GUID").text = f"SAL-{safe_str(header['Invoice ID'])}" # Unique GUID
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Sales"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(header['Invoice Number'])
        etree.SubElement(voucher, "PARTYLEDGERNAME").text = safe_str(header['Customer Name'])
        etree.SubElement(voucher, "CSTFORMISSUETYPE").text = "" # If C-Form/F-Form etc. used
        etree.SubElement(voucher, "CSTFORMRECVTYPE").text = ""
        etree.SubElement(voucher, "BASICBUYERNAME").text = safe_str(header['Customer Name'])
        etree.SubElement(voucher, "PERSISTEDVIEW").text = "Accounting Voucher" # Standard view for non-inventory
        etree.SubElement(voucher, "PLACEOFSUPPLY").text = safe_str(header.get('Place of Supply(With State Code)', '')).split('-')[0].strip() # E.g., '27' for Maharashtra

        # Buyer details for GST
        buyer_details = etree.SubElement(voucher, "BUYERDETAILS.LIST")
        etree.SubElement(buyer_details, "CONSNAME").text = safe_str(header['Customer Name'])
        # Concatenate address lines for Tally if multiple.
        cons_address_list = etree.SubElement(buyer_details, "ADDRESS.LIST")
        if safe_str(header.get('Shipping Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Address'))
            if safe_str(header.get('Shipping Street2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Street2'))
        elif safe_str(header.get('Billing Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Address'))
            if safe_str(header.get('Billing Street2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Street2'))
        
        etree.SubElement(buyer_details, "STATENAME").text = safe_str(header.get('Shipping State', '') or header.get('Billing State', '') or '')
        etree.SubElement(buyer_details, "COUNTRYNAME").text = safe_str(header.get('Shipping Country', '') or header.get('Billing Country', '') or DEFAULT_COUNTRY)
        
        gstin = safe_str(header.get('GST Identification Number (GSTIN)'))
        if gstin:
            etree.SubElement(buyer_details, "GSTREGISTRATIONTYPE").text = safe_str(header.get('GST Treatment', 'Regular'))
            etree.SubElement(buyer_details, "GSTIN").text = gstin
        
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header['Invoice Date'])
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Notes', ''))
        
        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Credit the Party Ledger (Customer)
        party_ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(party_ledger_entry, "LEDGERNAME").text = safe_str(header['Customer Name'])
        etree.SubElement(party_ledger_entry, "ISDEEMEDPOSITIVE").text = "No" # Credit
        etree.SubElement(party_ledger_entry, "AMOUNT").text = format_tally_amount(-header['Total']) # Total invoice amount, as credit
        
        # Bill-wise details
        bill_allocation_list = etree.SubElement(party_ledger_entry, "BILLALLOCATIONS.LIST")
        bill_allocation = etree.SubElement(bill_allocation_list, "BILLALLOCATIONS")
        etree.SubElement(bill_allocation, "NAME").text = safe_str(header['Invoice Number'])
        etree.SubElement(bill_allocation, "BILLTYPE").text = "New Ref"
        etree.SubElement(bill_allocation, "AMOUNT").text = format_tally_amount(-header['Total'])

        # Process each line item (if any) and associated GST
        # IMPORTANT: This assumes each relevant row in the group represents an item line.
        # If 'Item Name' is empty for the header row but present for subsequent rows,
        # adjust logic in 02_clean_map.py to ensure item data is distinct.
        for idx, item_row in group.iterrows():
            item_name = safe_str(item_row.get('Item Name'))
            if not item_name: # Skip if no item name, assuming it's a header-only row in the group
                continue

            # Debit Sales/Revenue Ledger
            sales_ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(sales_ledger_entry, "LEDGERNAME").text = safe_str(item_row.get('Account', 'Sales Account')) # Use mapped sales ledger
            etree.SubElement(sales_ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes" # Debit
            etree.SubElement(sales_ledger_entry, "AMOUNT").text = format_tally_amount(item_row['Item Total']) # Amount before tax for the line item

            # GST Details (Debit for Output GST)
            # This is a simplified GST application.
            # You might need more sophisticated logic based on 'GST Treatment' or 'Place of Supply'.
            cgst_rate = item_row.get('CGST Rate %', 0.0)
            sgst_rate = item_row.get('SGST Rate %', 0.0)
            igst_rate = item_row.get('IGST Rate %', 0.0)

            if igst_rate > 0 and safe_str(item_row.get('IGST')):
                igst_amount = item_row['IGST']
                gst_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry, "LEDGERNAME").text = safe_str(item_row.get('Tally_Output_IGST_Ledger', 'Output IGST')) # From 02_clean_map
                etree.SubElement(gst_entry, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry, "AMOUNT").text = format_tally_amount(igst_amount)
            elif (cgst_rate > 0 or sgst_rate > 0) and (safe_str(item_row.get('CGST')) or safe_str(item_row.get('SGST'))):
                cgst_amount = item_row.get('CGST', 0.0)
                sgst_amount = item_row.get('SGST', 0.0)

                if cgst_amount > 0:
                    gst_entry_cgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                    etree.SubElement(gst_entry_cgst, "LEDGERNAME").text = safe_str(item_row.get('Tally_Output_CGST_Ledger', 'Output CGST'))
                    etree.SubElement(gst_entry_cgst, "ISDEEMEDPOSITIVE").text = "Yes"
                    etree.SubElement(gst_entry_cgst, "AMOUNT").text = format_tally_amount(cgst_amount)
                if sgst_amount > 0:
                    gst_entry_sgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                    etree.SubElement(gst_entry_sgst, "LEDGERNAME").text = safe_str(item_row.get('Tally_Output_SGST_Ledger', 'Output SGST'))
                    etree.SubElement(gst_entry_sgst, "ISDEEMEDPOSITIVE").text = "Yes"
                    etree.SubElement(gst_entry_sgst, "AMOUNT").text = format_tally_amount(sgst_amount)

        # Round Off Adjustment
        round_off_amount = header.get('Round Off', 0.0)
        if round_off_amount != 0 and not math.isnan(round_off_amount): # Check for both 0 and NaN
            round_off_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(round_off_entry, "LEDGERNAME").text = safe_str(header.get('Tally_Round_Off_Ledger', 'Round Off')) # From 02_clean_map
            etree.SubElement(round_off_entry, "ISDEEMEDPOSITIVE").text = "Yes" if round_off_amount > 0 else "No"
            etree.SubElement(round_off_entry, "AMOUNT").text = format_tally_amount(round_off_amount)

    write_xml_to_file(envelope, "tally_sales_vouchers.xml")


def generate_customer_payments_xml(df_payments):
    """Generates Tally XML for Receipt Vouchers."""
    print("\n--- Generating Customer Payments (Receipt Vouchers) XML ---")
    if df_payments is None: return

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    for index, row in df_payments.iterrows():
        payment_id = safe_str(row['CustomerPayment ID'])
        if not payment_id:
            print(f"⚠️ Skipping customer payment due to empty ID: Row {index+2}")
            continue

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=payment_id,
                                   VCHTYPE="Receipt",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(row['Date'])
        etree.SubElement(voucher, "GUID").text = f"RCP-{payment_id}" # Unique GUID
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Receipt"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(row['Payment Number'])
        etree.SubElement(voucher, "NARRATION").text = safe_str(row.get('Description', 'Customer Payment'))
        etree.SubElement(voucher, "BASICBASECURRENTBAL").text = format_tally_amount(row['Amount']) # Total amount of payment
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(row['Date'])

        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Debit Bank/Cash Account
        debit_bank_cash = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(debit_bank_cash, "LEDGERNAME").text = safe_str(row.get('Tally_Deposit_Ledger', 'Cash-in-Hand')) # From 02_clean_map
        etree.SubElement(debit_bank_cash, "ISDEEMEDPOSITIVE").text = "Yes" # Debit
        etree.SubElement(debit_bank_cash, "AMOUNT").text = format_tally_amount(row['Amount'])

        # Credit Customer Ledger
        credit_customer = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(credit_customer, "LEDGERNAME").text = safe_str(row['Customer Name'])
        etree.SubElement(credit_customer, "ISDEEMEDPOSITIVE").text = "No" # Credit
        etree.SubElement(credit_customer, "AMOUNT").text = format_tally_amount(-row['Amount'])

        # Bill-wise allocation for the customer payment
        invoice_number = safe_str(row.get('Invoice Number'))
        amount_applied = row.get('Amount Applied to Invoice', 0.0)

        if invoice_number and amount_applied != 0:
            bill_allocation = etree.SubElement(credit_customer, "BILLALLOCATIONS.LIST")
            bill_details = etree.SubElement(bill_allocation, "BILLALLOCATIONS")
            etree.SubElement(bill_details, "NAME").text = invoice_number
            etree.SubElement(bill_details, "BILLTYPE").text = "Agst Ref" # Against reference
            etree.SubElement(bill_details, "AMOUNT").text = format_tally_amount(-amount_applied) # Amount applied to specific invoice (as credit)

    write_xml_to_file(envelope, "tally_receipt_vouchers.xml")


def generate_vendor_payments_xml(df_payments):
    """Generates Tally XML for Payment Vouchers."""
    print("\n--- Generating Vendor Payments (Payment Vouchers) XML ---")
    if df_payments is None: return

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    for index, row in df_payments.iterrows():
        payment_id = safe_str(row['VendorPayment ID'])
        if not payment_id:
            print(f"⚠️ Skipping vendor payment due to empty ID: Row {index+2}")
            continue

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=payment_id,
                                   VCHTYPE="Payment",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(row['Date'])
        etree.SubElement(voucher, "GUID").text = f"PAY-{payment_id}" # Unique GUID
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Payment"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(row['Payment Number'])
        etree.SubElement(voucher, "NARRATION").text = safe_str(row.get('Description', 'Vendor Payment'))
        etree.SubElement(voucher, "BASICBASECURRENTBAL").text = format_tally_amount(row['Amount']) # Total amount of payment
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(row['Date'])

        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Debit Vendor Ledger
        debit_vendor = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(debit_vendor, "LEDGERNAME").text = safe_str(row['Vendor Name'])
        etree.SubElement(debit_vendor, "ISDEEMEDPOSITIVE").text = "Yes" # Debit
        etree.SubElement(debit_vendor, "AMOUNT").text = format_tally_amount(row['Amount'])

        # Bill-wise allocation for the vendor payment
        bill_number = safe_str(row.get('Bill Number'))
        bill_amount_applied = row.get('Bill Amount', 0.0) # Amount applied to specific bill
        if bill_number and bill_amount_applied != 0:
            bill_allocation = etree.SubElement(debit_vendor, "BILLALLOCATIONS.LIST")
            bill_details = etree.SubElement(bill_allocation, "BILLALLOCATIONS")
            etree.SubElement(bill_details, "NAME").text = bill_number
            etree.SubElement(bill_details, "BILLTYPE").text = "Agst Ref" # Against reference
            etree.SubElement(bill_details, "AMOUNT").text = format_tally_amount(bill_amount_applied) # Amount applied to specific bill (as debit)

        # Credit Bank/Cash Account
        credit_bank_cash = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(credit_bank_cash, "LEDGERNAME").text = safe_str(row.get('Tally_Paid_Through_Ledger', 'Cash-in-Hand')) # From 02_clean_map
        etree.SubElement(credit_bank_cash, "ISDEEMEDPOSITIVE").text = "No" # Credit
        etree.SubElement(credit_bank_cash, "AMOUNT").text = format_tally_amount(-row['Amount'])

    write_xml_to_file(envelope, "tally_payment_vouchers.xml")


def generate_credit_notes_xml(df_credit_notes):
    """Generates Tally XML for Credit Note Vouchers."""
    print("\n--- Generating Credit Notes XML ---")
    if df_credit_notes is None: return

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    # Group by 'CreditNotes ID' to handle multiple line items per credit note
    df_credit_notes['Total'] = pd.to_numeric(df_credit_notes['Total'], errors='coerce').fillna(0)
    grouped_credit_notes = df_credit_notes.groupby('CreditNotes ID')

    for credit_note_id, group in grouped_credit_notes:
        header = group.iloc[0]

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(header['CreditNotes ID']),
                                   VCHTYPE="Credit Note",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header['Credit Note Date'])
        etree.SubElement(voucher, "GUID").text = f"CRN-{safe_str(header['CreditNotes ID'])}" # Unique GUID
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Credit Note"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(header['Credit Note Number'])
        etree.SubElement(voucher, "PARTYLEDGERNAME").text = safe_str(header['Customer Name'])
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Reason', 'Credit Note issued'))
        etree.SubElement(voucher, "BASICBUYERNAME").text = safe_str(header['Customer Name']) # For GST
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header['Credit Note Date'])
        etree.SubElement(voucher, "ISORIGINAL").text = "Yes" # Indicates it's a new entry

        # Buyer/Consignee details for GST
        buyer_details = etree.SubElement(voucher, "BUYERDETAILS.LIST")
        etree.SubElement(buyer_details, "CONSNAME").text = safe_str(header['Customer Name'])
        cons_address_list = etree.SubElement(buyer_details, "ADDRESS.LIST")
        if safe_str(header.get('Shipping Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Address'))
            if safe_str(header.get('Shipping Street 2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Shipping Street 2'))
        elif safe_str(header.get('Billing Address')):
            etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Address'))
            if safe_str(header.get('Billing Street 2')):
                etree.SubElement(cons_address_list, "ADDRESS").text = safe_str(header.get('Billing Street 2'))

        etree.SubElement(buyer_details, "STATENAME").text = safe_str(header.get('Shipping State', '') or header.get('Billing State', '') or '')
        etree.SubElement(buyer_details, "COUNTRYNAME").text = safe_str(header.get('Shipping Country', '') or header.get('Billing Country', '') or DEFAULT_COUNTRY)

        gstin = safe_str(header.get('GST Identification Number (GSTIN)'))
        if gstin:
            etree.SubElement(buyer_details, "GSTREGISTRATIONTYPE").text = safe_str(header.get('GST Treatment', 'Regular'))
            etree.SubElement(buyer_details, "GSTIN").text = gstin
        
        # Original Sales/Invoice details for GST Credit Note
        # This is where you link the credit note to the original invoice for Tally's GST reports.
        if safe_str(header.get('Associated Invoice Number')):
            original_invoice_details = etree.SubElement(voucher, "ORIGINALINVOICEDETAILS.LIST")
            orig_inv_item = etree.SubElement(original_invoice_details, "ORIGINALINVOICEDETAILS")
            etree.SubElement(orig_inv_item, "DATE").text = format_tally_date(header.get('Associated Invoice Date', ''))
            etree.SubElement(orig_inv_item, "REFNUM").text = safe_str(header.get('Associated Invoice Number'))


        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Debit Sales Returns / Revenue (or the original Sales Ledger)
        for idx, item_row in group.iterrows():
            item_name = safe_str(item_row.get('Item Name'))
            if not item_name:
                continue

            debit_sales_return = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(debit_sales_return, "LEDGERNAME").text = safe_str(item_row.get('Tally_Sales_Return_Ledger', 'Sales Returns')) # Use mapped Sales Returns ledger
            etree.SubElement(debit_sales_return, "ISDEEMEDPOSITIVE").text = "Yes" # Debit
            etree.SubElement(debit_sales_return, "AMOUNT").text = format_tally_amount(item_row['Item Total']) # Amount of item

            # Reverse GST (Credit for Output GST)
            cgst_rate = item_row.get('CGST Rate %', 0.0)
            sgst_rate = item_row.get('SGST Rate %', 0.0)
            igst_rate = item_row.get('IGST Rate %', 0.0)

            if igst_rate > 0 and safe_str(item_row.get('IGST')):
                igst_amount = item_row['IGST']
                gst_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry, "LEDGERNAME").text = safe_str(item_row.get('Tally_Output_IGST_Ledger', 'Output IGST'))
                etree.SubElement(gst_entry, "ISDEEMEDPOSITIVE").text = "No" # Reverse effect
                etree.SubElement(gst_entry, "AMOUNT").text = format_tally_amount(-igst_amount)
            elif (cgst_rate > 0 or sgst_rate > 0) and (safe_str(item_row.get('CGST')) or safe_str(item_row.get('SGST'))):
                cgst_amount = item_row.get('CGST', 0.0)
                sgst_amount = item_row.get('SGST', 0.0)

                if cgst_amount > 0:
                    gst_entry_cgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                    etree.SubElement(gst_entry_cgst, "LEDGERNAME").text = safe_str(item_row.get('Tally_Output_CGST_Ledger', 'Output CGST'))
                    etree.SubElement(gst_entry_cgst, "ISDEEMEDPOSITIVE").text = "No"
                    etree.SubElement(gst_entry_cgst, "AMOUNT").text = format_tally_amount(-cgst_amount)
                if sgst_amount > 0:
                    gst_entry_sgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                    etree.SubElement(gst_entry_sgst, "LEDGERNAME").text = safe_str(item_row.get('Tally_Output_SGST_Ledger', 'Output SGST'))
                    etree.SubElement(gst_entry_sgst, "ISDEEMEDPOSITIVE").text = "No"
                    etree.SubElement(gst_entry_sgst, "AMOUNT").text = format_tally_amount(-sgst_amount)
        
        # Credit Customer Ledger
        credit_customer = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(credit_customer, "LEDGERNAME").text = safe_str(header['Customer Name'])
        etree.SubElement(credit_customer, "ISDEEMEDPOSITIVE").text = "No" # Credit
        etree.SubElement(credit_customer, "AMOUNT").text = format_tally_amount(-header['Total']) # Total credit note amount

        # Against Invoice Reference (if applicable)
        associated_invoice_number = safe_str(header.get('Associated Invoice Number'))
        if associated_invoice_number:
            bill_allocation = etree.SubElement(credit_customer, "BILLALLOCATIONS.LIST")
            bill_details = etree.SubElement(bill_allocation, "BILLALLOCATIONS")
            etree.SubElement(bill_details, "NAME").text = associated_invoice_number
            etree.SubElement(bill_details, "BILLTYPE").text = "Agst Ref"
            etree.SubElement(bill_details, "AMOUNT").text = format_tally_amount(-header['Total'])

    write_xml_to_file(envelope, "tally_credit_notes.xml")


def generate_journal_vouchers_xml(df_journals):
    """Generates Tally XML for Journal Vouchers."""
    print("\n--- Generating Journal Vouchers XML ---")
    if df_journals is None: return

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    # Group by 'Journal Number' as a single journal voucher in Tally can have multiple debit/credit entries.
    grouped_journals = df_journals.groupby('Journal Number')

    for journal_num, group in grouped_journals:
        # Take the first row as the header for date, narration etc.
        header = group.iloc[0]

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(journal_num),
                                   VCHTYPE="Journal",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header['Journal Date'])
        etree.SubElement(voucher, "GUID").text = f"JRN-{safe_str(journal_num)}" # Unique GUID
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Journal"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(journal_num)
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Notes', 'Journal Entry'))
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header['Journal Date'])


        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Iterate through each line in the grouped journal
        for idx, entry_row in group.iterrows():
            ledger_name = safe_str(entry_row['Account'])
            debit_amount = entry_row['Debit']
            credit_amount = entry_row['Credit']

            if debit_amount > 0:
                ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(ledger_entry, "LEDGERNAME").text = ledger_name
                etree.SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes" # Debit
                etree.SubElement(ledger_entry, "AMOUNT").text = format_tally_amount(debit_amount)
            elif credit_amount > 0:
                ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(ledger_entry, "LEDGERNAME").text = ledger_name
                etree.SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "No" # Credit
                etree.SubElement(ledger_entry, "AMOUNT").text = format_tally_amount(-credit_amount) # Tally expects negative for Credit

        # A quick check to ensure total debit equals total credit for the journal entry
        total_debit = group['Debit'].sum()
        total_credit = group['Credit'].sum()
        if abs(total_debit - total_credit) > 0.01: # Allow for minor floating point differences
            print(f"❌ Warning: Journal '{journal_num}' has imbalanced debit/credit. Debit: {total_debit}, Credit: {total_credit}")


    write_xml_to_file(envelope, "tally_journal_vouchers.xml")


def generate_purchase_vouchers_xml(df_bills):
    """Generates Tally XML for Purchase Vouchers from Bills."""
    print("\n--- Generating Purchase Vouchers XML ---")
    if df_bills is None: return

    envelope, tally_message = create_tally_envelope("Vouchers", "VOUCHERS")

    # Group by 'Bill ID' to handle multiple line items per bill.
    df_bills['Total'] = pd.to_numeric(df_bills['Total'], errors='coerce').fillna(0)
    grouped_bills = df_bills.groupby('Bill ID')

    for bill_id, group in grouped_bills:
        header = group.iloc[0]

        voucher = etree.SubElement(tally_message, "VOUCHER",
                                   REMOTEID=safe_str(header['Bill ID']),
                                   VCHTYPE="Purchase",
                                   ACTION="CREATE")

        etree.SubElement(voucher, "DATE").text = format_tally_date(header['Bill Date'])
        etree.SubElement(voucher, "GUID").text = f"PUR-{safe_str(header['Bill ID'])}" # Unique GUID
        etree.SubElement(voucher, "VOUCHERTYPENAME").text = "Purchase"
        etree.SubElement(voucher, "VOUCHERNUMBER").text = safe_str(header['Bill Number'])
        etree.SubElement(voucher, "PARTYLEDGERNAME").text = safe_str(header['Vendor Name'])
        etree.SubElement(voucher, "BASICBUYERNAME").text = "" # Not applicable for purchase
        etree.SubElement(voucher, "BASICSELLERNAME").text = safe_str(header['Vendor Name'])
        etree.SubElement(voucher, "PERSISTEDVIEW").text = "Accounting Voucher"
        etree.SubElement(voucher, "EFFECTIVEDATE").text = format_tally_date(header['Bill Date'])
        etree.SubElement(voucher, "NARRATION").text = safe_str(header.get('Vendor Notes', ''))
        
        # Seller details for GST
        seller_details = etree.SubElement(voucher, "SELLERDETAILS.LIST")
        etree.SubElement(seller_details, "CONSNAME").text = safe_str(header['Vendor Name'])
        # You may need to fetch vendor's address from the processed_contacts/vendors.csv if not directly in bills
        gstin = safe_str(header.get('GST Identification Number (GSTIN)'))
        if gstin:
            etree.SubElement(seller_details, "GSTREGISTRATIONTYPE").text = safe_str(header.get('GST Treatment', 'Regular'))
            etree.SubElement(seller_details, "GSTIN").text = gstin
        

        all_ledger_entries = etree.SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        # Credit the Party Ledger (Vendor)
        party_ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
        etree.SubElement(party_ledger_entry, "LEDGERNAME").text = safe_str(header['Vendor Name'])
        etree.SubElement(party_ledger_entry, "ISDEEMEDPOSITIVE").text = "No" # Credit
        etree.SubElement(party_ledger_entry, "AMOUNT").text = format_tally_amount(-header['Total']) # Total bill amount, as credit
        
        # Bill-wise details
        bill_allocation_list = etree.SubElement(party_ledger_entry, "BILLALLOCATIONS.LIST")
        bill_allocation = etree.SubElement(bill_allocation_list, "BILLALLOCATIONS")
        etree.SubElement(bill_allocation, "NAME").text = safe_str(header['Bill Number'])
        etree.SubElement(bill_allocation, "BILLTYPE").text = "New Ref"
        etree.SubElement(bill_allocation, "AMOUNT").text = format_tally_amount(-header['Total'])

        # Process each line item
        for idx, item_row in group.iterrows():
            item_name = safe_str(item_row.get('Item Name'))
            if not item_name:
                continue

            # Debit Purchase Ledger
            purchase_ledger_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(purchase_ledger_entry, "LEDGERNAME").text = safe_str(item_row.get('Account', 'Purchase Account')) # Use mapped purchase ledger
            etree.SubElement(purchase_ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes" # Debit
            etree.SubElement(purchase_ledger_entry, "AMOUNT").text = format_tally_amount(item_row['Item Total']) # Amount before tax for the line item

            # GST Details (Debit for Input GST)
            cgst_rate = item_row.get('CGST Rate %', 0.0)
            sgst_rate = item_row.get('SGST Rate %', 0.0)
            igst_rate = item_row.get('IGST Rate %', 0.0)

            if igst_rate > 0 and safe_str(item_row.get('IGST')): # Assuming 'IGST' column for amount
                igst_amount = item_row['IGST']
                gst_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                etree.SubElement(gst_entry, "LEDGERNAME").text = safe_str(item_row.get('Tally_Input_IGST_Ledger', 'Input IGST')) # From 02_clean_map
                etree.SubElement(gst_entry, "ISDEEMEDPOSITIVE").text = "Yes"
                etree.SubElement(gst_entry, "AMOUNT").text = format_tally_amount(igst_amount)
            elif (cgst_rate > 0 or sgst_rate > 0) and (safe_str(item_row.get('CGST')) or safe_str(item_row.get('SGST'))):
                cgst_amount = item_row.get('CGST', 0.0)
                sgst_amount = item_row.get('SGST', 0.0)

                if cgst_amount > 0:
                    gst_entry_cgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                    etree.SubElement(gst_entry_cgst, "LEDGERNAME").text = safe_str(item_row.get('Tally_Input_CGST_Ledger', 'Input CGST'))
                    etree.SubElement(gst_entry_cgst, "ISDEEMEDPOSITIVE").text = "Yes"
                    etree.SubElement(gst_entry_cgst, "AMOUNT").text = format_tally_amount(cgst_amount)
                if sgst_amount > 0:
                    gst_entry_sgst = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
                    etree.SubElement(gst_entry_sgst, "LEDGERNAME").text = safe_str(item_row.get('Tally_Input_SGST_Ledger', 'Input SGST'))
                    etree.SubElement(gst_entry_sgst, "ISDEEMEDPOSITIVE").text = "Yes"
                    etree.SubElement(gst_entry_sgst, "AMOUNT").text = format_tally_amount(sgst_amount)

        # Round Off Adjustment (using 'Adjustment' column from Bill.csv)
        adjustment_amount = header.get('Adjustment', 0.0)
        if adjustment_amount != 0 and not math.isnan(adjustment_amount):
            round_off_entry = etree.SubElement(all_ledger_entries, "ALLLEDGERENTRIES")
            etree.SubElement(round_off_entry, "LEDGERNAME").text = safe_str(header.get('Tally_Round_Off_Ledger', 'Round Off'))
            etree.SubElement(round_off_entry, "ISDEEMEDPOSITIVE").text = "Yes" if adjustment_amount > 0 else "No"
            etree.SubElement(round_off_entry, "AMOUNT").text = format_tally_amount(adjustment_amount)

    write_xml_to_file(envelope, "tally_purchase_vouchers.xml")


# --- Main Execution ---
if __name__ == "__main__":
    print("--- Starting 03_generate_tally_xml.py: Generating Tally XML Files ---")

    # Ensure output directory exists
    if not os.path.exists(OUTPUT_XML_DIR):
        os.makedirs(OUTPUT_XML_DIR)

    # --- Load Processed DataFrames ---
    # These CSVs should be present from running 02_clean_map.py
    coa_df = load_processed_csv('cleaned_chart_of_accounts.csv')
    contacts_df = load_processed_csv('cleaned_contacts.csv')
    vendors_df = load_processed_csv('cleaned_vendors.csv')
    invoices_df = load_processed_csv('cleaned_invoices.csv')
    customer_payments_df = load_processed_csv('cleaned_customer_payments.csv')
    vendor_payments_df = load_processed_csv('cleaned_vendor_payments.csv')
    credit_notes_df = load_processed_csv('cleaned_credit_notes.csv')
    journals_df = load_processed_csv('cleaned_journals.csv')
    bills_df = load_processed_csv('cleaned_bills.csv')

    # --- Generate XMLs in recommended order ---
    # 1. Masters (Ledgers & Groups)
    generate_ledgers_xml(coa_df)
    generate_contacts_vendors_xml(contacts_df, vendors_df)

    # 2. Vouchers (Financial)
    generate_sales_vouchers_xml(invoices_df)
    generate_customer_payments_xml(customer_payments_df)
    generate_vendor_payments_xml(vendor_payments_df)
    generate_credit_notes_xml(credit_notes_df)
    generate_purchase_vouchers_xml(bills_df)
    generate_journal_vouchers_xml(journals_df)


    print("\n--- 03_generate_tally_xml.py: Tally XML generation complete. ---")
    print(f"XML files are located in the '{OUTPUT_XML_DIR}' directory.")
    print("Now, proceed to import these XML files into your Tally ERP company.")
    print("Refer to '04_batch_import_instructions.md' for detailed steps and troubleshooting.")