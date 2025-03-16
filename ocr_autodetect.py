import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import pytesseract
import io

def is_black_and_white(image):
    grayscale_image = image.convert("L")
    grayscale_rgb_image = grayscale_image.convert("RGB")
    return list(image.getdata()) == list(grayscale_rgb_image.getdata())

def is_large_image(image):
    width, height = image.size
    return width >= 500 and height >= 500

def extract_images_from_pdf(pdf_path, specific_pages=None):
    doc = fitz.open(pdf_path)
    images_per_page = []
    image_count_per_page = []
    total_images = 0
    
    for page_num in range(len(doc)):
        if specific_pages and (page_num + 1) not in specific_pages:
            continue
        
        page = doc.load_page(page_num)
        images = page.get_images(full=True)
        page_images = []
        
        for img_index, img in enumerate(images):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image = Image.open(io.BytesIO(image_bytes))
            page_images.append(image)
            total_images += 1
        
        images_per_page.append(page_images)
        image_count_per_page.append(len(page_images))

    return images_per_page, image_count_per_page

def extract_colored_text_from_pdf(pdf_path, specific_pages=None):
    doc = fitz.open(pdf_path)
    colored_text_count = 0
    colored_text_pages = 0

    for page_num in range(len(doc)):
        if specific_pages and (page_num + 1) not in specific_pages:
            continue
        
        page = doc.load_page(page_num)
        text_instances = page.get_text("dict")["blocks"]

        has_colored_text = False
        for block in text_instances:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        color = span["color"]
                        if color != 0:
                            colored_text_count += 1
                            has_colored_text = True
        
        if has_colored_text:
            colored_text_pages += 1

    return colored_text_count, colored_text_pages

def run_analysis(pdf_path, specific_pages=None):
    if not pdf_path:
        raise ValueError("Invalid file path provided.")

    try:
        print(f"🔎 Analyzing PDF: {pdf_path}")
        doc = fitz.open(pdf_path)

        total_pages = len(doc)

        # ✅ Extract images and analyze text color from specified pages
        page_images, image_count_per_page = extract_images_from_pdf(pdf_path, specific_pages)
        total_colored_text_instances, colored_text_pages = extract_colored_text_from_pdf(pdf_path, specific_pages)

        color_pages = 0
        black_white_pages = 0
        pages_with_images = 0
        large_color_images = 0

        # ✅ Process each page's images
        for images, image_count in zip(page_images, image_count_per_page):
            page_has_image = False
            page_is_colored_image = False

            for image in images:
                text = pytesseract.image_to_string(image)  # OCR text extraction (optional)

                if is_black_and_white(image):
                    page_is_colored_image = False
                else:
                    page_is_colored_image = True
                    if is_large_image(image):
                        large_color_images += 1

                if not page_has_image:
                    page_has_image = True

            if page_has_image:
                pages_with_images += 1

            if page_is_colored_image:
                color_pages += 1
            else:
                black_white_pages += 1

        result = {
            "total_pages": total_pages,
            "analyzed_pages": len(specific_pages) if specific_pages else total_pages,
            "color_pages": color_pages,
            "black_white_pages": black_white_pages,
            "pages_with_images": pages_with_images,
            "large_color_images": large_color_images,
            "colored_text_pages": colored_text_pages,
            "total_colored_text_instances": total_colored_text_instances,
            "total_images": sum(image_count_per_page)
        }

        print(f"✅ OCR Analysis Complete: {result}")
        return result

    except Exception as e:
        print(f"❌ Error during OCR analysis: {e}")
        return None