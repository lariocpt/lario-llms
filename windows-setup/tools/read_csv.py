import argparse
import pandas as pd

def read_csv(file_path):
    try:
        df = pd.read_csv(file_path)
        print(df.to_string())
    except Exception as e:
        print(f"Error reading CSV file: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read a CSV file and output text.")
    parser.add_argument("file", help="Path to the CSV file")
    args = parser.parse_args()
    read_csv(args.file)
