import argparse
import pandas as pd

def read_excel(file_path, sheet_name=None):
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        print(df.to_string())
    except Exception as e:
        print(f"Error reading Excel file: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read an Excel file and output text.")
    parser.add_argument("file", help="Path to the Excel file")
    parser.add_argument("--sheet", help="Specific sheet name to read", default=None)
    args = parser.parse_args()
    read_excel(args.file, args.sheet)
