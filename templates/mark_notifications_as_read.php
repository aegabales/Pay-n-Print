<?php
// mark_notifications_as_read.php

include 'includes/config.php';

// Get the POST data
$data = json_decode(file_get_contents('php://input'), true);

if ($data['action'] === 'mark_as_read') {
    // Prepare the query to update notifications as read
    $query = "UPDATE notifications SET NotifStatus = 'read' WHERE NotifStatus = 'unread'";

    if (mysqli_query($mysqli, $query)) {
        echo json_encode(['success' => true]);
    } else {
        echo json_encode(['success' => false, 'message' => mysqli_error($mysqli)]);
    }
}
