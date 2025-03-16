<?php 
require 'vendor/autoload.php';

use PhpOffice\PhpWord\IOFactory;
use PhpOffice\PhpWord\Settings;
use setasign\Fpdi\Fpdi;

include 'includes/config.php';

function sanitize_input($data) {
    global $mysqli;
    return mysqli_real_escape_string($mysqli, trim($data));
}

// iretrive a recent apply settings
$query = "SELECT * FROM setapply ORDER BY applyID DESC LIMIT 1";
$result = $mysqli->query($query);

if (!$result) {
    die("Query failed: " . $mysqli->error);
}

$settings = $result->fetch_assoc();

if ($settings) {
    $pages = sanitize_input($settings['Pages']);
    $spages = sanitize_input($settings['specificPages']);
    $copies = sanitize_input($settings['Copies']);
    $sizeName = sanitize_input($settings['sizeName']);
    $colorName = sanitize_input($settings['colorName']);
    $orientName = sanitize_input($settings['orientName']);
    $applyID = $settings['applyID']; // Retrieve applyID from setapply
} else {
    die("Settings not found.");
}

// iretrieve a recent file
$query = "SELECT FileName FROM fileupload ORDER BY fuID DESC LIMIT 1";
$result = $mysqli->query($query);

if (!$result) {
    die("Query failed: " . $mysqli->error);
}

$file = $result->fetch_assoc();
$file_name = sanitize_input($file['FileName'] ?? '');

if (empty($file_name)) {
    die("No file uploaded.");
}

$file_path = 'uploads/' . $file_name;
$pdf_path = 'uploads/' . pathinfo($file_name, PATHINFO_FILENAME) . '.pdf';

if (!file_exists($pdf_path)) {
    if ($file_name && pathinfo($file_name, PATHINFO_EXTENSION) === 'docx') {
        $phpWord = IOFactory::load($file_path, 'Word2007');

        Settings::setPdfRendererPath('./vendor/dompdf/dompdf');
        Settings::setPdfRendererName('DomPDF');

        try {
            $pdfWriter = IOFactory::createWriter($phpWord, 'PDF');
            $pdfWriter->save($pdf_path);
        } catch (Exception $e) {
            die("Error generating PDF: " . $e->getMessage());
        }
    } else {
        die("PDF file not found.");
    }
}

if (isset($_POST['delete'])) {
    $query = "DELETE FROM setapply ORDER BY applyID DESC LIMIT 1";
    if ($mysqli->query($query) === TRUE) {
        header("Location: settings.php?file=$file_name");
        exit();
    } else {
        echo "Error deleting record: " . $mysqli->error;
    }
}

// For page count
$pdf = new Fpdi();
$pdf->setSourceFile($pdf_path);
$pageCount = 0;

while (true) {
    try {
        $pdf->importPage($pageCount + 1);
        $pageCount++;
    } catch (\Exception $e) {
        break;
    }
}

// OCR Analysis
$command = escapeshellcmd("python3 includes/ocr_analysis.py $pdf_path");
$output = shell_exec($command . ' 2>&1');

if (!$output) {
    die("Error executing OCR script. Output is empty.");
}

$ocrResult = json_decode($output, true);

if (json_last_error() !== JSON_ERROR_NONE) {
    die("OCR analysis failed: " . json_last_error_msg() . ". Output: " . $output);
}

if (!$ocrResult) {
    die("OCR analysis failed. Output: " . $output);
}

// Extract OCR results sa ocr_analysis
$colorPages = $ocrResult['color_pages'] ?? 0;
$blackWhitePages = $ocrResult['black_white_pages'] ?? 0;
$largeColorImages = $ocrResult['large_color_images'] ?? 0;

function calculatePrice($colorPages, $blackWhitePages, $largeColorImages, $sizeName, $copies, $colorMode) {
    $colorPageCost = ($colorMode == 'Black & White') ? 3.00 : 5.00;
    $bwPageCost = 2.00;    
    $legalSizeExtraCost = 2.00; 
    $largeColorImageExtraCost = 5.00; 

    // Base costs
    $baseCost = ($colorPages * $colorPageCost) + ($blackWhitePages * $bwPageCost);

    // Extra cost for large color images
    $largeColorImagesCost = $largeColorImages * $largeColorImageExtraCost;

    // Paper size adjustment
    $paperSizeCost = ($sizeName == 'Legal (long)') ? ($colorPages + $blackWhitePages) * $legalSizeExtraCost : 0;


    $totalCostBeforeCopies = $baseCost + $largeColorImagesCost + $paperSizeCost;
    $totalCost = $totalCostBeforeCopies * $copies; // amo ni  ang final calculation (makita sa invoice)

    return [
        'baseCost' => $baseCost,
        'largeColorImagesCost' => $largeColorImagesCost,
        'paperSizeCost' => $paperSizeCost,
        'totalCost' => $totalCost
    ];
}

// Calculate
$priceBreakdown = calculatePrice($colorPages, $blackWhitePages, $largeColorImages, $sizeName, $copies, $colorName);
$totalPrice = $priceBreakdown['totalCost'];

// para sa pay button
if (isset($_POST['pay'])) {
    $transacID = 0;
    $mysqli->autocommit(FALSE);
    $mysqli->begin_transaction();

    $query = "INSERT INTO transaction (file, pageCount, Copies, sizeName, colorName, orientName, totalCost, status, created_at) 
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', NOW())";
    $stmt = $mysqli->prepare($query);
    $stmt->bind_param('sisssss', $file_name, $pageCount, $copies, $sizeName, $colorName, $orientName, $totalPrice);

    if ($stmt->execute()) {
        $transacID = $mysqli->insert_id;

        $query = "INSERT INTO payment (TransacID, applyID, totalCost, status) VALUES (?, ?, ?, 'Pending')";
        $stmt = $mysqli->prepare($query);
        $stmt->bind_param('iid', $transacID, $applyID, $totalPrice);
        
        if ($stmt->execute()) {
            $notification_message = "A new transaction has been made with file '$file_name' and total cost of " . number_format($totalPrice, 2) . " pesos.";
            $query = "INSERT INTO notifications (message, TransacID, NotifStatus, status) VALUES (?, ?, 'unread', 'Pending')";
            $stmt = $mysqli->prepare($query);
            $stmt->bind_param('si', $notification_message, $transacID);

            if ($stmt->execute()) {
                $command = escapeshellcmd("python3 payment.py " . escapeshellarg($totalPrice));
                $output = shell_exec($command . ' 2>&1');
                echo "Transaction and payment records inserted successfully. Python output: $output";
            } else {
                echo "Error inserting notification record: " . $mysqli->error;
            }
        } else {
            echo "Error inserting payment record: " . $mysqli->error;
        }
    } else {
        echo "Error inserting transaction record: " . $mysqli->error;
    }

    $mysqli->commit();
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pay 'N Print - Preview</title>
    <link rel="stylesheet" href="css/preview.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.10.377/pdf.min.js"></script>
</head>
<body>
    <div class="main">
        <div class="content">
            <section class="pdf">
                <div class="preview-pane">
                    <?php if (file_exists($pdf_path)) { ?>
                        <div id="pdfContainer"></div>
                    <?php } else { ?>
                        <p>No file to preview. Try uploading again.</p>
                    <?php } ?>
                </div>
            </section>

            <section>
                <div class="settings-pane">
                    <div class="header-sp">
                        <h2>Settings</h2>
                        <h5>
                            <?php
                            echo isset($pageCount) ? $pageCount . ' sheet' . ($pageCount > 1 ? 's' : '') . ' of paper' : 'Page count not available';
                            ?>
                        </h5>
                    </div>
                    <label class="page">Page(s):</label>
                    <div class="checkbox-container">
                        <label>
                            <input type="radio" id="allPages" name="Pages" <?php echo ($pages === 'all') ? 'checked' : ''; ?> disabled> All pages
                        </label>
                    </div>

                    <div class="custom">
                        <label>
                            <input type="radio" name="Pages" value="custom" <?php echo ($pages === 'custom') ? 'checked' : ''; ?> disabled>
                            <input type="text" id="specificPages" name="specificPages" value="<?php echo htmlspecialchars($spages); ?>" disabled>
                        </label>
                    </div>

                    <div class="form-field-input">
                        <input type="number" id="copies" name="Copies" min="1" value="<?php echo htmlspecialchars($copies); ?>" disabled>
                        <label>Copies</label>
                    </div>

                    <div class="form-field">
                        <div class="form-select">
                            <div class="custom-select">
                                <label>Paper Size</label>
                                <select id="psID" name="sizeName" disabled>
                                    <?php
                                    $size = $mysqli->query('SELECT * FROM setapply');
                                    if ($size) {
                                        while ($sizes = $size->fetch_object()) {
                                            echo "<option value='{$sizes->applyID}'>{$sizes->sizeName}</option>";
                                        }
                                    }
                                    ?>
                                </select>
                            </div>

                            <div class="custom-select">
                                <label>Color Mode</label>
                                <select id="colorID" name="colorName" disabled>
                                    <?php
                                    $color = $mysqli->query('SELECT * FROM setapply');
                                    if ($color) {
                                        while ($col = $color->fetch_object()) {
                                            echo "<option value='{$col->applyID}'>{$col->colorName}</option>";
                                        }
                                    }
                                    ?>
                                </select>
                            </div>

                            <div class="custom-select">
                                <label>Print Orientation</label>
                                <select id="orientID" name="orientName" disabled>
                                    <?php
                                    $orientation = $mysqli->query('SELECT * FROM setapply');
                                    if ($orientation) {
                                        while ($orient = $orientation->fetch_object()) {
                                            echo "<option value='{$orient->applyID}'>{$orient->orientName}</option>";
                                        }
                                    }
                                    ?>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
                <form method="post" action="">
                    <button class="delete-btn" type="submit" name="delete" >Go Back</button>
                </form>
                <button id="open-popup">View Invoice</button>              
            </section>
        </div>
    </div>

    <div class="popup">
        <button class="close-btn">&times;</button>
        <div class="receipt">
            <h2>INVOICE</h2>
            <p>****************************************</p>
            <h3>Print Job Details</h3>
            <div class="receipt-item">
                <span>File Name:</span>
                <span><?php echo htmlspecialchars($file_name); ?></span>
            </div>
            <div class="receipt-item">
                <span>Page Count:</span>
                <span><?php echo htmlspecialchars($pageCount); ?></span>
            </div>
            <div class="receipt-item">
                <span>Paper Size:</span>
                <span><?php echo htmlspecialchars($sizeName); ?></span>
            </div>
            <div class="receipt-item">
                <span>Color Mode:</span>
                <span><?php echo htmlspecialchars($colorName); ?></span>
            </div>
            <div class="receipt-item">
                <span>Print Orientation:</span> <br> <br>  
                <span><?php echo htmlspecialchars($orientName); ?></span>
            </div>

            <!-- Price Breakdown -->
            <h3>Price Breakdown</h3>
            <div class="receipt-item">
                <span>Base Cost (Color Pages):</span>
                <span><?php echo number_format($priceBreakdown['baseCost'], 2); ?> pesos</span>
            </div>
            <div class="receipt-item">
                <span>Extra Cost (Images):</span>
                <span><?php echo number_format($priceBreakdown['largeColorImagesCost'], 2); ?> pesos</span>
            </div>
            <div class="receipt-item">
                <span>Paper Size Adjustment:</span>
                <span><?php echo number_format($priceBreakdown['paperSizeCost'], 2); ?> pesos</span>
            </div>
            <div class="receipt-item total">
                <span>Total cost for <?php echo htmlspecialchars($copies); ?> copies:</span>
                <span><?php echo number_format($totalPrice, 2); ?> pesos</span>
            </div>
            <form method="post" action="">
                    <button class="pay-btn" type="submit" name="pay">Pay</button>
                </form>
        </div>
    </div>

    <script>
        document.querySelector("#open-popup").addEventListener("click",function(){
            document.body.classList.add("active-popup");
        });

        document.querySelector(".popup .close-btn").addEventListener("click",function(){
            document.body.classList.remove("active-popup");
        });


        document.addEventListener('DOMContentLoaded', function() {
            const pdfPath = "<?php echo $pdf_path; ?>";
            const paperSize = "<?php echo $sizeName; ?>";
            const colorMode = "<?php echo $colorName; ?>";
            const orientation = "<?php echo $orientName; ?>";

            console.log("Loading PDF from path: ", pdfPath);
            loadPDF(pdfPath, paperSize, colorMode, orientation);
        });


        function loadPDF(url, paperSize, colorMode, orientation) {
            const pdfContainer = document.getElementById('pdfContainer');

            if (!pdfContainer) {
                console.error('pdfContainer element not found');
                return;
            }

            pdfContainer.innerHTML = '';

            pdfjsLib.getDocument(url).promise.then(pdf => {
                console.log('PDF loaded successfully:', pdf);
                let pageNumber = 1;
                const renderNextPage = () => {
                    pdf.getPage(pageNumber).then(page => {
                        let canvas = document.createElement('canvas');
                        canvas.id = 'page' + pageNumber;
                        canvas.style.margin = '10px 0';
                        canvas.style.border = '2px solid #ccc';
                        pdfContainer.appendChild(canvas);

                        renderPage(page, canvas, paperSize, orientation, colorMode);

                        pageNumber++;
                        if (pageNumber <= pdf.numPages) {
                            renderNextPage();
                        }
                    }).catch(error => {
                        console.error('Error rendering page:', error);
                    });
                };

                renderNextPage();
            }).catch(error => {
                console.error('Error loading PDF:', error);
            });
        }

        function renderPage(page, canvas, paperSize, orientation, colorMode) {
            let desiredWidth, desiredHeight;

            if (paperSize === 'Legal (long)') {
                desiredWidth = orientation === 'Landscape' ? 1344 : 816;
                desiredHeight = orientation === 'Landscape' ? 816 : 1344;
            } else {
                desiredWidth = orientation === 'Landscape' ? 1056 : 816;
                desiredHeight = orientation === 'Landscape' ? 816 : 1056;
            }

            const viewport = page.getViewport({ scale: 1 });
            const scale = Math.min(desiredWidth / viewport.width, desiredHeight / viewport.height);

            const offsetX = (desiredWidth - viewport.width * scale) / 2;
            const offsetY = (desiredHeight - viewport.height * scale) / 2;

            canvas.width = desiredWidth;
            canvas.height = desiredHeight;

            const scaledViewport = page.getViewport({ scale: scale });
            const context = canvas.getContext('2d');

            context.clearRect(0, 0, canvas.width, canvas.height);
            context.setTransform(1, 0, 0, 1, 0, 0);

            page.render({
                canvasContext: context,
                viewport: scaledViewport,
                transform: [1, 0, 0, 1, offsetX, offsetY]
            }).promise.then(() => {
                context.setTransform(1, 0, 0, 1, 0, 0);
                if (colorMode === 'Black & White') {
                    convertCanvasToBlackAndWhite(canvas);
                }
            }).catch(console.error);
        }

        function convertCanvasToBlackAndWhite(canvas) {
            const context = canvas.getContext('2d');
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            const data = imageData.data;

            for (let i = 0; i < data.length; i += 4) {
                const brightness = (data[i] + data[i + 1] + data[i + 2]) / 3;
                data[i] = data[i + 1] = data[i + 2] = brightness;
            }

            context.putImageData(imageData, 0, 0);
        }

        document.querySelector(".pay-btn").addEventListener("click", function() {
            fetch('updateTransac.php', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: 'action=updateStatus'
            })
            .then(response => response.text())
            .then(result => {
                console.log(result);
                alert("Transaction status updated.");
            })
            .catch(error => {
                console.error('Error:', error);
            });
        });
    </script>
</body>
</html>