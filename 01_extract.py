import zipfile
import os
import pandas as pd # Included for consistency, though not strictly used in extraction/verification itself

# --- Configuration ---
# Define the path to your Zoho backup ZIP file
ZIP_FILE_PATH = "/mnt/data/Plant Essentials Private Limited_2025-07-09.zip"

# Define the directory where the ZIP contents will be extracted
EXTRACT_TO_DIR = "/mnt/data/zoho_extracted"

# List of expected Zoho CSV files that are crucial for the migration.
# This list is based on the analysis you've already performed.
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
    'Item.csv' # Including Item as it was found in your backup, though financial focus initially
]

# --- Helper Functions ---

def extract_zoho_zip(zip_path, extract_path):
    """
    Extracts the Zoho backup ZIP file to the specified directory.
    Creates the extraction directory if it doesn't exist.
    Handles common errors like invalid ZIP file or file not found.
    """
    if not os.path.exists(extract_path):
        os.makedirs(extract_path)
        print(f"Created extraction directory: '{extract_path}'")
    else:
        print(f"Extraction directory already exists: '{extract_path}'")

    try:
        print(f"Attempting to extract '{os.path.basename(zip_path)}'...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        print(f"✅ Successfully extracted '{os.path.basename(zip_path)}' to '{extract_path}'")
    except zipfile.BadZipFile:
        print(f"❌ Error: '{zip_path}' is not a valid ZIP file. Please check the file integrity.")
        exit(1) # Exit the script on critical error
    except FileNotFoundError:
        print(f"❌ Error: ZIP file not found at '{zip_path}'. Please ensure the path is correct.")
        exit(1) # Exit the script on critical error
    except Exception as e:
        print(f"❌ An unexpected error occurred during extraction: {e}")
        exit(1) # Exit the script on critical error

def verify_extracted_files(extract_path, expected_files):
    """
    Verifies if all the crucial CSV files listed in ZOHO_CSVS are present
    in the extracted directory.
    Prints a summary of found and missing files.
    Returns True if all expected files are found, False otherwise.
    """
    missing_files = []
    found_files = []
    print("\n--- Verifying Extracted Files ---")
    for file_name in expected_files:
        file_path = os.path.join(extract_path, file_name)
        if not os.path.exists(file_path):
            missing_files.append(file_name)
        else:
            found_files.append(file_name)

    if missing_files:
        print("\n⚠️ Warning: The following expected Zoho CSV files are MISSING:")
        for mf in missing_files:
            print(f"- {mf}")
        print("\nPlease ensure your Zoho backup ZIP contains these files or adjust the `ZOHO_CSVS` list if they are not relevant.")
        print("Migration may not be complete without these files.")
        return False
    else:
        print("\n✅ All expected Zoho CSV files are present and ready for processing.")
        # Optional: Print all found files for confirmation
        # print("Found files:")
        # for ff in found_files:
        #     print(f"- {ff}")
        return True

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Starting 01_extract.py: Zoho Data Extraction & Verification ---")

    # Step 1: Extract the Zoho ZIP file
    extract_zoho_zip(ZIP_FILE_PATH, EXTRACT_TO_DIR)

    # Step 2: Verify that the crucial CSVs are present
    if verify_extracted_files(EXTRACT_TO_DIR, ZOHO_CSVS):
        print("\n--- 01_extract.py completed successfully. ---")
        print("You can now proceed to data cleaning and mapping using '02_clean_map.py'.")
    else:
        print("\n--- 01_extract.py finished with warnings/errors. ---")
        print("Please review the output and address any missing files before proceeding.")