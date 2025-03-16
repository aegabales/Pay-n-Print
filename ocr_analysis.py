import sys
import os
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import json
import fitz
import io

# Ensure correct usage of the script
if len(sys.argv) < 2:
    print("Usage: python script.py <file_name> [page_numbers]")
    sys.exit(1)

pdf_path = sys.argv[1]

if len(sys.argv) > 2:
    specific_pages = list(map(int, ' '.join(sys.argv[2:]).split()))
else:
    specific_pages = None

if not os.path.isfile(pdf_path):
    print(f"Error: The file {pdf_path} does not exist.")
    sys.exit(1)

poppler_path = r'C:\Program Files\poppler-24.07.0\Library\bin'

def extract_images_from_pdf(pdf_path, specific_pages=None):
    pdf_document = fitz.open(pdf_path)
    page_images = []
    image_count_per_page = []

    for page_number in range(len(pdf_document)):
        # Only process specific pages if provided
        if specific_pages and (page_number + 1) not in specific_pages:
            continue

        page = pdf_document.load_page(page_number)
        images = []
        image_list = page.get_images(full=True)
        image_count = 0

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = pdf_document.extract_image(xref)
            image_bytes = base_image["image"]
            image = Image.open(io.BytesIO(image_bytes))
            
            # Ignore small or transparent images
            if is_black_image(image) or is_transparent_image(image) or is_too_small(image):
                print(f"Skipping small/black/transparent image on page {page_number + 1}")
                continue
            
            images.append(image)
            image_count += 1

        page_images.append(images)
        image_count_per_page.append(image_count)
    
    return page_images, image_count_per_page

def extract_colored_text_from_pdf(pdf_path, specific_pages=None):
    pdf_document = fitz.open(pdf_path)
    total_colored_text_instances = 0
    colored_text_pages = 0

    for page_number in range(len(pdf_document)):
        if specific_pages and (page_number + 1) not in specific_pages:
            continue

        page = pdf_document.load_page(page_number)
        text_instances = page.get_text("dict")
        page_colored_text = 0

        for block in text_instances['blocks']:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    color = span.get("color")
                    if color and color != (0, 0, 0):  # Check if text is colored
                        page_colored_text += 1

        if page_colored_text > 0:
            colored_text_pages += 1
            total_colored_text_instances += page_colored_text

    return total_colored_text_instances, colored_text_pages

def is_black_image(image):
    """Check if the image is entirely black or nearly black."""
    grayscale_image = image.convert("L")
    pixel_values = list(grayscale_image.getdata())
    
    # If more than 98% of pixels are black (0-10 grayscale range), consider it a black image
    black_pixel_threshold = 0.98 * len(pixel_values)
    black_pixels = sum(1 for pixel in pixel_values if pixel <= 10)
    
    return black_pixels >= black_pixel_threshold

def is_transparent_image(image):
    """Check if the image contains transparency (alpha channel)."""
    if image.mode == "RGBA":
        alpha_channel = image.getchannel("A")
        return max(alpha_channel.getdata()) < 10  # Mostly transparent
    return False

def is_too_small(image):
    """Ignore images that are very small (likely artifacts)."""
    width, height = image.size
    return width * height < 5000  # Ignore images smaller than 5000 pixels

def is_black_and_white(image):
    """Check if an image is purely black & white."""
    grayscale_image = image.convert("L")
    grayscale_rgb_image = grayscale_image.convert("RGB")
    return list(image.getdata()) == list(grayscale_rgb_image.getdata())

def is_large_image(image):
    """Check if the image is large (over 100k pixels)."""
    width, height = image.size
    return width * height > 100000  # 100k pixels threshold

# Counters for analysis results
color_pages = 0
black_white_pages = 0
pages_with_images = 0
large_color_images = 0

# Extract images and analyze text color from specified pages (or all pages if none specified)
page_images, image_count_per_page = extract_images_from_pdf(pdf_path, specific_pages)
total_colored_text_instances, colored_text_pages = extract_colored_text_from_pdf(pdf_path, specific_pages)

# Process each page's images
for images, image_count in zip(page_images, image_count_per_page):
    page_has_image = False
    page_is_colored_image = False
    for image in images:
        text = pytesseract.image_to_string(image)

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

# Output results in JSON format
result = {
    "color_pages": color_pages,
    "black_white_pages": black_white_pages,
    "pages_with_images": pages_with_images,
    "large_color_images": large_color_images,
    "colored_text_pages": colored_text_pages,
    "total_colored_text_instances": total_colored_text_instances,
    "image_count_per_page": image_count_per_page
}

print(json.dumps(result, indent=4))
