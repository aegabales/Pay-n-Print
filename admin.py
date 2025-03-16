from flask import Flask, render_template, request, redirect, url_for, session, flash, Blueprint, current_app
from werkzeug.utils import secure_filename
from datetime import datetime, timezone,  timedelta
from flask import current_app
import mysql.connector
import os
import time

# Define the blueprint for admin routes
admin_bp = Blueprint('admin', __name__, static_folder='static')

# Database Configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'pnp'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

#========================== ADMIN LOGIN ======================================
@admin_bp.route('/', methods=['GET', 'POST'])
def login():
    session['AdminID'] = 1

    if request.method == 'POST':
        username = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = "SELECT AdminID, AdminName FROM users WHERE email = %s AND password = %s"
        cursor.execute(query, (username, password))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user:
            session['AdminID'] = user['AdminID']
            session['AdminName'] = user['AdminName']
            session['AdminPhoto'] = user.get('profile_photo', 'default.png')
            return redirect(url_for('admin.admindb'))
        else:
            return render_template('adminlogin.html', error="Invalid username or password.")

            
    return render_template('adminlogin.html')

#========================== ADMIN DASHBOARD ======================================
@admin_bp.route('/admindb', methods=['GET', 'POST'])
def admindb():
    if 'AdminID' not in session:
        return redirect(url_for('admin.login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch admin profile
    user_id = session.get('AdminID', 1)
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()
    
    if request.method == 'POST' and 'update-btn' in request.form:
        new_name = request.form.get('AdminName', '').strip()
        profile_photo = user['profile_photo']

        # Handle profile photo upload
        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and file.filename != '':
                allowed_types = {'image/jpeg', 'image/png', 'image/gif'}
                if file.mimetype in allowed_types:
                    filename = secure_filename(file.filename)

                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
                    os.makedirs(upload_folder, exist_ok=True)

                    file_path = os.path.join(upload_folder, filename)  # Save in static/uploads
                    file.save(file_path)
                    profile_photo = filename
                else:
                    # Return with error if file type is invalid
                    return render_template('adminuser.html', user=user, error="Invalid file type.")
                
        try:
            cursor.execute("UPDATE users SET AdminName = %s, profile_photo = %s WHERE AdminID = %s", (new_name, profile_photo, user_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error updating profile: {e}")
            return render_template('adminuser.html', user=user, error="An error occurred while updating.")

    sales_date = request.form.get('sales_date', datetime.today().strftime('%Y-%m-%d'))

    sales_query = """
        SELECT SUM(totalCost) AS totalSales 
        FROM payment 
        WHERE DATE(date) = %s AND status = 'success'
    """
    cursor.execute(sales_query, (sales_date,))
    sales_result = cursor.fetchone()
    total_sales = sales_result['totalSales'] if sales_result and sales_result['totalSales'] is not None else 0

    period = request.form.get('period', 'this_month')
    today = datetime.today()

    if period == 'last_month':
        start_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        end_date = today.replace(day=1) - timedelta(days=1)
        label = "Last Month"
    else:
        start_date = today.replace(day=1)
        end_date = today
        label = "This Month"

    revenue_query = """
        SELECT SUM(totalCost) AS totalRevenue 
        FROM payment 
        WHERE date BETWEEN %s AND %s AND status = 'success'
    """
    cursor.execute(revenue_query, (start_date, end_date))
    revenue_result = cursor.fetchone()
    total_revenue = revenue_result['totalRevenue'] if revenue_result and revenue_result['totalRevenue'] is not None else 0

    percent = round((total_revenue / 10000) * 100, 2) if total_revenue else 0
    sales_percent = round((total_sales / 500) * 100, 2) if total_sales else 0  

    percent = max(0, min(percent, 100))
    sales_percent = max(0, min(sales_percent, 100))

    cursor.execute("SELECT * FROM transaction ORDER BY TransacID DESC LIMIT 3")
    recent_transactions = cursor.fetchall()

    cursor.execute("SELECT TransacID, created_at FROM notifications ORDER BY created_at DESC LIMIT 5")
    notifications = cursor.fetchall()

    for notification in notifications:
        created_at = notification.get('created_at')
        if isinstance(created_at, str):
            try:
                created_at = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                created_at = datetime.now()
        notification['time_ago'] = time_ago(created_at)

    cursor.close()
    conn.close()

    return render_template('admindb.html',
                           period=period, sales_date=sales_date,
                           total_revenue=total_revenue, total_sales=total_sales,
                           percent=percent, sales_percent=sales_percent,
                           recent_transactions=recent_transactions,
                           notifications=notifications,
                           admin_name=user['AdminName'], admin_photo=user['profile_photo'],
                           period_label=label)

#========================== PRINT JOBS PAGE ======================================
@admin_bp.route('/printjobs', methods=['GET'])
def printjobs():
    if 'AdminID' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch admin profile
    user_id = session.get('AdminID', 1)
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()

    # Pagination setup
    page = int(request.args.get('page', 1))
    limit = 10
    offset = (page - 1) * limit

    # Status filter
    status_filter = request.args.get('status', 'all')
    query = """
        SELECT file, Copies, colorName, totalCost, status
        FROM transaction
    """
    params = []

    if status_filter in ['success', 'pending', 'failed']:
        query += " WHERE status = %s"
        params.append(status_filter)

    query += " ORDER BY TransacID DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    # Fetch filtered transactions with pagination
    cursor.execute(query, params)
    transactions = cursor.fetchall()

    # Count total transactions for pagination
    count_query = "SELECT COUNT(*) as count FROM transaction"
    count_params = []

    if status_filter in ['success', 'pending', 'failed']:
        count_query += " WHERE status = %s"
        count_params.append(status_filter)

    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()["count"]
    total_pages = (total_count // limit) + (1 if total_count % limit > 0 else 0)

    cursor.close()
    conn.close()

    return render_template('printjobs.html',
                           transactions=transactions,
                           page=page,
                           total_pages=total_pages,
                           filter_status=status_filter,
                           admin_name=user['AdminName'], admin_photo=user['profile_photo'])

#========================== PRICELIST PAGE --ADMIN ======================================
@admin_bp.route('/addprice', methods=['GET', 'POST'])
def addprice():
    if 'AdminID' not in session:
        return redirect('/')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
 
    user_id = session.get('AdminID', 1)
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()
    
    if request.method == 'POST':
        item_name = request.form.get('ItemName')
        price = request.form.get('price')
        item_type = request.form.get('type')
        
        if not item_name or not price or not item_type:
            flash('Please fill out all fields', 'danger')
        else:
            cursor.execute("INSERT INTO prices (ItemName, price, type) VALUES (%s, %s, %s)", (item_name, price, item_type))
            conn.commit()
            return redirect(url_for('admin.addprice'))
    
    cursor.execute("SELECT * FROM prices WHERE type = 'Paper Size'")
    paper_sizes = cursor.fetchall()
    
    cursor.execute("SELECT * FROM prices WHERE type = 'Additional Cost'")
    additional_costs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('addprice.html', admin_name=user['AdminName'], admin_photo=user['profile_photo'], paper_sizes=paper_sizes, additional_costs=additional_costs)

@admin_bp.route('/edit_price/<int:id>')
def edit_price(id):
    return redirect(url_for('admin.priceupdate', id=id))

@admin_bp.route('/priceupdate/<int:id>', methods=['GET', 'POST'])
def priceupdate(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    user_id = session.get('AdminID', 1)
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        flash('User not found', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('admin.addprice'))
    
    cursor.execute("SELECT * FROM prices WHERE ItemID = %s", (id,))
    item = cursor.fetchone()
    
    if not item:
        flash('Item not found', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('admin.addprice'))
    
    if request.method == 'POST':
        item_name = request.form.get('ItemName')
        price = request.form.get('price')
        item_type = request.form.get('type')
        
        if not item_name or not price or not item_type:
            flash('Please fill out all fields', 'danger')
        else:
            try:
                cursor.execute("UPDATE prices SET ItemName = %s, price = %s, type = %s WHERE ItemID = %s", (item_name, price, item_type, id))
                conn.commit()
                flash('Price updated successfully!', 'success')
                return redirect(url_for('admin.addprice'))
            except Exception as e:
                flash(f'Update failed: {str(e)}', 'danger')
    
    cursor.close()
    conn.close()
    return render_template('priceupdate.html', item=item, admin_name=user['AdminName'], admin_photo=user['profile_photo'])


@admin_bp.route('/delete_price/<int:item_id>')
def delete_price(item_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM prices WHERE ItemID = %s", (item_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('admin.addprice'))

#========================== ADMIN NOTIFICATIONS ======================================
@admin_bp.route('/notifications', methods=['GET', 'POST'])
def notifications():
    if 'AdminID' not in session:
        return redirect('/')

    user_id = session.get('AdminID', 1)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch admin profile
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()

    # Handle profile update
    if request.method == 'POST' and 'update-btn' in request.form:
        new_name = request.form['AdminName']
        profile_photo = user['profile_photo']

        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join('uploads', filename))
                profile_photo = filename

        cursor.execute("""
            UPDATE users
            SET AdminName = %s, profile_photo = %s
            WHERE AdminID = %s
        """, (new_name, profile_photo, user_id))
        conn.commit()

        # Refresh user data
        cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
        user = cursor.fetchone()

    # Fetch unread notification count
    cursor.execute("SELECT COUNT(*) AS unreadCount FROM notifications WHERE NotifStatus = 'unread'")
    unread_count = cursor.fetchone()['unreadCount']

    # Fetch recent notifications (limit 5)
    cursor.execute("""
        SELECT TransacID, message, NotifStatus, status, created_at
        FROM notifications
        ORDER BY created_at DESC
        LIMIT 5
    """)
    notifications = cursor.fetchall()

    conn.close()

    def time_ago(time_ago):
        time_ago = time_ago.timestamp()
        cur_time = time.time()
        time_elapsed = cur_time - time_ago

        if time_elapsed <= 60:
            return "just now"
        minutes = int(time_elapsed / 60)
        if minutes <= 60:
            return f"{minutes} minute(s) ago"
        hours = int(time_elapsed / 3600)
        if hours <= 24:
            return f"{hours} hour(s) ago"
        days = int(time_elapsed / 86400)
        if days <= 7:
            return f"{days} day(s) ago"
        weeks = int(time_elapsed / 604800)
        if weeks <= 4.3:
            return f"{weeks} week(s) ago"
        months = int(time_elapsed / 2600640)
        if months <= 12:
            return f"{months} month(s) ago"
        years = int(time_elapsed / 31207680)
        return f"{years} year(s) ago"

    return render_template('notifications.html',
                           admin_name=user['AdminName'], admin_photo=user['profile_photo'],
                           unread_count=unread_count,
                           notifications=notifications,
                           time_ago=time_ago)

#========================== NOTIF DETAIL ======================================
def time_ago(created_at):
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    diff = now - created_at

    if diff.days > 0:
        return f"{diff.days} day(s) ago"
    elif diff.seconds >= 3600:
        return f"{diff.seconds // 3600} hour(s) ago"
    elif diff.seconds >= 60:
        return f"{diff.seconds // 60} minute(s) ago"
    else:
        return "Just now"

@admin_bp.route('/notifdetail', methods=['GET', 'POST'])
def notifdetail():
    if 'AdminID' not in session:
        return redirect(url_for('admin.login'))

    user_id = session.get('AdminID')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch admin profile
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()

    # Handle profile update
    if request.method == 'POST':
        admin_name = request.form.get('AdminName')
        profile_photo = None

        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                file_path = os.path.join(admin_bp.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                profile_photo = filename

        update_query = """
        UPDATE users
        SET AdminName = %s, profile_photo = %s
        WHERE AdminID = %s
        """
        cursor.execute(update_query, (admin_name, profile_photo, user_id))
        conn.commit()

    # Fetch admin details
    cursor.execute("SELECT AdminName, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()

    notification_id = request.args.get('id', 0, type=int)
    notification = None

    # Fetch notification details
    if notification_id:
        cursor.execute("SELECT * FROM notifications WHERE TransacID = %s", (notification_id,))
        notification = cursor.fetchone()

    # Get unread notification count
    cursor.execute("SELECT COUNT(*) AS unreadCount FROM notifications WHERE NotifStatus = 'unread'")
    unread_count = cursor.fetchone()


    # Mark notifications as read
    cursor.execute("UPDATE notifications SET NotifStatus = 'read' WHERE NotifStatus = 'unread'")
    conn.commit()

    cursor.close()
    conn.close()

    return render_template('notifdetail.html',
                           admin_name=user['AdminName'], admin_photo=user['profile_photo'],
                           notification=notification,
                           unread_count=unread_count['unreadCount'],
                           time_ago=time_ago)

#========================== ADMIN USERS ======================================
@admin_bp.route('/adminuser', methods=['GET', 'POST'])
def adminuser():
    if 'AdminID' not in session:
        return redirect(url_for('admin.login'))

    user_id = session['AdminID']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch user data
    cursor.execute("SELECT AdminID, AdminName, email, password, profile_photo FROM users WHERE AdminID = %s", (user_id,))
    user = cursor.fetchone()

    if request.method == 'POST' and 'update-btn' in request.form:
        new_name = request.form.get('AdminName', '').strip()
        profile_photo = user['profile_photo']

        # Handle profile photo upload
        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and file.filename != '':
                allowed_types = {'image/jpeg', 'image/png', 'image/gif'}
                if file.mimetype in allowed_types:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(admin_bp.config['UPLOAD_FOLDER'], filename))
                    profile_photo = filename
                else:
                    # Return with error if file type is invalid
                    return render_template('adminuser.html', user=user, error="Invalid file type.")

        # Update user data
        cursor.execute("UPDATE users SET AdminName = %s, profile_photo = %s WHERE AdminID = %s", (new_name, profile_photo, user_id))
        conn.commit()

    cursor.execute("SELECT * FROM users")
    user = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('adminuser.html',
                           user=user,
                           admin_name=session.get('AdminName'), 
                           admin_photo=session.get('AdminPhoto'))

@admin_bp.route('/delete_user', methods=['POST'])
def delete_user():
    if 'AdminID' not in session:
        return redirect(url_for('admin.login'))

    uid = request.form.get('uid')
    if uid:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Delete the user with the specified ID
        cursor.execute("DELETE FROM users WHERE AdminID = %s", (uid,))
        conn.commit()

        cursor.close()
        conn.close()

    return redirect(url_for('admin.adminuser'))

#========================== ADMIN ADD USERS ======================================
@admin_bp.route('/adduser', methods=['GET', 'POST'])
def adduser():
    if 'AdminID' not in session:
        return redirect(url_for('admin.login'))
    admin_id = session.get('AdminID')


    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM users WHERE AdminID = %s", (admin_id,))
    user = cursor.fetchone()

    if request.method == 'POST' and 'update-btn' in request.form:
        new_name = request.form.get('AdminName', '').strip()
        profile_photo = user['profile_photo']

        # Handle profile photo upload
        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and file.filename != '':
                allowed_types = {'image/jpeg', 'image/png', 'image/gif'}
                if file.mimetype in allowed_types:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(admin_bp.config['UPLOAD_FOLDER'], filename))
                    profile_photo = filename
                else:
                    # Return with error if file type is invalid
                    return render_template('adminuser.html', user=user, error="Invalid file type.")

        # Update user data
        cursor.execute("UPDATE users SET AdminName = %s, profile_photo = %s WHERE AdminID = %s", (new_name, profile_photo, admin_id))
        conn.commit()

    if request.method == 'POST':
        name = request.form.get('AdminName', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        profile_photo = ''

    # Handle file upload
    if 'profile_photo' in request.files:
        file = request.files['profile_photo']
        if file and file.filename != '':
            allowed_types = {'image/jpeg', 'image/png'}
            if file.mimetype in allowed_types:
                filename = secure_filename(file.filename)
                new_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)

                file_path = os.path.join(upload_folder, new_filename)  # Save in static/uploads
                file.save(file_path)
                profile_photo = new_filename


        # Insert into the database if all fields are valid
        if name and email and password:
            cursor.execute(
                "INSERT INTO users (profile_photo, AdminName, email, password) VALUES (%s, %s, %s, %s)",
                (profile_photo, name, email, password)
            )
            conn.commit()
            return redirect(url_for('admin.adminuser'))

    cursor.close()
    conn.close()

    return render_template('adduser.html', user=user,
                           admin_name=user['AdminName'], admin_photo=user['profile_photo'])


@admin_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    admin_bp.run(debug=True)
