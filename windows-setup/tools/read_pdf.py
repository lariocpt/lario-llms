import argparse
import PyPDF2

def read_pdf(file_path):
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
            print(text)
    except Exception as e:
        print(f"Error reading PDF: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read a PDF file and output text.")
    parser.add_argument("file", help="Path to the PDF file")
    args = parser.parse_args()
    read_pdf(args.file)
