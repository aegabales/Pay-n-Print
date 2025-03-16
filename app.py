from flask import Flask, request, render_template, redirect, url_for, send_from_directory, jsonify
import os
import mysql.connector
import fitz
import pdfkit
import json
import subprocess
import platform

import platform

if platform.system() == "Windows":
    try:
        import win32api
        import pythoncom
        import requests
        import comtypes.client
        import secrets
        from admin import admin_bp
        from ocr_autodetect import run_analysis
        import fitz  # PyMuPDF
        import numpy as np
        import pymysql
        import win32print
    except ImportError:
        pass


app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.register_blueprint(admin_bp, url_prefix='/admin')

# Ignore comtypes-generated files
os.environ["WATCHDOG_IGNORE_DIRECTORIES"] = "comtypes"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

MODIFIED_FOLDER = "modified_prints"
os.makedirs(MODIFIED_FOLDER, exist_ok=True)
app.config["MODIFIED_FOLDER"] = MODIFIED_FOLDER

@app.route('/modified_prints/<filename>')
def modified_file(filename):
    return send_from_directory("modified_prints", filename)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve the uploaded file."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)

# Database Connection
db = mysql.connector.connect(
    host=os.getenv("host", "localhost"),
    user=os.getenv("user", "root"),
    password=os.getenv("password", ""),
    database=os.getenv("database", "pnp")
)

cursor = db.cursor(dictionary=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/pricelist')
def pricelist_page():

    cursor.execute("SELECT * FROM prices WHERE type = 'Paper Size'")
    paper_sizes = cursor.fetchall()
    
    cursor.execute("SELECT * FROM prices WHERE type = 'Additional Cost'")
    additional_costs = cursor.fetchall()

    return render_template('pricelist.html', paper_sizes=paper_sizes, additional_costs=additional_costs)

# ====================== UPLOAD PAGE ===========================================
def allowed_file(filename):
    allowed_extensions = {"pdf", "doc", "docx"}
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions

def convert_docx_to_pdf(input_path):
    UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    """
    Convert a DOCX file to PDF using Microsoft Word automation (Windows only).
    """
    try:
        # Convert to absolute paths
        absolute_input_path = os.path.abspath(input_path)
        output_path = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(os.path.splitext(input_path)[0] + ".pdf"))
        absolute_output_path = os.path.abspath(output_path)

        # Use Microsoft Word to convert DOCX to PDF
        pythoncom.CoInitialize()  # Required for COM threading safety
        word = comtypes.client.CreateObject("Word.Application")
        word.Visible = False  # Run Microsoft Word in the background

        # Open and save the file as PDF
        doc = word.Documents.Open(absolute_input_path)
        doc.SaveAs(absolute_output_path, FileFormat=17)  # 17 = wdFormatPDF
        doc.Close()
        word.Quit()

        if os.path.exists(absolute_output_path):
            print(f"✅ DOCX successfully converted to PDF: {absolute_output_path}")
            return absolute_output_path
        else:
            print("❌ Conversion failed. PDF not created.")
            return None
    except Exception as e:
        print(f"❌ Error converting DOCX to PDF: {e}")
        return None

def get_pdf_page_count(pdf_path):
    """Counts pages in a PDF."""
    try:
        if os.path.exists(pdf_path):
            with fitz.open(pdf_path) as doc:
                return len(doc)
    except Exception as e:
        print(f"Error counting pages in PDF: {e}")
    return 0

def modify_pdf(input_path, color_mode, orientation, sizeName, copies, selected_pages):
    """Modify the PDF with high-quality Black & White conversion and optional rotation."""
    try:
            doc = fitz.open(input_path)
            modified_doc = fitz.open()

            # Get filename without extension
            filename = os.path.basename(input_path)
            modified_path = os.path.join(app.config["MODIFIED_FOLDER"], filename)

            for page_num in selected_pages:
                if 1 <= page_num <= len(doc):
                    page = doc[page_num - 1]
                    new_page = modified_doc.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.show_pdf_page(new_page.rect, doc, page_num - 1)

                    # Convert to Black & White
                    if color_mode == "Black & White":
                        pix = page.get_pixmap()
                        img = fitz.Pixmap(fitz.csGRAY, pix)
                        new_page.insert_image(new_page.rect, pixmap=img)

            modified_doc.save(modified_path)
            modified_doc.close()
            doc.close()
            print(f" Modified PDF saved: {modified_path}")

    except Exception as e:
            print(f" Error modifying PDF: {e}")

def detect_black_and_white_pages(pdf_path):
    """Detects how many pages are black-and-white and how many are colored."""
    try:
        doc = fitz.open(pdf_path)
        bnw_count = 0
        color_count = 0

        for page in doc:
            # Convert page to a high-resolution pixmap
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)

            # Check if the image contains color
            if np.any(img[:, :, 0] != img[:, :, 1]) or np.any(img[:, :, 1] != img[:, :, 2]):
                color_count += 1  # At least one pixel is colored
            else:
                bnw_count += 1  # All pixels are grayscale (R=G=B)

        return bnw_count, color_count
    except Exception as e:
        print(f"Error analyzing colors in PDF: {e}")
        return 0, 0

def detect_orientation(pdf_path):
    """Detects if the PDF is portrait or landscape."""
    try:
        doc = fitz.open(pdf_path)
        first_page = doc[0]  # Check the first page
        width, height = first_page.rect.width, first_page.rect.height
        return "Portrait" if height > width else "Landscape"
    except Exception as e:
        print(f"Error detecting orientation: {e}")
        return "Unknown"

def get_file_size(pdf_path):
    """Gets the file size in KB."""
    try:
        file_size = os.path.getsize(pdf_path) / 1024  
        return round(file_size, 2)
    except Exception as e:
        print(f"Error getting file size: {e}")
        return 0.0
    
def detect_paper_size(file_path):
    """Detects if a file is Letter (short), A4 (short), or Legal (long)."""

    # ✅ If it's a DOCX file, convert to PDF first
    if file_path.lower().endswith(".docx"):
        print("Detected DOCX file, converting to PDF for size detection...")
        converted_pdf = convert_docx_to_pdf(file_path)
        if not converted_pdf:
            return "Unknown (Conversion Failed)"
        file_path = converted_pdf  # ✅ Use the converted PDF

    try:
        doc = fitz.open(file_path)
        first_page = doc[0]
        width, height = first_page.rect.width, first_page.rect.height

        # ✅ Print actual detected dimensions
        print(f"Detected Page Size: Width = {width}, Height = {height}")

        # Ensure consistent comparison (Portrait Mode)
        if width > height:
            width, height = height, width  # Swap

        # Standard sizes in points (1 inch = 72 points)
        paper_sizes = {
            "Letter (short)": (612, 792),  # 8.5 x 11 inches
            "Legal (long)": (612, 1008)  # 8.5 x 14 inches
        }

        for name, (w, h) in paper_sizes.items():
            if abs(width - w) < 10 and abs(height - h) < 10:
                print(f"Matched Paper Size: {name}")
                return name

        print("Paper Size Not Matched! Returning Unknown.")
        return "Unknown Size"

    except Exception as e:
        print(f"Error detecting paper size: {e}")
        return "Unknown"


def remove_blank_pages(pdf_path, output_path):
    """Removes blank pages (pages with no text or images) from a PDF."""
    try:
        doc = fitz.open(pdf_path)
        cleaned_doc = fitz.open()

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Check if the page has text
            text = page.get_text("text").strip()

            # Check if the page has images
            images = page.get_images(full=True)

            if text or images:  # ✅ Keep the page if it has text or images
                cleaned_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        if len(cleaned_doc) == 0:
            print("❌ All pages were blank! No output file generated.")
            return None

        output_path = output_path.replace(".docx", ".pdf")  # ✅ Ensure PDF extension
        cleaned_doc.save(output_path)
        cleaned_doc.close()
        print(f"✅ Blank pages removed! Cleaned PDF saved at: {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ Error removing blank pages: {e}")
        return None


@app.route("/upload", methods=["GET", "POST"])
def upload_page():
    message = None

    if request.method == "POST":
        if "file" not in request.files:
            return render_template("upload.html", message="No file selected!")
        
        file = request.files["file"]
        if file.filename == "":
            message = "No file selected."
        elif not allowed_file(file.filename):
            message = "Invalid file type. Only PDF, DOC, and DOCX are allowed."
        else:
            # Save the uploaded file
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(file_path)
            print(f"📄 File uploaded: {file_path}")

            # Insert filename into the database
            try:
                query = "INSERT INTO fileupload (FileName) VALUES (%s)"
                cursor.execute(query, (file.filename,))
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"❌ Error inserting filename: {e}")
                message = "Database error while saving the file."

            # Convert DOCX to PDF if needed
            pdf_path = file_path
            if file.filename.lower().endswith(".docx"):
                converted_path = convert_docx_to_pdf(file_path)
                if converted_path:
                    pdf_path = converted_path

            if not os.path.exists(pdf_path):  
                return "PDF conversion failed.", 400

            cleaned_file_path = os.path.join(app.config["UPLOAD_FOLDER"], "cleaned_" + file.filename)
            cleaned_pdf = remove_blank_pages(pdf_path, cleaned_file_path)

            if cleaned_pdf:
                pdf_path = cleaned_pdf

            # Extract details
            bnw_count, color_count = detect_black_and_white_pages(pdf_path)
            orientation = detect_orientation(pdf_path)
            file_size_kb = get_file_size(pdf_path)
            paper_size = detect_paper_size(pdf_path)

            return redirect(url_for("autodetect_page", 
                                    file=os.path.basename(pdf_path), 
                                    bnw=bnw_count, 
                                    color=color_count, 
                                    orient=orientation, 
                                    file_size_kb=file_size_kb,
                                    paper_size=paper_size))

    return render_template("upload.html", message=message)

@app.route("/autodetect", methods=["GET", "POST"])
def autodetect_page():
    message = None
    filename = request.args.get("file", "")

    if request.method == "POST":
        filename = request.form.get("filename", filename)

    if not filename:
        return "No file name found.", 400

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    pdf_path = os.path.splitext(file_path)[0] + ".pdf"

    print(f"Serving file: {file_path}")
    print(f"PDF Path: {pdf_path}")

    # Convert DOCX to PDF if necessary
    if file_path.endswith(".docx") and not os.path.exists(pdf_path):
        try:
            pdfkit.from_file(file_path, pdf_path, options={"quiet": ""})
            print(f"Converted DOCX to PDF: {pdf_path}")
        except Exception as e:
            print(f"Error converting DOCX to PDF: {e}")

    # Convert parameters to correct types safely
    def safe_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
        
    page_count = get_pdf_page_count(pdf_path) or 0
    specific_pages = 0
    copies = 1
    color_name = None  

    bnw = safe_int(request.args.get("bnw"))
    color = safe_int(request.args.get("color"))

    if color > 0 and bnw > 0:
        color_name = "Mixed"
    elif color > 0:
        color_name = "Color"
    else:
        color_name = "Black & White"

    size = request.form.get("paper_size", request.args.get("paper_size", "Unknown"))
    orientation = request.form.get("orient", request.args.get("orient", "Unknown"))
    pages = "all"

    print(f"Received paper size: {size}")
    print(f"Received orientation: {orientation}")
    print(f"Received color: {color_name}")

    cursor = db.cursor()

    # Check if the record already exists in setapply
    cursor.execute("SELECT COUNT(*) FROM setapply WHERE file = %s", (filename,))
    (existing_count,) = cursor.fetchone()

    if existing_count == 0:
        query = """
            INSERT INTO setapply (file, Pages, specificPages, Copies, sizeName, colorName, orientName) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        values = (filename, pages, specific_pages, copies, size, color_name, orientation)
        cursor.execute(query, values)
        db.commit()
        print(f"✅ Inserted into setapply: {values}")
    else:
        print(f"⚠️ Skipped insert: {filename} already exists in setapply")

    # Insert or update into autodetect 
    cursor.execute("""
        INSERT INTO autodetect (filename, page_count, bnw, color, size, orientation, copies, pages)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        page_count=VALUES(page_count), bnw=VALUES(bnw), color=VALUES(color),
        size=VALUES(size), orientation=VALUES(orientation), copies=VALUES(copies), pages=VALUES(pages)
    """, (filename, page_count, bnw, color, size, orientation, copies, pages))
    db.commit()

    # Handle file deletion
    if request.method == "POST" and "delete" in request.form:
        filename = request.form.get("filename")
        if filename:
            try:
                cursor.execute("DELETE FROM fileupload WHERE FileName = %s", (filename,))
                db.commit()
                print(f"{filename} is deleted from database.")
                return redirect(url_for("upload_page"))
            except Exception as e:
                db.rollback()
                print(f"❌ Error deleting file: {e}")
                message = f"Error deleting record: {e}"
        else:
            message = "No filename provided for deletion."

    # Handle "Next" button
    if request.method == "POST" and "next" in request.form:
        return redirect(url_for("invoice_page", filename=filename))

    return render_template(
        "autodetect.html",
        bnw=bnw,
        color=color,
        orientation=orientation,
        size=size,
        filename=filename,
        page_count=page_count,
        message=message
    )

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def get_autodetect_data(filename):
    try:
        cursor = db.cursor(dictionary=True)
        query = """
            SELECT page_count, size, orientation
            FROM autodetect
            WHERE filename = %s
            LIMIT 1
        """
        cursor.execute(query, (filename,))
        result = cursor.fetchone()
        cursor.close()

        if result:
            return {
                "page_count": result.get("page_count", 0),
                "size": result.get("size", "Unknown"),
                "orientation": result.get("orientation", "Unknown")
            }
        else:
            return {
                "page_count": 0,
                "size": "Unknown",
                "orientation": "Unknown"
            }
    except Exception as e:
        print(f"❌ Error fetching autodetect data: {e}")
        return {
            "page_count": 0,
            "size": "Unknown",
            "orientation": "Unknown"
        }

@app.route("/invoice/<filename>", methods=["GET", "POST"])
def invoice_page(filename):
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    
    if not os.path.exists(file_path):
        return "File not found", 404

    # ✅ Run OCR analysis
    ocr_result = run_analysis(file_path)
    
    if not ocr_result:
        return "Error during OCR analysis", 500
    
    # ✅ Extract values
    color_pages = ocr_result["color_pages"]
    black_white_pages = ocr_result["black_white_pages"]
    pages_with_images = ocr_result["pages_with_images"]
    large_color_images = ocr_result["large_color_images"]
    colored_text_pages = ocr_result["colored_text_pages"]
    total_colored_text_instances = ocr_result["total_colored_text_instances"]


    autodetect_data = get_autodetect_data(filename)
    page_count = autodetect_data["page_count"]
    size = autodetect_data["size"]
    orientation = autodetect_data["orientation"]

    BNW_IMAGE_COST = 3.00
    COLOR_IMAGE_COST = 5.00
    COLOR_TEXT_COST = 1.00

    filteredPageCount = color_pages + black_white_pages

    if size == "Letter (short)":
        base_cost = 2.00
    elif size == "Legal (long)":
        base_cost = 3.00
    else:
        base_cost = 0.00  # Unknown or invalid size

    base = base_cost * page_count
    bnw_image_total = BNW_IMAGE_COST * black_white_pages
    colored_image_total = COLOR_IMAGE_COST * color_pages
    color_text_cost = COLOR_TEXT_COST * total_colored_text_instances

    total_cost = base + bnw_image_total + colored_image_total + color_text_cost

    # Handle delete request
    if request.method == "POST" and "custom" in request.form:
        cursor.execute("DELETE FROM setapply ORDER BY applyID DESC LIMIT 1")
        db.commit()
        return redirect(url_for("settings_page", filename=filename))

    return render_template("invoice.html",
                           filename=filename,
                           page_count=page_count,
                           size=size,
                           orientation=orientation,
                           pageCount=filteredPageCount,
                           base=base,
                           base_cost=base_cost,
                           bnwImageTotal=bnw_image_total,
                           bnw_image_cost=BNW_IMAGE_COST,
                           bnw_pages=black_white_pages,
                           coloredImageTotal=colored_image_total,
                           color_image_cost=COLOR_IMAGE_COST,
                           color_text_cost=color_text_cost,
                           coloredText=total_colored_text_instances,
                           copies=1,
                           color_pages=color_pages,
                           total_cost=total_cost)

# ====================== SETTINGS PAGE ===========================================
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    message = None
    filename = request.args.get("filename")
    if not filename:
        return "No filename provided.", 400

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    modified_path = os.path.join(app.config["MODIFIED_FOLDER"], filename) 
    pdf_path = os.path.splitext(file_path)[0] + ".pdf"

    print(f"Serving file: {file_path}")  
    print(f"PDF Path: {pdf_path}")  

    # Convert DOCX to PDF if necessary
    if file_path.endswith(".docx") and not os.path.exists(pdf_path):
        try:
            pdfkit.from_file(file_path, pdf_path)
            print(f"Converted DOCX to PDF: {pdf_path}")
        except Exception as e:
            print(f"Error converting DOCX to PDF: {e}")

    page_count = get_pdf_page_count(pdf_path) or 0   

    # Handle file deletion
    if request.method == "POST" and "delete" in request.form:
        try:
            cursor.execute("DELETE FROM fileupload ORDER BY fuID DESC LIMIT 1")
            db.commit()
            return redirect(url_for("upload_page"))
        except Exception as e:
            message = f"Error deleting record: {e}"

    # Print settings
    if request.method == "POST":
        if "print" in request.form:
            fileName = request.form.get("filename", "")
            pages = request.form.get("Pages", "")
            specific_pages = request.form.get("specificPages", "")
            copies = int(request.form.get("Copies", 1))
            sizeName = request.form.get("sizeName", "")
            colorName = request.form.get("colorName", "")
            orientName = request.form.get("orientName", "")

            if not (pages and copies and sizeName and colorName and orientName):
                message = "Please select all required fields."
            else:
                if pages == "custom":
                    pages = "custom"
                elif pages == "all":
                    specific_pages = ""

                try:
                    query = """INSERT INTO setapply (file, Pages, specificPages, Copies, sizeName, colorName, orientName)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)"""
                    cursor.execute(query, (fileName, pages, specific_pages, copies, sizeName, colorName, orientName))
                    db.commit()
                    print(" File inserted successfully:", fileName)
                except pymysql.Error as e:
                    db.rollback()
                    print(f" Database Insert Error: {e}")

                # Modify the file before printing
                selected_pages = determine_pages_to_display(pages, specific_pages, page_count)  
                modify_pdf(pdf_path, colorName, orientName, sizeName, copies, selected_pages)  

                if not os.path.exists(modified_path):
                    print(f" Error: Modified file not found → {modified_path}")
                    return "Modified file not found.", 400

                return redirect(url_for("preview_page", filename=filename))

    return render_template("settings.html", filename=filename, page_count=page_count, message=message)

# ====================== PREVIEW PAGE ===========================================
def sanitize_input(input_value):
    if input_value is None:
        return ""
    return str(input_value).strip()

def get_recent_apply_settings():
    try:
        cursor = db.cursor(dictionary=True)
        query = "SELECT * FROM setapply ORDER BY applyID DESC LIMIT 1"
        cursor.execute(query)
        settings = cursor.fetchone()
        cursor.close()

        if settings:
            return {
                "pages": settings.get('Pages', ''),
                "specific_pages": settings.get('specificPages', ''),
                "copies": settings.get('Copies', 1),
                "sizeName": settings.get('sizeName', 'Letter'),
                "colorName": settings.get('colorName', 'Black & White'),
                "orientName": settings.get('orientName', 'Portrait'),
                "apply_id": settings.get('applyID')
            }
        else:
            return {} 

    except mysql.connector.Error as e:
        return {"error": f"Database query failed: {str(e)}"}

@app.route('/recent_settings', methods=['GET'])
def recent_settings():
    settings = get_recent_apply_settings()
    return jsonify(settings)

@app.route("/preview", methods=["GET", "POST"])
def preview_page():
    filename = request.args.get("filename")
    if not filename:
        return "No filename provided.", 400

    # Fetch recent print settings
    settings = get_recent_apply_settings()
    if isinstance(settings, tuple):
        keys = ["pages", "specific_pages", "copies", "sizeName", "colorName", "orientName", "apply_id"]
        settings = dict(zip(keys, settings))

    if not settings:
        return "Settings not found.", 400

    print("Settings passed to template:", settings)

    # Extract settings
    pages = settings.get("pages")
    spages = settings.get("specific_pages")
    copies = int(settings.get("copies", 1))
    sizeName = settings.get("sizeName")
    colorName = settings.get("colorName")
    orientName = settings.get("orientName")
    applyID = settings.get("apply_id")

    copies = int(copies) if copies else 1

    modified_file_path = os.path.join("modified_prints", filename)
    pdf_path = os.path.splitext(modified_file_path)[0] + ".pdf"

    # Convert DOCX to PDF if necessary
    if not os.path.exists(pdf_path) and filename.endswith(".docx"):
        try:
            pdfkit.from_file(modified_file_path, pdf_path)
        except Exception as e:
            return f"Error converting DOCX to PDF: {e}", 500

    # Total pages in the PDF
    totalPageCount = count_pdf_pages(pdf_path)

    # Determine pages to display
    pagesToDisplay = determine_pages_to_display(pages, spages, totalPageCount)
    filteredPageCount = len(pagesToDisplay)

    # Run OCR analysis
    ocrResult = run_ocr_analysis(pdf_path, pagesToDisplay)

    # Extract OCR results
    colorPages = ocrResult.get("color_pages", 0)
    blackWhitePages = ocrResult.get("black_white_pages", 0)
    pagesWithImages = ocrResult.get("pages_with_images", 0)
    total_colored_text_instances = ocrResult.get("total_colored_text_instances", 0)
    colored_text_pages = ocrResult.get("colored_text_pages", 0)
    largeColorImages = ocrResult.get("large_color_images", 0)
    
    pageImage = colorPages

    # Calculate price
    priceBreakdown = calculate_price(
        colorPages, blackWhitePages, pageImage, colorName, sizeName, copies,
        total_colored_text_instances, colored_text_pages, largeColorImages
    )

    # Extract price details
    base_cost = priceBreakdown.get('base_cost', 0)
    page_cost = priceBreakdown.get('page_cost', 0)
    colored_text_price = priceBreakdown.get('colored_text_price', 0)
    image_cost_per_page = priceBreakdown.get('image_cost_per_page', 0)
    large_color_images_cost = priceBreakdown.get('large_color_images_cost', 0)
    image_cost = priceBreakdown.get('image_cost', 0)
    totalPrice = priceBreakdown['total_cost']

    # Handle delete request
    if request.method == "POST" and "delete" in request.form:
        cursor.execute("DELETE FROM setapply ORDER BY applyID DESC LIMIT 1")
        db.commit()
        return redirect(url_for("settings_page", filename=filename))

    # Render the preview page with relevant settings
    return render_template(
        "preview.html",
        filename=filename,
        page_count=filteredPageCount,
        applyID=applyID,
        sizeName=sizeName,
        colorName=colorName,
        orientName=orientName,
        copies=copies,
        total_colored_text_instances=total_colored_text_instances,
        colored_text_pages=colored_text_pages,
        large_color_images_cost=large_color_images_cost,
        page_cost=page_cost,
        base_cost=base_cost,
        colored_text_price=colored_text_price,
        image_cost_per_page=image_cost_per_page,
        totalPrice=totalPrice,
        filteredPageCount=filteredPageCount,
        largeColorImages=largeColorImages,
        pagesWithImages=pagesWithImages,
        image_cost=image_cost,
        pageImage=pageImage
    )

# ====================== OCR ANALYSIS ===========================================
def run_ocr_analysis(pdf_path, pagesToDisplay):
    try:
        command = ["python", "ocr_analysis.py", pdf_path, " ".join(map(str, pagesToDisplay))]
        output = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
        return json.loads(output) if output else {}
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"OCR Error: {e}")
        return {}

    except Exception as e:
        print(f"⚠️ OCR analysis failed: {e}")
        return {}
    
def calculate_price(color_pages, black_white_pages, pages_with_images, colorName, sizeName, copies, total_colored_text_instances, colored_text_pages, large_color_images):
    short_page_cost = 2.00
    long_page_cost = 3.00
    
    # Colored text pricing
    colored_text_price = 1.00
    if colorName != "Black & White":
        if total_colored_text_instances > 0:
            colored_text_price = 2.00 if total_colored_text_instances <= 2 else 3.00
    
    # Image costs
    image_cost_per_page = 3.00 if colorName == "Black & White" else 5.00
    
    # Determine page cost based on size (short or long)
    page_cost = long_page_cost if sizeName == "Legal (long)" else short_page_cost
    
    # Base cost calculation: page costs (black & white + color)
    base_cost = (color_pages + black_white_pages) * page_cost

    pageImage = color_pages

    # Image-related costs: how many pages have images, including large images
    image_cost = pageImage * image_cost_per_page
    large_color_images_cost = large_color_images * image_cost_per_page

    # IMAGE COST 
    if image_cost > 0:
        image_cost_to_add = image_cost
    else:
        image_cost_to_add = large_color_images_cost

    # Total cost before considering the number of copies
    total_cost_before_copies = base_cost + image_cost + colored_text_price

    
    # Final cost, considering the number of copies
    total_cost = total_cost_before_copies * copies
    
    
    print(f"Color Pages: {color_pages}, B/W Pages: {black_white_pages}")
    print(f"Pages with Images: {pages_with_images}, Large Color Images: {large_color_images}")
    print(f"Base Cost: {base_cost}, Image Cost: {image_cost}, PAGES: {pageImage}")
    print(f"Colored Text Price: {colored_text_price}")
    print(f"Total Cost Before Copies: {total_cost_before_copies}")
    print(f"Total Cost After Copies: {total_cost}")
    
    return {
        "base_cost": base_cost,
        "image_cost": image_cost,
        "large_color_images_cost": large_color_images_cost,
        "colored_text_price": colored_text_price,
        "total_cost_before_copies": total_cost_before_copies,
        "total_cost": total_cost,
        "page_cost": page_cost,
        "image_cost_per_page": image_cost_per_page,
        "pageImage": pageImage
    }

def count_pdf_pages(pdf_path):
    """Counts total pages in a PDF."""
    try:
        with fitz.open(pdf_path) as doc:
            return len(doc)
    except Exception as e:
        print(f"Error counting pages: {e}")
        return 0

def determine_pages_to_display(pages, spages, totalPageCount):
    pagesToDisplay = []

    if pages == "custom" and spages:
        pagesRange = spages.split(',')
        for range_item in pagesRange:
            if "-" in range_item:
                start, end = map(int, range_item.split('-'))
                pagesToDisplay.extend(range(start, end + 1))
            else:
                pagesToDisplay.append(int(range_item))
    else:
        pagesToDisplay = list(range(1, totalPageCount + 1))

    return [p for p in pagesToDisplay if 1 <= p <= totalPageCount]

# ====================== PAYMENT PROCESS ===========================================
@app.route("/payment_success")
def payment_success():
    file_name = request.args.get("file_name", "")

    if not file_name:
        return render_template("payment_success.html", print_status="Error: No file name provided.")

    print_response = requests.get(f"http://127.0.0.1:5000/print/{file_name}")

    return render_template(
        "payment_success.html",
        print_status=print_response.text if print_response.status_code == 200 else "Print failed."
    )


@app.route("/payment_error")
def payment_error():
    return render_template(
                "error_payment.html"
            )

@app.route('/delete_setapply', methods=['POST'])
def delete_setapply():
    try:
        cursor.execute("DELETE FROM setapply")
        db.commit()
        print("🗑️ setapply table cleared successfully.")
        return jsonify({"success": True})
    except Exception as e:
        print(f"❌ Error deleting setapply: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/pay", methods=["POST"])
def process_payment():
    try:
        data = request.form

        # Retrieve payment details
        file_name = data.get("file_name", "")
        pageCount = int(data.get("pageCount") or 0)
        copies = int(data.get("copies") or 1)
        sizeName = data.get("sizeName", "")
        colorName = data.get("colorName", "")
        orientName = data.get("orientName", "")
        totalPrice = float(data.get("totalPrice") or 0.00)
        applyID = int(data.get("applyID") or 0)

        print("Received payment request...")

        cursor.execute("SELECT TransacID FROM payment WHERE applyID = %s AND status = 'Pending'", (applyID,))
        existing_payment = cursor.fetchone()

        if existing_payment:
            return render_template("error_payment.html", message="You already have a pending payment. Please complete or cancel it before proceeding.")

        cursor.execute("""
            INSERT INTO transaction (file, pageCount, Copies, sizeName, colorName, orientName, totalCost, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending', NOW())
        """, (file_name, pageCount, copies, sizeName, colorName, orientName, totalPrice))

        transacID = cursor.lastrowid  # Get last inserted ID
        print(f"Transaction inserted with ID: {transacID}")  

        cursor.execute("""
            INSERT INTO payment (TransacID, applyID, totalCost, status)
            VALUES (%s, %s, %s, 'Pending')
        """, (transacID, applyID, totalPrice))

        print(" Inserting into notifications table...")  
        notification_message = f"A new transaction has been made with file '{file_name}' and total cost of {totalPrice:.2f} pesos."
        cursor.execute("""
            INSERT INTO notifications (message, TransacID, NotifStatus, status)
            VALUES (%s, %s, 'unread', 'Pending')
        """, (notification_message, transacID))

        db.commit()
        print(" Database transaction committed.")  

        print(" Processing payment through PayPal...")  
        payment_result = subprocess.run(
            ["python3", "payment.py", str(totalPrice)], capture_output=True, text=True
        )

        if "success" in payment_result.stdout.lower():
            print(" Payment successful. Updating database status...")  
            cursor.execute("UPDATE transaction SET status = 'Success' WHERE TransacID = %s", (transacID,))
            cursor.execute("UPDATE payment SET status = 'Success' WHERE TransacID = %s", (transacID,))
            db.commit()

            print(" Sending file to printer...")  
            return redirect(url_for("payment_success"))

        else:
            print(" Payment failed. Rolling back transaction...")  
            cursor.execute("UPDATE transaction SET status = 'Failed' WHERE TransacID = %s", (transacID,))
            cursor.execute("UPDATE payment SET status = 'Failed' WHERE TransacID = %s", (transacID,))
            db.commit()
            return redirect(url_for("payment_error"))

    except mysql.connector.Error as db_err:
        db.rollback()
        print(f" Database error: {db_err}")  
        return jsonify({"error": str(db_err)}), 500

    except Exception as e:
        db.rollback()
        print(f" Error processing payment: {e}")  
        return jsonify({"error": str(e)}), 500

# ====================== PRINTING ===========================================
PRINTER_NAME = "HPB405041"

def get_print_job_status():
    try:
        printer_handle = win32print.OpenPrinter(PRINTER_NAME)
        job_info = win32print.EnumJobs(printer_handle, 0, -1, 1)

        if job_info:
            active_jobs = False
            for job in job_info:
                job_status = job["Status"]

                if job_status & win32print.JOB_STATUS_PRINTING:
                    win32print.ClosePrinter(printer_handle)
                    return "Printing"
                
                elif job_status & win32print.JOB_STATUS_ERROR:
                    win32print.ClosePrinter(printer_handle)
                    return "Error"

                elif job_status & win32print.JOB_STATUS_COMPLETED:
                    active_jobs = True

            win32print.ClosePrinter(printer_handle)

            if active_jobs:
                return "Printed"  # Job detected as completed
            else:
                return "idle"  # No active jobs

        win32print.ClosePrinter(printer_handle)
        return "Idle"

    except Exception as e:
        return f"error: {str(e)}"

@app.route('/printer_status')
def printer_status():
    status = get_print_job_status()
    return jsonify({"status": status})


@app.route("/print_success")
def print_success():
    filename = request.args.get("filename", "")
    return render_template("print_success.html", message=f"Print job for '{filename}' sent successfully!")

@app.route("/error_print")
def error_print():
    message = request.args.get("message", "")
    return render_template("error_print.html", message=message)

def clear_cursor():
    try:
        if cursor.with_rows:  # Only fetch if there are results
            cursor.fetchall()
    except Exception as e:
        print(f"⚠️ Cursor clear error: {e}")

def get_copies_from_db(filename):
    clear_cursor()  # Ensure previous queries are cleared

    query = "SELECT Copies FROM setapply WHERE file = %s"
    cursor.execute(query, (filename,))
    result = cursor.fetchone()

    if result and 'Copies' in result:
        try:
            copies = int(result['Copies']) if result['Copies'] is not None else 1
            print(f"🛠️ Copies retrieved from DB for '{filename}': {copies}")
            return copies
        except (ValueError, TypeError):
            print(f"❌ Error: Invalid value for copies in DB for '{filename}'. Defaulting to 1.")
            return 1
    else:
        print(f"❌ No result or 'Copies' key found for '{filename}'. Defaulting to 1.")
        return 1


def getOrient(filename):
    query = "SELECT orientName FROM setapply WHERE file = %s"
    cursor.execute(query, (filename,))
    result = cursor.fetchone()

    if not result: 
        print(f"❌ No orientation found for '{filename}', defaulting to Portrait.")
        return "Portrait"

    orientName = result.get('orientName') 

    if not orientName: 
        print(f"❌ Orientation in DB is NULL for '{filename}', defaulting to Portrait.")
        return "Portrait"

    orientName = str(orientName).strip().capitalize()
    print(f"🛠️ Orientation retrieved: {orientName}")

    return orientName

def getColor(filename):
    clear_cursor()
    query = "SELECT colorName FROM setapply WHERE file = %s"
    cursor.execute(query, (filename,))
    result = cursor.fetchone()

    if result and 'colorName' in result:
        colorName = result['colorName'].strip().lower()
        return colorName
    return "Black & White"

def get_selected_pages(filename):
    query = "SELECT specificPages FROM setapply WHERE file = %s"

    try:
        cursor = db.cursor(buffered=True)  # Buffered cursor to avoid unread results
        cursor.execute(query, (filename,))
        result = cursor.fetchone()
        cursor.close()  # Explicitly close cursor to avoid conflicts

        print(f"🔍 Raw Query Result for '{filename}': {result}")

        if not result:
            print(f"❌ No matching record found in 'setapply' for file '{filename}'.")
            return None  

        # Extract specific pages safely
        specific_pages = result['specificPages'] if isinstance(result, dict) else result[0]
        
        if not specific_pages:  # Ensure no errors if specificPages is None
            print(f"⚠️ 'specificPages' is None or empty for '{filename}', returning None.")
            return None

        try:
            selected_pages = [int(p.strip()) for p in specific_pages.split(',') if p.strip().isdigit()]
            print(f"✅ Selected pages for '{filename}': {selected_pages}")
            return selected_pages if selected_pages else None  # Ensure empty list doesn't default to all
        except ValueError:
            print(f"⚠️ Invalid page format stored in DB for '{filename}', defaulting to all pages.")
            return None
    except mysql.connector.Error as err:
        print(f"❌ MySQL Error: {err}")
        return None
    finally:
        if db.is_connected():
            db.commit()

def selected_pages(filename):
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"❌ File not found: {file_path}")
    
    doc = fitz.open(file_path)
    modified_doc = fitz.open()
    pages = get_selected_pages(filename)

    if pages is None:
        pages = list(range(1, len(doc) + 1))  # Default to all pages

    for page_num in pages:
        if 1 <= page_num <= len(doc):
            page = doc[page_num - 1]
            new_page = modified_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.show_pdf_page(new_page.rect, doc, page_num - 1)

    return pages  # ✅ Return pages for printing

def convert_to_grayscale(pdf_path, output_path):
    doc = fitz.open(pdf_path)

    for page_index in range(len(doc)):
        page = doc[page_index]
        images = page.get_images(full=True)  # Get all images on the page

        for img in images:
            xref = img[0]  # Image reference number
            pix = fitz.Pixmap(doc, xref)  # Get image
            
            if pix.n > 1:  # Convert only if the image is colored
                gray_pix = fitz.Pixmap(fitz.csGRAY, pix)  # Convert to grayscale

                # Convert to bytes and insert as a new image
                img_rect = page.get_image_rects(xref)[0]  # Get the image's bounding box
                img_bytes = gray_pix.tobytes("png")  # Convert to PNG format
                
                # Remove old image and insert new grayscale image
                page.insert_image(img_rect, stream=img_bytes)
                print(f"🖼️ Replaced image {xref} with grayscale version.")

    doc.save(output_path)
    doc.close()
    print(f"✅ Successfully converted images to grayscale: {output_path}")

@app.route("/print/<filename>", methods=["GET", "POST"])
def print_file(filename):
    result = getOrient(filename)
    color = getColor(filename)
    copies = get_copies_from_db(filename)
    pages = selected_pages(filename)

    if pages is None or len(pages) == 0:
        print("⚠️ No pages specified, defaulting to all.")
        pages_str = 'all'
    else:
        pages_str = ','.join(map(str, pages))
        print(f"📄 Printing selected pages: {pages_str}")

    orientation_flag = 'Landscape' if result == 'Landscape' else 'Portrait'
    print(f"🛠️ Printing in {orientation_flag} orientation")

    original_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    grayscale_path = os.path.join(app.config["UPLOAD_FOLDER"], f"grayscale_{filename}")

    # Convert to grayscale if user selects black & white
    if color.lower() == "black & white":
        convert_to_grayscale(original_path, grayscale_path)
        modified_path = grayscale_path
    else:
        modified_path = original_path

    sumatra_path = r"C:\xampp\htdocs\PNP\SumatraPDF-3.5.2-64.exe"
    printer_name = "HPB405041"
    print_settings = f"{copies}x, {pages_str}, {orientation_flag}, {color}"

    print(f"🖨️ Sending '{modified_path}' to printer: {printer_name} with {copies} copies and orientation {orientation_flag}")

    if not os.path.exists(modified_path):
        return f"❌ Modified file not found: {modified_path}", 400

    try:
        if modified_path.endswith(".pdf"):
            command = f'-print-to "{printer_name}" -print-settings "{print_settings}" "{modified_path}"'
            print(f"🖨️ SumatraPDF Command: {command}")
            win32api.ShellExecute(0, "open", sumatra_path, command, ".", 0)
        elif modified_path.endswith(".docx"):
            win32api.ShellExecute(0, "print", modified_path, None, ".", 0)
        else:
            return "❌ Unsupported file type", 400

        return f"✅ Print job for '{filename}' sent successfully with {copies} copies!", 200

    except Exception as e:
        return f"❌ Print error: {e}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
