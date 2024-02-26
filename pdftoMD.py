import sys
import pdf2image
import pytesseract

def pdf_to_markdown(pdf_path):
    # Convert PDF to images
    images = pdf2image.convert_from_path(pdf_path)

    markdown = ""
    for i, image in enumerate(images):
        # Convert image to text using OCR
        text = pytesseract.image_to_string(image, lang='eng')

        # Append text to markdown
        markdown += text + "\n"

    return markdown

if __name__ == "__main__":
    # Check if PDF path is provided as command line argument
    if len(sys.argv) < 2:
        print("Please provide the path to the PDF file as a command line argument.")
        sys.exit(1)

    pdf_path = sys.argv[1]
    markdown_output = pdf_to_markdown(pdf_path)
    print(markdown_output)

