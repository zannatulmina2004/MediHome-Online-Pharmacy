# ==================== IMPORTS ====================
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from functools import wraps
from decimal import Decimal
import datetime
import csv
import io
import os
import re
import mysql.connector
from mysql.connector import Error
from werkzeug.utils import secure_filename
from time import time
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import random
import secrets
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import check_password_hash
from functools import wraps
import pymysql
from flask import jsonify
from dotenv import load_dotenv
from functools import wraps



# ==================== FLASK APP INITIALIZATION ====================
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-this-secret-key')


# ==================== CONFIGURATION SETTINGS ====================
# Configure upload folders
UPLOAD_FOLDER = 'static/uploads'
PRESCRIPTION_FOLDER = 'static/prescriptions'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

# Ensure upload directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PRESCRIPTION_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PRESCRIPTION_FOLDER'] = PRESCRIPTION_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  
app.config['ALLOWED_EXTENSIONS'] = ALLOWED_EXTENSIONS


@app.template_filter('image_url')
def image_url_filter(value):
    """Return a valid local static image path; missing files use one fallback."""
    fallback = '/static/images/defaultMed.png'
    if not value:
        return fallback
    value = str(value).strip()
    if value.startswith(('http://', 'https://')):
        return value
    if not value.startswith('/static/'):
        value = '/static/images/' + value.lstrip('/')
    rel = value.replace('/static/', '', 1)
    if os.path.exists(os.path.join(app.static_folder, rel)):
        return value
    return fallback

# Database configuration
db_config = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'medihome2')
}

SMTP_CONFIG = {
    "host": os.getenv('SMTP_HOST', 'smtp.gmail.com'),
    "port": int(os.getenv('SMTP_PORT', '587')),
    "username": os.getenv('SMTP_USERNAME', ''),
    "password": os.getenv('SMTP_PASSWORD', '')
}

FROM_EMAIL = os.getenv('FROM_EMAIL', 'MediHome <noreply@example.com>')

# ==================== DATABASE CONNECTION AND HELPERS ====================
def get_db_connection():
    try:
        connection = mysql.connector.connect(**db_config)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_cart_count(user_id):
    """Helper function to get cart count for a user"""
    if not user_id:
        return 0
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result['count'] if result else 0
    return 0

def send_email(subject, to_email, user_name, code):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    # HTML content
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <div style="max-width: 600px; margin: auto; background: #fff; padding: 30px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
          <h2 style="color: #333;">Hello {user_name},</h2>
          <p style="font-size: 16px; color: #555;">
            This is your verification code from <strong>MediHome</strong>.
            Please enter this code to confirm your account:
          </p>
          <h1 style="text-align: center; letter-spacing: 4px; background: #0d6efd; color: #fff; padding: 15px 0; border-radius: 5px;">{code}</h1>
          <p style="font-size: 14px; color: #777; margin-top: 20px;">
            This code is valid for 10 minutes.<br>
            &copy; {datetime.utcnow().year} MediHome. All rights reserved.
          </p>
        </div>
      </body>
    </html>
    """

    msg.add_alternative(html_content, subtype='html')

    if not SMTP_CONFIG["username"] or not SMTP_CONFIG["password"]:
        print(f"[EMAIL NOT CONFIGURED] Verification code for {to_email}: {code}")
        return False

    try:
        with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=15) as server:
            server.starttls()
            server.login(SMTP_CONFIG["username"], SMTP_CONFIG["password"])
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[EMAIL WARNING] Could not send verification email: {exc}")
        print(f"[EMAIL FALLBACK] Verification code for {to_email}: {code}")
        return False


def send_order_email(to_email, user_name, order_ref, total_amount):
    """Send an order email when SMTP is configured; never break checkout if it is not."""
    if not SMTP_CONFIG["username"] or not SMTP_CONFIG["password"]:
        print(f"[EMAIL NOT CONFIGURED] Order confirmation for {to_email}; order: {order_ref}")
        return False

    msg = EmailMessage()
    msg["Subject"] = f"MediHome - Order Confirmation {order_ref}"
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    html_content = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f7fb;padding:20px;">
      <div style="max-width:600px;margin:auto;background:#fff;padding:30px;border-radius:14px;">
        <h2 style="color:#0f766e;">MediHome Order Confirmed</h2>
        <p>Hello {user_name}, your order has been received successfully.</p>
        <p><strong>Order ID:</strong> {order_ref}</p>
        <p><strong>Total:</strong> BDT {total_amount}</p>
        <p>We will update you when your order is processed.</p>
      </div></body></html>
    """
    msg.add_alternative(html_content, subtype='html')
    try:
        with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=15) as server:
            server.starttls()
            server.login(SMTP_CONFIG["username"], SMTP_CONFIG["password"])
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[EMAIL WARNING] Could not send order email: {exc}")
        return False


# CREATE TABLE statements for all tables
tables_sql = [
    # users
    """
     CREATE TABLE IF NOT EXISTS `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `password` varchar(255) NOT NULL,
  `address` text DEFAULT NULL,
  `role` varchar(50) DEFAULT 'customer',
  `image` varchar(255) DEFAULT NULL,
  `is_verified` TINYINT(1) DEFAULT 0,
  `verification_code` VARCHAR(6) DEFAULT NULL,
  `code_expiry` DATETIME DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
   PRIMARY KEY (`id`),
   UNIQUE KEY `email` (`email`)
   ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    # medicines
    """
    CREATE TABLE IF NOT EXISTS `medicines` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `name` varchar(255) NOT NULL,
      `price` decimal(10,2) NOT NULL,
      `stock_quantity` int(11) DEFAULT 0,
      `sold_quantity` int(11) DEFAULT 0,
      `ratings` decimal(3,2) DEFAULT 0.00,
      `details` text DEFAULT NULL,
      `category` varchar(100) DEFAULT 'General',
      `image` varchar(255) DEFAULT NULL,
      PRIMARY KEY (`id`)
    ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    # cart
    """
    CREATE TABLE IF NOT EXISTS `cart` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `user_id` int(11) NOT NULL,
      `medicine_id` int(11) NOT NULL,
      `quantity` int(11) DEFAULT 1,
      PRIMARY KEY (`id`),
      KEY `user_id` (`user_id`),
      KEY `medicine_id` (`medicine_id`),
      CONSTRAINT `cart_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
      CONSTRAINT `cart_ibfk_2` FOREIGN KEY (`medicine_id`) REFERENCES `medicines` (`id`) ON DELETE CASCADE
    ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    # orders
    """
    CREATE TABLE IF NOT EXISTS `orders` (
    `id` INT(11) NOT NULL AUTO_INCREMENT,
    `ordered_by` VARCHAR(255) NOT NULL,
    `phone` VARCHAR(20) DEFAULT NULL,
    `email` VARCHAR(255) DEFAULT NULL,
    `address` TEXT DEFAULT NULL,
    `product` VARCHAR(255) NOT NULL,
    `quantity` INT(11) DEFAULT 1,
    `unit_price` DECIMAL(10,2) NOT NULL,
    `price` DECIMAL(10,2) NOT NULL,          -- price = unit_price * quantity
    `delivery_charge` DECIMAL(10,2) DEFAULT 0,
    `discount` DECIMAL(10,2) DEFAULT 0,
    `payment_method` VARCHAR(50) DEFAULT 'cod',
    `special_instruction` TEXT DEFAULT NULL,
    `status` VARCHAR(50) DEFAULT 'Pending',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4;


    """,
    # all_orders
    """
    CREATE TABLE IF NOT EXISTS `all_orders` (
    `id` INT(11) NOT NULL AUTO_INCREMENT,
    `ordered_by` VARCHAR(255) NOT NULL,
    `phone` VARCHAR(20) DEFAULT NULL,
    `email` VARCHAR(255) DEFAULT NULL,
    `address` TEXT DEFAULT NULL,
    `product` VARCHAR(255) NOT NULL,
    `quantity` INT(11) DEFAULT 1,
    `unit_price` DECIMAL(10,2) NOT NULL,
    `price` DECIMAL(10,2) NOT NULL,       -- price = unit_price * quantity
    `delivery_charge` DECIMAL(10,2) DEFAULT 0,
    `discount` DECIMAL(10,2) DEFAULT 0,
    `payment_method` VARCHAR(50) DEFAULT 'cod',
    `special_instruction` TEXT DEFAULT NULL,
    `status` VARCHAR(50) DEFAULT 'Pending',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4;

    """,
    # dborders
    """
    CREATE TABLE IF NOT EXISTS `dborders` (
    `id` INT(11) NOT NULL AUTO_INCREMENT,
    `ordered_by` VARCHAR(255) NOT NULL,
    `phone` VARCHAR(20) DEFAULT NULL,
    `email` VARCHAR(255) DEFAULT NULL,
    `address` TEXT DEFAULT NULL,
    `product` VARCHAR(255) NOT NULL,
    `quantity` INT(11) DEFAULT 1,
    `unit_price` DECIMAL(10,2) NOT NULL,
    `price` DECIMAL(10,2) NOT NULL,
    `delivery_charge` DECIMAL(10,2) DEFAULT 0,
    `discount` DECIMAL(10,2) DEFAULT 0,
    `payment_method` VARCHAR(50) DEFAULT 'cod',
    `special_instruction` TEXT DEFAULT NULL,
    `status` VARCHAR(50) DEFAULT 'Pending',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    """,
    # contact_messages
    """
    CREATE TABLE IF NOT EXISTS `contact_messages` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `name` varchar(255) NOT NULL,
      `email` varchar(255) NOT NULL,
      `phone` varchar(20) DEFAULT NULL,
      `subject` varchar(255) DEFAULT NULL,
      `message` text DEFAULT NULL,
      `newsletter` tinyint(1) DEFAULT 0,
      `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
      PRIMARY KEY (`id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=latin1;
    """,
    # newsletter_subscribers
    """
    CREATE TABLE IF NOT EXISTS `newsletter_subscribers` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `email` varchar(255) NOT NULL,
      `subscribed_at` timestamp NOT NULL DEFAULT current_timestamp(),
      PRIMARY KEY (`id`),
      UNIQUE KEY `email` (`email`)
    ) ENGINE=InnoDB DEFAULT CHARSET=latin1;
    """,
    # prescriptions
    """
    CREATE TABLE IF NOT EXISTS `prescriptions` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `user_id` int(11) NOT NULL,
      `patient_name` varchar(255) NOT NULL,
      `patient_age` int(11) DEFAULT NULL,
      `patient_phone` varchar(20) DEFAULT NULL,
      `patient_email` varchar(255) DEFAULT NULL,
      `patient_address` text DEFAULT NULL,
      `image_path` varchar(255) DEFAULT NULL,
      `special_instructions` text DEFAULT NULL,
      `status` varchar(50) DEFAULT 'Pending',
      `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
      PRIMARY KEY (`id`),
      KEY `user_id` (`user_id`),
      CONSTRAINT `prescriptions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
    ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    # promo_codes
    """
    CREATE TABLE IF NOT EXISTS `promo_codes` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `code` varchar(50) NOT NULL,
      `discount_type` enum('percentage','fixed','free_delivery') NOT NULL,
      `discount_value` decimal(10,2) NOT NULL,
      `valid_from` date NOT NULL,
      `valid_until` date NOT NULL,
      `max_uses` int(11) NOT NULL DEFAULT 100,
      `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
      `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
      `is_active` tinyint(1) DEFAULT 1,
      `used_count` int(11) DEFAULT 0,
      PRIMARY KEY (`id`),
      UNIQUE KEY `code` (`code`)
    ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    # reviews
    """
    CREATE TABLE IF NOT EXISTS `reviews` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `user_id` int(11) NOT NULL,
      `medicine_id` int(11) DEFAULT NULL,
      `ratings` decimal(3,2) NOT NULL,
      `quote` text DEFAULT NULL,
      `review_date` timestamp NOT NULL DEFAULT current_timestamp(),
      PRIMARY KEY (`id`),
      KEY `user_id` (`user_id`),
      KEY `medicine_id` (`medicine_id`),
      CONSTRAINT `reviews_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
      CONSTRAINT `reviews_ibfk_2` FOREIGN KEY (`medicine_id`) REFERENCES `medicines` (`id`) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=latin1;
    """,
    # settings
    """
    CREATE TABLE IF NOT EXISTS `settings` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `setting_key` varchar(100) NOT NULL,
      `setting_value` text DEFAULT NULL,
      `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
      `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
      PRIMARY KEY (`id`),
      UNIQUE KEY `setting_key` (`setting_key`)
    ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    #Chat
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
    id INT NOT NULL AUTO_INCREMENT,
    sender_id INT NOT NULL,        -- 0 for admin
    sender_name VARCHAR(255) NOT NULL,
    receiver INT NOT NULL,         -- customer_id for admin messages, 'admin' for customer->admin
    message TEXT NOT NULL,
    is_read TINYINT(1) DEFAULT 0, -- 0=unread, 1=read
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    """,
    # user_promo_codes
    """
    CREATE TABLE IF NOT EXISTS `user_promo_codes` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `user_id` int(11) NOT NULL,
      `promo_code_id` int(11) NOT NULL,
      `used_at` timestamp NOT NULL DEFAULT current_timestamp(),
      `is_active` tinyint(1) DEFAULT 1,
      PRIMARY KEY (`id`),
      KEY `user_id` (`user_id`),
      KEY `promo_code_id` (`promo_code_id`),
      CONSTRAINT `user_promo_codes_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
      CONSTRAINT `user_promo_codes_ibfk_2` FOREIGN KEY (`promo_code_id`) REFERENCES `promo_codes` (`id`) ON DELETE CASCADE
    ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1;
    """,
    """
    INSERT INTO `promo_codes` 
(`code`, `discount_type`, `discount_value`, `valid_from`, `valid_until`, `max_uses`, `is_active`, `used_count`)
VALUES
('WELCOME10', 'percentage', 10.00, '2025-12-01', '2026-01-01', 100, 1, 0),
('FLAT50', 'fixed', 50.00, '2025-12-01', '2026-02-01', 100, 1, 0),
('FREESHIP', 'free_delivery', 0.00, '2025-12-01', '2026-03-01', 100, 1, 0),
('HOLIDAY20', 'percentage', 20.00, '2025-12-15', '2026-01-15', 50, 1, 0),
('SAVE100', 'fixed', 100.00, '2025-12-10', '2026-02-10', 30, 1, 0),
('NEWYEAR25', 'percentage', 25.00, '2025-12-31', '2026-01-31', 200, 1, 0),
('SHIPFREE50', 'free_delivery', 0.00, '2025-12-05', '2026-01-05', 150, 1, 0),
('SPRING15', 'percentage', 15.00, '2026-03-01', '2026-04-01', 100, 1, 0),
('FLAT200', 'fixed', 200.00, '2025-12-20', '2026-01-20', 20, 1, 0),
('HOLIDAYSHIP', 'free_delivery', 0.00, '2025-12-20', '2026-01-10', 100, 1, 0);
""",
]

@app.route('/create_tables')
def create_tables():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        for sql in tables_sql:
            cursor.execute(sql)
        conn.commit()
        cursor.close()
        conn.close()
        return "All 13 tables created successfully (if not exist)!"
    except mysql.connector.Error as err:
        return f"Error: {err}"

create_tables()

# ==================== MEDICINE CATALOG + COMPANY COLUMN (FIX) ====================
# Adds a `company` column to `medicines` (for filtering by manufacturer, e.g.
# Square, Beximco, ACME, Renata, etc.) and seeds the full medicine catalog
# -- with correct local image paths (static/images/...) and a company for
# every item -- but ONLY if the table is currently empty, so this is safe to
# re-run on every app start and will never duplicate or wipe existing data.
def setup_company_column():
    conn = get_db_connection()
    if not conn:
        print("[MEDICINE SETUP] Could not connect to MySQL, skipping company column setup.")
        return
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE `medicines` ADD COLUMN `company` VARCHAR(150) DEFAULT NULL")
        conn.commit()
    except mysql.connector.Error as err:
        if err.errno != 1060:  # 1060 = Duplicate column name, already exists
            print(f"[MEDICINE SETUP] {err}")
    cursor.close()
    conn.close()

setup_company_column()


def normalize_medicine_image_paths():
    """Fix any legacy image values that are bare filenames (e.g. 'napa.jpg')
    instead of a proper site-root path, so <img src="..."> always resolves
    correctly no matter which page/route it's rendered on."""
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE medicines SET image = CONCAT('/static/images/', image) "
            "WHERE image IS NOT NULL AND image <> '' "
            "AND image NOT LIKE '/static/%%' AND image NOT LIKE 'static/%%' "
            "AND image NOT LIKE 'http%%'"
        )
        conn.commit()
    except mysql.connector.Error as err:
        print(f"[MEDICINE SETUP] Could not normalize image paths: {err}")
    cursor.close()
    conn.close()

normalize_medicine_image_paths()


def seed_medicine_catalog():
    """Keep the catalog complete on every run.

    The original project only seeded medicines when the table was empty, which
    meant an older database never received the newer products, companies or
    image paths.  We now load the catalog into a temporary table, add missing
    products, and repair the company/category/image metadata for matching
    products without deleting customer data.
    """
    conn = get_db_connection()
    if not conn:
        print("[MEDICINE SETUP] Could not connect to MySQL, skipping catalog sync.")
        return
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TEMPORARY TABLE medicine_seed (
              `name` varchar(255) NOT NULL,
              `price` decimal(10,2) NOT NULL,
              `stock_quantity` int(11) DEFAULT 0,
              `sold_quantity` int(11) DEFAULT 0,
              `ratings` decimal(3,2) DEFAULT 0.00,
              `details` text DEFAULT NULL,
              `category` varchar(100) DEFAULT 'General',
              `image` varchar(255) DEFAULT NULL,
              `company` varchar(150) DEFAULT NULL
            ) ENGINE=InnoDB;
        """)
        cursor.execute("""INSERT INTO `medicine_seed`
            (`name`, `price`, `stock_quantity`, `sold_quantity`, `ratings`, `details`, `category`, `image`, `company`)
            VALUES
            ('Paracetamol 500mg', 15.00, 100, 50, 4.5, 'Pain reliever and fever reducer.', 'Pain Relief', '/static/images/paracetamol.webp', 'Square Pharmaceuticals'),
            ('Ibuprofen 400mg', 18.00, 90, 45, 4.4, 'Anti-inflammatory pain reliever.', 'Pain Relief', '/static/images/ibuprofen_400mg.png', 'Beximco Pharmaceuticals'),
            ('Napa Extra 650mg', 25.00, 80, 40, 4.6, 'Effective for mild to moderate pain.', 'Pain Relief', '/static/images/napa.webp', 'Beximco Pharmaceuticals'),
            ('Aspirin 75mg', 12.00, 120, 60, 4.3, 'Blood thinner and pain reliever.', 'Pain Relief', '/static/images/ecospirin.jpeg', 'Incepta Pharmaceuticals'),
            ('C-Vita 500mg', 30.00, 60, 30, 4.2, 'Vitamin C supplement.', 'Vitamins', '/static/images/cevit.jpeg', 'ACI Limited'),
            ('Calbo 500mg', 20.00, 70, 35, 4.3, 'Calcium supplement for bones.', 'Vitamins', '/static/images/calbo_500mg.png', 'ACI Limited'),
            ('Seclo 10mg', 45.00, 50, 20, 4.0, 'For stomach acid and ulcers.', 'Digestive', '/static/images/seclo.webp', 'Square Pharmaceuticals'),
            ('Amoxicillin 500mg', 50.00, 40, 25, 4.1, 'Antibiotic for bacterial infections.', 'Antibiotics', '/static/images/amoxicillin_500mg.png', 'Eskayef Pharmaceuticals'),
            ('Ciprofloxacin 250mg', 55.00, 30, 15, 4.2, 'Antibiotic for bacterial infections.', 'Antibiotics', '/static/images/ciprofloxacin_250mg.png', 'Opsonin Pharma'),
            ('Metformin 500mg', 22.00, 60, 30, 4.0, 'For type 2 diabetes control.', 'Diabetes', '/static/images/metformin_500mg.png', 'Incepta Pharmaceuticals'),
            ('Glimepiride 2mg', 28.00, 50, 25, 4.1, 'Diabetes medicine to lower blood sugar.', 'Diabetes', '/static/images/glimepiride_2mg.png', 'Square Pharmaceuticals'),
            ('Cetirizine 10mg', 12.00, 100, 50, 4.2, 'Antihistamine for allergies.', 'Allergy', '/static/images/cetirizine_10mg.png', 'Beximco Pharmaceuticals'),
            ('Loratadine 10mg', 14.00, 80, 40, 4.3, 'Non-drowsy antihistamine.', 'Allergy', '/static/images/loratadine_10mg.png', 'ACME Laboratories'),
            ('Salbutamol 100mcg', 35.00, 40, 20, 4.1, 'Relieves asthma symptoms.', 'Respiratory', '/static/images/salbutamol_100mcg.png', 'Renata Limited'),
            ('Montelukast 10mg', 40.00, 35, 15, 4.2, 'Prevents asthma attacks.', 'Respiratory', '/static/images/montelukast_10mg.png', 'Beximco Pharmaceuticals'),
            ('Omeprazole 20mg', 25.00, 60, 30, 4.3, 'Reduces stomach acid.', 'Digestive', '/static/images/omeprazole_20mg.png', 'Eskayef Pharmaceuticals'),
            ('Pantoprazole 40mg', 30.00, 55, 25, 4.2, 'Prevents acid reflux.', 'Digestive', '/static/images/pantoprazole_40mg.png', 'Aristopharma'),
            ('Diclofenac 50mg', 16.00, 80, 40, 4.1, 'Pain reliever and anti-inflammatory.', 'Pain Relief', '/static/images/diclofenac_50mg.png', 'Eskayef Pharmaceuticals'),
            ('Naproxen 250mg', 20.00, 70, 35, 4.0, 'Treats pain and inflammation.', 'Pain Relief', '/static/images/naproxen_250mg.png', 'Opsonin Pharma'),
            ('Ranitidine 150mg', 18.00, 90, 45, 4.0, 'Reduces stomach acid.', 'Digestive', '/static/images/ranitidine_150mg.png', 'Drug International'),
            ('Hydrochlorothiazide 25mg', 22.00, 60, 30, 4.1, 'Treats high blood pressure.', 'Cardiovascular', '/static/images/hydrochlorothiazide_25mg.png', 'Square Pharmaceuticals'),
            ('Amlodipine 5mg', 28.00, 50, 25, 4.2, 'Lowers blood pressure.', 'Cardiovascular', '/static/images/amlodipine_5mg.png', 'Beximco Pharmaceuticals'),
            ('Losartan 50mg', 35.00, 45, 20, 4.3, 'For high blood pressure.', 'Cardiovascular', '/static/images/losartan_50mg.png', 'Square Pharmaceuticals'),
            ('Simvastatin 20mg', 40.00, 40, 15, 4.1, 'Lowers cholesterol.', 'Cardiovascular', '/static/images/simvastatin_20mg.png', 'Renata Limited'),
            ('Atorvastatin 10mg', 42.00, 35, 15, 4.2, 'Reduces LDL cholesterol.', 'Cardiovascular', '/static/images/atorvastatin_10mg.png', 'Incepta Pharmaceuticals'),
            ('Levothyroxine 50mcg', 25.00, 60, 30, 4.1, 'For hypothyroidism.', 'Endocrine', '/static/images/levothyroxine_50mcg.png', 'ACI Limited'),
            ('Vitamin D3 1000IU', 15.00, 100, 50, 4.3, 'Supports bone health.', 'Vitamins', '/static/images/vitamin_d3_1000iu.png', 'Aristopharma'),
            ('Folic Acid 400mcg', 12.00, 80, 40, 4.2, 'Prevents anemia.', 'Vitamins', '/static/images/folic_acid_400mcg.png', 'Eskayef Pharmaceuticals'),
            ('Iron 65mg', 20.00, 70, 35, 4.1, 'Treats iron deficiency.', 'Vitamins', '/static/images/iron_65mg.png', 'Opsonin Pharma'),
            ('Zinc 20mg', 18.00, 60, 30, 4.2, 'Supports immune system.', 'Vitamins', '/static/images/zinc_20mg.png', 'Drug International'),
            ('Magnesium 250mg', 22.00, 50, 25, 4.1, 'Supports muscle and nerve function.', 'Vitamins', '/static/images/magnesium_250mg.png', 'Square Pharmaceuticals'),
            ('Coenzyme Q10 100mg', 35.00, 40, 20, 4.2, 'Supports heart health.', 'Supplements', '/static/images/coenzyme_q10_100mg.png', 'Beximco Pharmaceuticals'),
            ('Omega 3 Fish Oil', 40.00, 45, 25, 4.3, 'Supports heart and brain health.', 'Supplements', '/static/images/omega_3_fish_oil.png', 'ACME Laboratories'),
            ('Ginger Capsules', 15.00, 80, 40, 4.0, 'Aids digestion and reduces nausea.', 'Herbal', '/static/images/ginger_capsules.png', 'Renata Limited'),
            ('Turmeric Capsules', 18.00, 70, 35, 4.1, 'Anti-inflammatory and antioxidant.', 'Herbal', '/static/images/turmeric_capsules.png', 'Incepta Pharmaceuticals'),
            ('Garlic Capsules', 20.00, 60, 30, 4.2, 'Supports heart health.', 'Herbal', '/static/images/garlic_capsules.png', 'ACI Limited'),
            ('Aloe Vera Juice', 25.00, 50, 25, 4.3, 'Supports digestive health.', 'Herbal', '/static/images/aloe_vera_juice.png', 'Aristopharma'),
            ('Honey 500g', 12.00, 100, 50, 4.4, 'Natural sweetener and immune booster.', 'Herbal', '/static/images/honey_500g.png', 'Eskayef Pharmaceuticals'),
            ('Probiotic Capsules', 30.00, 60, 30, 4.3, 'Supports gut health.', 'Supplements', '/static/images/probiotic_capsules.png', 'Opsonin Pharma'),
            ('Calcium + Vitamin D', 28.00, 50, 25, 4.2, 'Supports bone health.', 'Vitamins', '/static/images/calcium_vitamin_d.png', 'Drug International'),
            ('Multivitamin Tablets', 35.00, 60, 30, 4.3, 'General health supplement.', 'Vitamins', '/static/images/multivitamin_tablets.png', 'Square Pharmaceuticals'),
            ('Vitamin B12 1000mcg', 22.00, 70, 35, 4.1, 'Supports nerve health.', 'Vitamins', '/static/images/vitamin_b12_1000mcg.png', 'Beximco Pharmaceuticals'),
            ('Vitamin B6 50mg', 18.00, 80, 40, 4.0, 'Supports metabolism.', 'Vitamins', '/static/images/vitamin_b6_50mg.png', 'ACME Laboratories'),
            ('Vitamin A 5000IU', 15.00, 90, 45, 4.1, 'Supports vision.', 'Vitamins', '/static/images/vitamin_a_5000iu.png', 'Renata Limited'),
            ('Vitamin E 400IU', 25.00, 60, 30, 4.2, 'Antioxidant.', 'Vitamins', '/static/images/vitamin_e_400iu.png', 'Incepta Pharmaceuticals'),
            ('Biotin 5mg', 20.00, 50, 25, 4.0, 'Supports hair and nails.', 'Vitamins', '/static/images/biotin_5mg.png', 'ACI Limited'),
            ('Fexofenadine 120mg', 18.00, 80, 40, 4.1, 'Non-drowsy antihistamine.', 'Allergy', '/static/images/fexofenadine_120mg.png', 'Renata Limited'),
            ('Montair LC', 45.00, 40, 20, 4.2, 'Allergy relief.', 'Allergy', '/static/images/montair_lc.png', 'Eskayef Pharmaceuticals'),
            ('Levocetirizine 5mg', 12.00, 100, 50, 4.3, 'Allergy treatment.', 'Allergy', '/static/images/levocetirizine_5mg.png', 'Opsonin Pharma'),
            ('Budesonide Inhaler', 50.00, 30, 15, 4.2, 'Asthma treatment.', 'Respiratory', '/static/images/budesonide_inhaler.png', 'Drug International'),
            ('Formoterol Inhaler', 55.00, 35, 15, 4.3, 'Long-term asthma management.', 'Respiratory', '/static/images/formoterol_inhaler.png', 'Square Pharmaceuticals'),
            ('Montelukast + Levocetirizine', 60.00, 25, 10, 4.1, 'Allergy and asthma combo.', 'Respiratory', '/static/images/montelukast_levocetirizine.png', 'Beximco Pharmaceuticals'),
            ('Salbutamol + Ipratropium', 65.00, 20, 10, 4.2, 'Bronchodilator combo.', 'Respiratory', '/static/images/salbutamol_ipratropium.png', 'ACME Laboratories'),
            ('Fluticasone Nasal Spray', 40.00, 30, 15, 4.3, 'Nasal allergy relief.', 'Allergy', '/static/images/fluticasone_nasal_spray.png', 'Renata Limited'),
            ('Prednisolone 5mg', 25.00, 50, 25, 4.1, 'Steroid for inflammation.', 'Anti-inflammatory', '/static/images/prednisolone_5mg.png', 'Incepta Pharmaceuticals'),
            ('Hydrocortisone Cream', 20.00, 60, 30, 4.0, 'Topical anti-inflammatory.', 'Anti-inflammatory', '/static/images/hydrocortisone_cream.png', 'ACI Limited'),
            ('Diclofenac Gel', 18.00, 70, 35, 4.1, 'Pain relief gel.', 'Pain Relief', '/static/images/diclofenac_gel.png', 'Aristopharma'),
            ('Ketoconazole Cream', 22.00, 50, 25, 4.2, 'Antifungal cream.', 'Dermatology', '/static/images/ketoconazole_cream.png', 'Eskayef Pharmaceuticals'),
            ('Clotrimazole Cream', 20.00, 60, 30, 4.1, 'Treats fungal infections.', 'Dermatology', '/static/images/clotrimazole_cream.png', 'Opsonin Pharma'),
            ('Cetomacrogol Cream', 18.00, 70, 35, 4.0, 'Moisturizing cream.', 'Dermatology', '/static/images/cetomacrogol_cream.png', 'Drug International'),
            ('Bepanthen Cream', 25.00, 50, 25, 4.2, 'Skin healing cream.', 'Dermatology', '/static/images/bepanthen_cream.png', 'Square Pharmaceuticals'),
            ('Acyclovir 400mg', 35.00, 40, 20, 4.1, 'Antiviral for cold sores.', 'Antiviral', '/static/images/acyclovir_400mg.png', 'Beximco Pharmaceuticals'),
            ('Oseltamivir 75mg', 45.00, 35, 15, 4.2, 'Flu treatment.', 'Antiviral', '/static/images/oseltamivir_75mg.png', 'ACME Laboratories'),
            ('Valacyclovir 500mg', 50.00, 30, 10, 4.3, 'Treats viral infections.', 'Antiviral', '/static/images/valacyclovir_500mg.png', 'Renata Limited'),
            ('Loperamide 2mg', 12.00, 100, 50, 4.0, 'Stops diarrhea.', 'Digestive', '/static/images/loperamide_2mg.png', 'Incepta Pharmaceuticals'),
            ('Orlistat 60mg', 55.00, 25, 10, 4.1, 'Weight loss medication.', 'Weight Management', '/static/images/orlistat_60mg.png', 'ACI Limited'),
            ('Sildenafil 50mg', 75.00, 20, 5, 4.2, 'Treats erectile dysfunction.', 'Men Health', '/static/images/sildenafil_50mg.png', 'Aristopharma'),
            ('Tadalafil 10mg', 80.00, 15, 5, 4.3, 'Erectile dysfunction treatment.', 'Men Health', '/static/images/tadalafil_10mg.png', 'Eskayef Pharmaceuticals'),
            ('Finasteride 5mg', 70.00, 25, 10, 4.0, 'Treats hair loss.', 'Men Health', '/static/images/finasteride_5mg.png', 'Opsonin Pharma'),
            ('Minoxidil 5%', 65.00, 30, 15, 4.1, 'Hair growth solution.', 'Men Health', '/static/images/minoxidil_5.png', 'Drug International'),
            ('Oral Rehydration Salts', 10.00, 100, 50, 4.2, 'Prevents dehydration.', 'Digestive', '/static/images/oral_rehydration_salts.png', 'Square Pharmaceuticals'),
            ('Paracetamol Syrup', 20.00, 80, 40, 4.3, 'Pain and fever in children.', 'Pain Relief', '/static/images/paracetamol_syrup.png', 'Beximco Pharmaceuticals'),
            ('Amoxicillin Syrup', 45.00, 50, 25, 4.2, 'Antibiotic for children.', 'Antibiotics', '/static/images/amoxicillin_syrup.png', 'ACME Laboratories'),
            ('Cough Syrup', 25.00, 60, 30, 4.1, 'Relieves cough.', 'Respiratory', '/static/images/cough_syrup.png', 'Renata Limited'),
            ('Vitamin C Chewable', 18.00, 70, 35, 4.2, 'Chewable vitamin C tablets.', 'Vitamins', '/static/images/vitamin_c_chewable.png', 'Incepta Pharmaceuticals'),
            ('Calcium Chewable', 20.00, 50, 25, 4.1, 'Chewable calcium tablets.', 'Vitamins', '/static/images/calcium_chewable.png', 'ACI Limited'),
            ('Magnesium Chewable', 22.00, 40, 20, 4.0, 'Chewable magnesium tablets.', 'Vitamins', '/static/images/magnesium_chewable.png', 'Aristopharma'),
            ('Zinc Chewable', 18.00, 60, 30, 4.1, 'Chewable zinc tablets.', 'Vitamins', '/static/images/zinc_chewable.png', 'Eskayef Pharmaceuticals'),
            ('Probiotic Sachet', 30.00, 50, 25, 4.2, 'Gut health supplement.', 'Supplements', '/static/images/probiotic_sachet.png', 'Opsonin Pharma'),
            ('Herbal Tea', 15.00, 100, 50, 4.3, 'Digestive and relaxation.', 'Herbal', '/static/images/herbal_tea.png', 'Drug International'),
            ('Aloe Vera Gel', 20.00, 80, 40, 4.2, 'Skin care gel.', 'Herbal', '/static/images/aloe_vera_gel.png', 'Square Pharmaceuticals'),
            ('Vitamin E Oil', 25.00, 60, 30, 4.1, 'Skin and hair care.', 'Vitamins', '/static/images/vitamin_e_oil.png', 'Beximco Pharmaceuticals'),
            ('Face Cream', 35.00, 50, 25, 4.0, 'Moisturizing face cream.', 'Dermatology', '/static/images/face_cream.png', 'ACME Laboratories'),
            ('Sunscreen SPF50', 40.00, 45, 20, 4.2, 'Protects against UV rays.', 'Dermatology', '/static/images/sunscreen_spf50.png', 'Renata Limited'),
            ('Lip Balm', 12.00, 100, 50, 4.1, 'Protects lips.', 'Dermatology', '/static/images/lip_balm.png', 'Incepta Pharmaceuticals'),
            ('Hand Sanitizer 100ml', 15.00, 120, 60, 4.3, 'Kills germs and bacteria.', 'Hygiene', '/static/images/hand_sanitizer_100ml.png', 'ACI Limited'),
            ('Disinfectant Spray', 25.00, 80, 40, 4.2, 'Kills germs on surfaces.', 'Hygiene', '/static/images/disinfectant_spray.png', 'Aristopharma'),
            ('Face Mask 50pcs', 30.00, 60, 30, 4.0, 'Protective face masks.', 'Hygiene', '/static/images/face_mask_50pcs.png', 'Eskayef Pharmaceuticals'),
            ('Gloves 100pcs', 20.00, 50, 25, 4.1, 'Disposable gloves.', 'Hygiene', '/static/images/gloves_100pcs.png', 'Opsonin Pharma'),
            ('Thermometer Digital', 50.00, 40, 20, 4.3, 'Measures body temperature.', 'Medical Devices', '/static/images/thermometer_digital.png', 'Drug International'),
            ('Blood Pressure Monitor', 150.00, 30, 15, 4.2, 'Monitors blood pressure.', 'Medical Devices', '/static/images/blood_pressure_monitor.png', 'Square Pharmaceuticals'),
            ('Glucometer', 80.00, 50, 25, 4.1, 'Measures blood sugar.', 'Medical Devices', '/static/images/glucometer.png', 'Beximco Pharmaceuticals'),
            ('Stethoscope', 100.00, 20, 10, 4.0, 'Medical examination device.', 'Medical Devices', '/static/images/stethoscope.png', 'ACME Laboratories'),
            ('Otoscope', 75.00, 15, 5, 4.1, 'Ear examination device.', 'Medical Devices', '/static/images/otoscope.png', 'Renata Limited'),
            ('Nebulizer', 200.00, 10, 5, 4.2, 'Respiratory treatment device.', 'Medical Devices', '/static/images/nebulizer.png', 'Incepta Pharmaceuticals'),
            ('Inhaler Spacer', 30.00, 40, 20, 4.0, 'Helps use inhaler effectively.', 'Medical Devices', '/static/images/inhaler_spacer.png', 'ACI Limited'),
            ('First Aid Kit', 50.00, 60, 30, 4.3, 'Emergency medical supplies.', 'Hygiene', '/static/images/first_aid_kit.png', 'Aristopharma'),
            ('Bandage Roll', 10.00, 100, 50, 4.2, 'For wound dressing.', 'Hygiene', '/static/images/bandage_roll.png', 'Eskayef Pharmaceuticals'),
            ('Cotton Roll', 8.00, 120, 60, 4.1, 'Medical cotton.', 'Hygiene', '/static/images/cotton_roll.png', 'Opsonin Pharma'),
            ('Alcohol Swab', 12.00, 80, 40, 4.2, 'For disinfection.', 'Hygiene', '/static/images/alcohol_swab.png', 'Drug International'),
            ('Hand Gloves Latex', 20.00, 50, 25, 4.0, 'Latex examination gloves.', 'Hygiene', '/static/images/hand_gloves_latex.png', 'Square Pharmaceuticals'),
            ('Surgical Mask', 25.00, 100, 50, 4.1, 'Surgical protective mask.', 'Hygiene', '/static/images/surgical_mask.png', 'Beximco Pharmaceuticals'),
            ('Ointment Anti-Fungal', 18.00, 60, 30, 4.2, 'Treats fungal infections.', 'Dermatology', '/static/images/ointment_anti-fungal.png', 'ACME Laboratories'),
            ('Pain Relief Patch', 22.00, 50, 25, 4.1, 'Provides localized pain relief.', 'Pain Relief', '/static/images/pain_relief_patch.png', 'Renata Limited'),
            ('Cold Compress Pack', 15.00, 80, 40, 4.0, 'Reduces swelling.', 'Pain Relief', '/static/images/cold_compress_pack.png', 'Incepta Pharmaceuticals'),
            ('Hot Compress Pack', 15.00, 80, 40, 4.0, 'Relieves muscle pain.', 'Pain Relief', '/static/images/hot_compress_pack.png', 'ACI Limited'),
            ('Eye Drops Lubricant', 20.00, 50, 25, 4.1, 'Relieves dry eyes.', 'Eye Care', '/static/images/eye_drops_lubricant.png', 'Aristopharma'),
            ('Vitamin A Eye Drops', 25.00, 40, 20, 4.2, 'Supports eye health.', 'Eye Care', '/static/images/vitamin_a_eye_drops.png', 'Eskayef Pharmaceuticals'),
            ('Contact Lens Solution', 30.00, 60, 30, 4.3, 'Cleans and stores lenses.', 'Eye Care', '/static/images/contact_lens_solution.png', 'Opsonin Pharma'),
            ('Artificial Tears', 22.00, 50, 25, 4.1, 'Moisturizes eyes.', 'Eye Care', '/static/images/artificial_tears.png', 'Drug International'),
            ('Hearing Aid Batteries', 15.00, 100, 50, 4.0, 'Batteries for hearing aids.', 'Medical Devices', '/static/images/hearing_aid_batteries.png', 'Square Pharmaceuticals'),
            ('Memory Foam Pillow', 50.00, 40, 20, 4.1, 'Supports neck and spine.', 'Health Care', '/static/images/memory_foam_pillow.png', 'Beximco Pharmaceuticals'),
            ('Knee Support Brace', 60.00, 30, 15, 4.2, 'Supports knee joint.', 'Health Care', '/static/images/knee_support_brace.png', 'ACME Laboratories'),
            ('Back Support Belt', 70.00, 20, 10, 4.1, 'Supports lower back.', 'Health Care', '/static/images/back_support_belt.png', 'Renata Limited'),
            ('Walking Stick', 40.00, 50, 25, 4.0, 'Mobility aid.', 'Health Care', '/static/images/walking_stick.png', 'Incepta Pharmaceuticals'),
            ('Wheelchair Foldable', 300.00, 10, 5, 4.3, 'Portable wheelchair.', 'Health Care', '/static/images/wheelchair_foldable.png', 'ACI Limited'),
            ('Crutches Pair', 50.00, 30, 15, 4.2, 'Mobility aid for injured legs.', 'Health Care', '/static/images/crutches_pair.png', 'Aristopharma'),
            ('Blood Glucose Test Strips', 60.00, 40, 20, 4.1, 'For glucometer testing.', 'Medical Devices', '/static/images/blood_glucose_test_strips.png', 'Eskayef Pharmaceuticals'),
            ('Lancets', 25.00, 80, 40, 4.0, 'For blood testing.', 'Medical Devices', '/static/images/lancets.png', 'Opsonin Pharma'),
            ('Pregnancy Test Kit', 30.00, 50, 25, 4.2, 'Detects pregnancy.', 'Diagnostics', '/static/images/pregnancy_test_kit.png', 'Drug International'),
            ('Ovulation Test Kit', 35.00, 40, 20, 4.1, 'Predicts ovulation.', 'Diagnostics', '/static/images/ovulation_test_kit.png', 'Square Pharmaceuticals'),
            ('Blood Pressure Cuff Manual', 45.00, 30, 15, 4.0, 'Manual BP measurement.', 'Medical Devices', '/static/images/blood_pressure_cuff_manual.png', 'Beximco Pharmaceuticals'),
            ('Digital Thermometer', 50.00, 60, 30, 4.2, 'Digital temperature reading.', 'Medical Devices', '/static/images/digital_thermometer.png', 'ACME Laboratories'),
            ('Pulse Oximeter', 70.00, 40, 20, 4.1, 'Measures oxygen saturation.', 'Medical Devices', '/static/images/pulse_oximeter.png', 'Renata Limited'),
            ('Medical Gloves Powder-Free', 20.00, 100, 50, 4.2, 'Powder-free latex gloves.', 'Hygiene', '/static/images/medical_gloves_powder-free.png', 'Incepta Pharmaceuticals'),
            ('Surgical Gown', 80.00, 30, 15, 4.1, 'Protective surgical gown.', 'Hygiene', '/static/images/surgical_gown.png', 'ACI Limited'),
            ('Face Shield', 25.00, 60, 30, 4.2, 'Protects face during procedures.', 'Hygiene', '/static/images/face_shield.png', 'Aristopharma'),
            ('Hand Wash Liquid', 15.00, 120, 60, 4.0, 'Antibacterial hand wash.', 'Hygiene', '/static/images/hand_wash_liquid.png', 'Eskayef Pharmaceuticals'),
            ('Disinfectant Wipes', 12.00, 100, 50, 4.1, 'Kills germs on surfaces.', 'Hygiene', '/static/images/disinfectant_wipes.png', 'Opsonin Pharma');""")

        # Add products that are not already in the customer's database.
        cursor.execute("""
            INSERT INTO medicines
              (name, price, stock_quantity, sold_quantity, ratings, details, category, image, company)
            SELECT s.name, s.price, s.stock_quantity, s.sold_quantity, s.ratings,
                   s.details, s.category, s.image, s.company
            FROM medicine_seed s
            LEFT JOIN medicines m ON LOWER(TRIM(m.name)) = LOWER(TRIM(s.name))
            WHERE m.id IS NULL
        """)

        # Repair metadata for matching existing products. This is what makes
        # old databases pick up company names and the bundled local images.
        cursor.execute("""
            UPDATE medicines m
            JOIN medicine_seed s ON LOWER(TRIM(m.name)) = LOWER(TRIM(s.name))
            SET m.category = s.category,
                m.company = s.company,
                m.image = s.image
        """)
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM medicines")
        total = cursor.fetchone()[0]
        print(f"[MEDICINE SETUP] Catalog ready: {total} products.")
    except mysql.connector.Error as err:
        conn.rollback()
        print(f"[MEDICINE SETUP] Catalog sync error: {err}")
    finally:
        cursor.close()
        conn.close()

seed_medicine_catalog()


# ==================== B2B / B2C + WHOLESALE PRICING (NEW) ====================
# These columns are added on top of the existing schema without touching
# anything that was already there. Wrapped in try/except so re-running the
# app never crashes even if the columns already exist from a previous run.
def setup_b2b_wholesale_columns():
    conn = get_db_connection()
    if not conn:
        print("[B2B SETUP] Could not connect to MySQL, skipping B2B/wholesale setup.")
        return
    cursor = conn.cursor()

    b2b_alterations = [
        "ALTER TABLE `users` ADD COLUMN `account_type` VARCHAR(10) DEFAULT 'b2c'",
        "ALTER TABLE `users` ADD COLUMN `business_name` VARCHAR(255) DEFAULT NULL",
        "ALTER TABLE `users` ADD COLUMN `trade_license` VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE `medicines` ADD COLUMN `wholesale_price` DECIMAL(10,2) DEFAULT NULL",
        "ALTER TABLE `medicines` ADD COLUMN `min_bulk_qty` INT DEFAULT NULL",
    ]

    for statement in b2b_alterations:
        try:
            cursor.execute(statement)
            conn.commit()
        except mysql.connector.Error as err:
            # Error 1060 = Duplicate column name -> column already exists, safe to ignore
            if err.errno != 1060:
                print(f"[B2B SETUP] {err}")

    # Seed a default wholesale price (15% off) + minimum bulk quantity (20)
    # for any medicine that doesn't have one set yet. Safe to re-run.
    try:
        cursor.execute("""
            UPDATE medicines
            SET wholesale_price = ROUND(price * 0.82, 2),
                min_bulk_qty = 1
            WHERE wholesale_price IS NULL
        """)
        conn.commit()
    except mysql.connector.Error as err:
        print(f"[B2B SETUP] Could not seed wholesale prices: {err}")

    cursor.close()
    conn.close()
    print("[B2B SETUP] B2B/B2C account fields and wholesale pricing ready.")

setup_b2b_wholesale_columns()

# ==================== CATALOG / SAFETY / PRICING ENHANCEMENTS ====================
def setup_catalog_enhancements():
    """Add storefront fields without breaking an existing MediHome database."""
    conn = get_db_connection()
    if not conn:
        print("[CATALOG SETUP] Database unavailable; enhancements will retry on next run.")
        return
    cursor = conn.cursor()
    alterations = [
        "ALTER TABLE `medicines` ADD COLUMN `discount_percent` DECIMAL(5,2) DEFAULT 0",
        "ALTER TABLE `medicines` ADD COLUMN `unit_price` DECIMAL(10,2) DEFAULT NULL",
        "ALTER TABLE `medicines` ADD COLUMN `pack_size` INT DEFAULT 10",
        "ALTER TABLE `medicines` ADD COLUMN `prescription_required` TINYINT(1) DEFAULT 0",
        "ALTER TABLE `medicines` ADD COLUMN `ingredients` TEXT DEFAULT NULL",
        "ALTER TABLE `medicines` ADD COLUMN `dosage_form` VARCHAR(80) DEFAULT 'Tablet'",
        "ALTER TABLE `cart` ADD COLUMN `purchase_unit` VARCHAR(20) DEFAULT 'strip'",
    ]
    for sql in alterations:
        try:
            cursor.execute(sql)
            conn.commit()
        except mysql.connector.Error as err:
            if err.errno != 1060:
                print(f"[CATALOG SETUP] {err}")

    # Practical demo pricing: vitamins/supplements receive stronger promotions,
    # while other categories get smaller, believable discounts.
    try:
        cursor.execute("""
            UPDATE medicines
            SET discount_percent = CASE
                WHEN LOWER(category) IN ('vitamins', 'supplements') THEN 20
                WHEN LOWER(category) IN ('allergy', 'herbal') THEN 12
                WHEN LOWER(category) IN ('digestive', 'respiratory') THEN 10
                WHEN LOWER(category) IN ('pain relief', 'dermatology') THEN 8
                WHEN LOWER(category) IN ('diabetes', 'cardiovascular', 'endocrine') THEN 5
                ELSE 6
            END,
            pack_size = CASE
                WHEN LOWER(category) IN ('medical devices', 'hygiene') THEN 1
                WHEN LOWER(dosage_form) LIKE '%syrup%' OR LOWER(dosage_form) LIKE '%liquid%' THEN 1
                ELSE 10
            END
        """)
        cursor.execute("UPDATE medicines SET unit_price = ROUND(price / NULLIF(pack_size, 1), 2) WHERE unit_price IS NULL OR unit_price <= 0")
        # Prescription-required flag for medicines that should be reviewed before dispensing.
        cursor.execute("""
            UPDATE medicines
            SET prescription_required = CASE
                WHEN LOWER(category) IN ('antibiotics') THEN 1
                WHEN LOWER(name) REGEXP 'amoxicillin|ciprofloxacin|valacyclovir|oseltamivir|finasteride|tadalafil' THEN 1
                ELSE prescription_required
            END
        """)
        # Useful, product-specific ingredient text for the demo catalog.
        cursor.execute("UPDATE medicines SET ingredients = COALESCE(NULLIF(ingredients,''), details) WHERE ingredients IS NULL OR ingredients = ''")
        cursor.execute("""
            UPDATE medicines SET ingredients = CASE
                WHEN LOWER(name) LIKE 'paracetamol%' THEN 'Paracetamol'
                WHEN LOWER(name) LIKE 'napa extra%' THEN 'Paracetamol + Caffeine'
                WHEN LOWER(name) LIKE 'ibuprofen%' THEN 'Ibuprofen'
                WHEN LOWER(name) LIKE 'omeprazole%' THEN 'Omeprazole'
                WHEN LOWER(name) LIKE 'esomeprazole%' THEN 'Esomeprazole'
                WHEN LOWER(name) LIKE 'domperidone%' THEN 'Domperidone'
                WHEN LOWER(name) LIKE 'cetirizine%' THEN 'Cetirizine Hydrochloride'
                WHEN LOWER(name) LIKE 'loratadine%' THEN 'Loratadine'
                WHEN LOWER(name) LIKE 'amoxicillin%' THEN 'Amoxicillin'
                WHEN LOWER(name) LIKE 'azithromycin%' THEN 'Azithromycin'
                WHEN LOWER(name) LIKE 'metformin%' THEN 'Metformin Hydrochloride'
                WHEN LOWER(name) LIKE 'vitamin d3%' THEN 'Cholecalciferol (Vitamin D3)'
                WHEN LOWER(name) LIKE 'vitamin b12%' THEN 'Cyanocobalamin (Vitamin B12)'
                WHEN LOWER(name) LIKE 'zinc%' THEN 'Zinc'
                ELSE ingredients
            END
        """)
        conn.commit()
    except mysql.connector.Error as err:
        print(f"[CATALOG SETUP] Pricing/safety update failed: {err}")
    cursor.close()
    conn.close()
    print("[CATALOG SETUP] Discounts, unit pricing and prescription flags ready.")

setup_catalog_enhancements()


def seed_additional_medicines():
    """Add a few recognizable medicines to older installations without duplicating rows."""
    conn = get_db_connection()
    if not conn:
        return
    cur = conn.cursor()
    rows = [
        ('Domperidone 10mg', 18.00, 80, 'Digestive', '/static/images/domperidone_10mg.png', 'Square Pharmaceuticals', 'Domperidone 10 mg', 'Prescription review may be required depending on indication.', 10, 0),
        ('Esomeprazole 20mg', 32.00, 60, 'Digestive', '/static/images/esomeprazole_20mg.png', 'Incepta Pharmaceuticals', 'Esomeprazole 20 mg', 'Reduces gastric acid production.', 10, 0),
        ('Azithromycin 500mg', 70.00, 40, 'Antibiotics', '/static/images/azithromycin_500mg.png', 'Renata Limited', 'Azithromycin 500 mg', 'Antibiotic; prescription required.', 10, 1),
        ('ORS Lemon Sachet', 8.00, 120, 'Hydration', '/static/images/ors_lemon_sachet.png', 'ACME Laboratories', 'Oral rehydration salts', 'Helps replace fluids and electrolytes during dehydration.', 1, 0),
    ]
    for name, price, stock, category, image, company, ingredients, details, pack_size, rx in rows:
        try:
            cur.execute("""
                INSERT INTO medicines (name, price, stock_quantity, sold_quantity, ratings, details, category, image, company, pack_size, unit_price, prescription_required, ingredients, dosage_form)
                SELECT %s,%s,%s,0,0,%s,%s,%s,%s,%s,ROUND(%s/NULLIF(%s,1),2),%s,%s,'Tablet'
                WHERE NOT EXISTS (SELECT 1 FROM medicines WHERE LOWER(TRIM(name))=LOWER(TRIM(%s)))
            """, (name, price, stock, details, category, image, company, pack_size, price, pack_size, rx, ingredients, name))
        except mysql.connector.Error as err:
            print(f'[CATALOG SETUP] Could not add {name}: {err}')
    conn.commit()
    cur.close(); conn.close()

seed_additional_medicines()


def setup_order_group_columns():
    """Add a shared checkout/order reference so one checkout has one Order ID."""
    conn = get_db_connection()
    if not conn:
        print("[ORDER SETUP] Could not connect to MySQL, skipping order-group setup.")
        return
    cursor = conn.cursor()
    try:
        for table in ("orders", "all_orders", "dborders"):
            try:
                cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `order_group_id` VARCHAR(40) DEFAULT NULL")
                conn.commit()
            except mysql.connector.Error as err:
                if err.errno != 1060:
                    print(f"[ORDER SETUP] {table}: {err}")
        conn.commit()
        print("[ORDER SETUP] Shared order reference ready.")
    finally:
        cursor.close()
        conn.close()

setup_order_group_columns()


def apply_wholesale_pricing(items, user):
    """Apply retail promotions first, then B2B pricing when eligible."""
    is_b2b = bool(user) and user.get('account_type') == 'b2b'
    for item in items:
        base_price = Decimal(str(item.get('price') or '0'))
        discount_percent = Decimal(str(item.get('discount_percent') or '0'))
        sale_price = (base_price * (Decimal('1') - discount_percent / Decimal('100'))).quantize(Decimal('0.01'))
        item['original_price'] = base_price
        item['discount_percent'] = discount_percent
        item['sale_price'] = sale_price
        item['price'] = sale_price
        item['wholesale_applied'] = False
        wholesale_price = item.get('wholesale_price')
        min_bulk_qty = item.get('min_bulk_qty') or 0
        qty = int(item.get('quantity') or 0)
        if is_b2b and wholesale_price and min_bulk_qty > 0 and qty >= min_bulk_qty:
            item['price'] = Decimal(str(wholesale_price)).quantize(Decimal('0.01'))
            item['wholesale_applied'] = True
    return items


def item_unit_price(item, purchase_unit='strip'):
    """Return the selling price for one selected unit/strip."""
    price = Decimal(str(item.get('price') or '0'))
    pack_size = int(item.get('pack_size') or 10)
    if purchase_unit == 'unit' and pack_size > 1:
        return (price / Decimal(pack_size)).quantize(Decimal('0.01'))
    return price

# ==================== DECORATORS ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You need to be logged in to access this page.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('You need admin privileges to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== SETTINGS MANAGEMENT ====================
def get_settings():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get current settings
        cursor.execute("SELECT * FROM settings")
        settings_data = cursor.fetchall()
        
        # Convert to dictionary for easier access
        settings = {}
        for setting in settings_data:
            settings[setting['setting_key']] = setting['setting_value']
        
        cursor.close()
        connection.close()
        
        return settings
    return {}

# ==================== USER AUTHENTICATION ROUTES ====================
# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].lower()
        password = request.form["password"]

        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            cursor.close()
            connection.close()

            if user:
                if user["is_verified"] == 0:
                    flash("Please verify your email before login", "warning")
                    return redirect(url_for("verify", email=email))

                # Password check
                if check_password_hash(user["password"], password):
                    session["user_id"] = user["id"]
                    session["user_name"] = user["name"]
                    session["role"] = user.get("role", "user")
                    session["email"] = user["email"]
                    session["account_type"] = user.get("account_type", "b2c")  # NEW: B2B/B2C

                    flash("Login successful!", "success")

                    # Redirect based on role
                    if session["role"] == "admin":
                        return redirect(url_for("admin_dashboard"))
                    else:
                        return redirect(url_for("index"))

            flash("Invalid email or password", "danger")
            return render_template("login.html")

    return render_template("login.html")

# Signup route
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email'].lower()
        phone = request.form.get('phone')
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # ---- NEW: B2B / B2C account type ----
        account_type = request.form.get('account_type', 'b2c')
        if account_type not in ('b2c', 'b2b'):
            account_type = 'b2c'
        business_name = request.form.get('business_name', '').strip() if account_type == 'b2b' else None
        trade_license = request.form.get('trade_license', '').strip() if account_type == 'b2b' else None

        if password != confirm_password:
            flash("Passwords do not match", "danger")
            return redirect(url_for('signup'))

        hashed_password = generate_password_hash(password)
        code = f"{random.randint(0, 999999):06d}"
        expiry = datetime.utcnow() + timedelta(minutes=10)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        if user and user['is_verified'] == 1:
            flash("Email already registered", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for('signup'))

        try:
            if user:
                cursor.execute("""
                    UPDATE users SET name=%s, phone=%s, password=%s,
                    verification_code=%s, code_expiry=%s, is_verified=0,
                    account_type=%s, business_name=%s, trade_license=%s
                    WHERE email=%s
                """, (name, phone, hashed_password, code, expiry,
                      account_type, business_name, trade_license, email))
            else:
                cursor.execute("""
                    INSERT INTO users (name, email, phone, password,
                    is_verified, verification_code, code_expiry,
                    account_type, business_name, trade_license)
                    VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s)
                """, (name, email, phone, hashed_password, code, expiry,
                      account_type, business_name, trade_license))

            conn.commit()

            # ✅ Send professional HTML email
            email_sent = send_email(
                subject="MediHome Verification Code",
                to_email=email,
                user_name=name,
                code=code
            )

            if email_sent:
                flash("Verification code sent to your email", "info")
            else:
                flash("Email is not configured. The verification code was printed in the terminal.", "warning")
            return redirect(url_for('verify', email=email, name=name))

        finally:
            cursor.close()
            conn.close()

    return render_template("signup.html")

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    email = request.args.get('email')  
    name = request.args.get('name', 'User')  

    if request.method == 'POST':
        email = request.form['email']
        code = request.form['code']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        if not user:
            flash("User not found", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for('signup'))

        if user['verification_code'] != code:
            flash("Invalid verification code", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for('verify', email=email, name=name))

        if user['code_expiry'] < datetime.utcnow():
            flash("Code expired", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for('verify', email=email, name=name))

        # All good, verify user
        cursor.execute("""
            UPDATE users SET is_verified=1,
            verification_code=NULL, code_expiry=NULL
            WHERE email=%s
        """, (email,))
        conn.commit()
        cursor.close()
        conn.close()

        flash("✅ Email verified successfully!", "success")
        return redirect(url_for('login'))

    
    return render_template(
        "verify.html",
        email=email,
        name=name,
        current_year=datetime.utcnow().year
    )

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('index'))  # redirect to homepage


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('You have been logged out from admin panel successfully', 'info')
    return redirect(url_for('index'))



# ==================== MAIN APPLICATION ROUTES ====================
# Home route
@app.route('/')
def index():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get top selling products
        cursor.execute("""
            SELECT * FROM medicines 
            ORDER BY sold_quantity DESC 
            LIMIT 4
        """)
        top_products = cursor.fetchall()
        
        # Get categories
        cursor.execute("SELECT DISTINCT category FROM medicines")
        categories = cursor.fetchall()
        
        # Get reviews with user information
        cursor.execute("""
            SELECT r.*, u.name, u.image as user_image, m.name as medicine_name 
            FROM reviews r
            JOIN users u ON r.user_id = u.id
            LEFT JOIN medicines m ON r.medicine_id = m.id
            ORDER BY r.review_date DESC
            LIMIT 3
        """)
        reviews = cursor.fetchall()
        
        # Get user info if logged in
        user = None
        cart_count = 0
        if 'user_id' in session:
            cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
            user = cursor.fetchone()
            
            # Get cart count
            cursor.execute("""
                SELECT COUNT(*) as count FROM cart 
                WHERE user_id = %s
            """, (session['user_id'],))
            cart_count = cursor.fetchone()['count']
        
        # Get statistics
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM medicines")
        total_medicines = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM all_orders")
        total_orders = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM prescriptions")
        total_prescriptions = cursor.fetchone()['total']
        
        cursor.close()
        connection.close()
        
        return render_template('index.html', 
                              top_products=top_products, 
                              categories=categories, 
                              reviews=reviews,
                              user=user,
                              cart_count=cart_count,
                              total_users=total_users,
                              total_medicines=total_medicines,
                              total_orders=total_orders,
                              total_prescriptions=total_prescriptions)
    return "Database connection error", 500


# Medicine Details route
@app.route('/medicine_details/<int:medicine_id>')
def medicine_details(medicine_id):
    # Get cart count for the header
    cart_count = 0
    user_id = session.get('user_id')
    user = None
    
    if user_id:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            # Get user info
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            # Get cart count
            cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
            cart_count = cursor.fetchone()['count']
            
            cursor.close()
            connection.close()
    
    # Get medicine details
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM medicines WHERE id = %s", (medicine_id,))
        medicine = cursor.fetchone()
        
        # Get recommended medicines
        if medicine:
            recommended_medicines = []
            
            # First try to get from the same category
            if medicine['category']:
                cursor.execute("""
                    SELECT * FROM medicines 
                    WHERE category = %s AND id != %s 
                    ORDER BY RAND() 
                    LIMIT 4
                """, (medicine['category'], medicine_id))
                recommended_medicines = cursor.fetchall()
                print(f"Found {len(recommended_medicines)} medicines in same category: {medicine['category']}")
            
            # If we don't have enough, get random medicines
            if len(recommended_medicines) < 4:
                needed = 4 - len(recommended_medicines)
                exclude_ids = [medicine_id] + [med['id'] for med in recommended_medicines]
                placeholders = ','.join(['%s'] * len(exclude_ids))
                cursor.execute(f"""
                    SELECT * FROM medicines 
                    WHERE id NOT IN ({placeholders})
                    ORDER BY RAND() 
                    LIMIT %s
                """, exclude_ids + [needed])
                additional_medicines = cursor.fetchall()
                recommended_medicines.extend(additional_medicines)
                print(f"Added {len(additional_medicines)} random medicines")
            
            print(f"Total recommended medicines: {len(recommended_medicines)}")
            medicine['image'] = image_url_filter(medicine.get('image'))
            base = Decimal(str(medicine.get('price') or 0))
            dp = Decimal(str(medicine.get('discount_percent') or 0))
            medicine['sale_price'] = (base * (Decimal('1') - dp/Decimal('100'))).quantize(Decimal('0.01'))
            medicine['unit_price'] = medicine.get('unit_price') or (medicine['sale_price'] / Decimal(int(medicine.get('pack_size') or 10))).quantize(Decimal('0.01'))
            medicine['ingredients'] = medicine.get('ingredients') or medicine.get('details') or 'See product label.'
            medicine['details'] = medicine.get('details') or 'Please check the product label and follow professional advice where appropriate.'
            for rec in recommended_medicines:
                rec['image'] = image_url_filter(rec.get('image'))
                base_rec = Decimal(str(rec.get('price') or 0)); dp_rec = Decimal(str(rec.get('discount_percent') or 0))
                rec['sale_price'] = (base_rec * (Decimal('1') - dp_rec/Decimal('100'))).quantize(Decimal('0.01'))
            cursor.close()
            connection.close()
            
            return render_template('view-details.html', 
                                  medicine=medicine, 
                                  recommended_medicines=recommended_medicines,
                                  cart_count=cart_count, 
                                  user=user)
        else:
            cursor.close()
            connection.close()
            flash('Medicine not found', 'danger')
            return redirect(url_for('medicines'))
    
    return "Database connection error", 500


# Medicines by category route
@app.route('/medicines/<category>')
def medicines_by_category(category):
    # This is a placeholder since we're not building the page now
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM medicines WHERE category = %s", (category,))
        medicines = cursor.fetchall()
        cursor.close()
        connection.close()
        
        return f"Medicines in {category} category: {len(medicines)} items"
    
    return "Category not found", 404


# Medicines page route
@app.route('/medicines')
@app.route('/medicines/<category>')
def medicines(category=None):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get filter parameters
        search = request.args.get('search', '')
        group = request.args.get('group', 'all')          # product-name filter (e.g. Paracetamol, Omeprazole)
        company = request.args.get('company', 'all')      # medicine company/manufacturer filter
        availability = request.args.get('availability', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = 12  
        
        # Build the base query
        query = "SELECT * FROM medicines WHERE 1=1"
        params = []
        
        # Add category filter if provided and not 'all' (from the /medicines/<category> URL)
        if category and category != 'all':
            # Make category matching case-insensitive and trim spaces
            query += " AND LOWER(category) = LOWER(%s)"
            params.append(category.strip())
        
        # Medicine Group means a specific medicine family/product name in the storefront.
        if group and group != 'all':
            query += " AND LOWER(TRIM(name)) = LOWER(TRIM(%s))"
            params.append(group.strip())
        
        # Add search filter
        if search:
            query += " AND name LIKE %s"
            params.append(f"%{search}%")
        
        # Add company/manufacturer filter
        if company and company != 'all':
            query += " AND company = %s"
            params.append(company)
        
        # Add availability filter
        if availability != 'all':
            if availability == 'in_stock':
                query += " AND stock_quantity > 10"
            elif availability == 'low_stock':
                query += " AND stock_quantity > 0 AND stock_quantity <= 10"
            elif availability == 'out_of_stock':
                query += " AND stock_quantity = 0"
        
        
        # Get total count for pagination
        count_query = f"SELECT COUNT(*) as total FROM ({query}) as subquery"
        cursor.execute(count_query, params)
        total = cursor.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page
        
        # Add pagination
        offset = (page - 1) * per_page
        query += " LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        cursor.execute(query, params)
        medicines = cursor.fetchall()
        for medicine in medicines:
            image = (medicine.get('image') or '').strip()
            if image and not image.startswith(('http://', 'https://', '/static/')):
                image = '/static/images/' + image.lstrip('/')
            medicine['image'] = image_url_filter(image)
            base = Decimal(str(medicine.get('price') or 0))
            dp = Decimal(str(medicine.get('discount_percent') or 0))
            medicine['sale_price'] = (base * (Decimal('1') - dp/Decimal('100'))).quantize(Decimal('0.01'))
            medicine['unit_price'] = medicine.get('unit_price') or (medicine['sale_price'] / Decimal(int(medicine.get('pack_size') or 10))).quantize(Decimal('0.01'))
            medicine['details'] = medicine.get('details') or 'Please check the product details and follow professional advice where appropriate.'
            medicine['ingredients'] = medicine.get('ingredients') or medicine['details']

        # Medicine-name options for the storefront filter
        cursor.execute("SELECT DISTINCT name FROM medicines ORDER BY name")
        medicine_groups = cursor.fetchall()
        # Keep category data for footer/navigation compatibility.
        cursor.execute("SELECT DISTINCT category FROM medicines ORDER BY category")
        categories = cursor.fetchall()
        
        # Get companies for filter dropdown
        cursor.execute("SELECT DISTINCT company FROM medicines WHERE company IS NOT NULL AND company <> '' ORDER BY company")
        companies = cursor.fetchall()
        
        # Calculate pagination range
        start_page = max(1, page - 2)
        end_page = min(total_pages + 1, page + 3)
        page_range = range(start_page, end_page)
        
        # Get user info if logged in
        user = None
        cart_count = 0
        if 'user_id' in session:
            cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
            user = cursor.fetchone()
            
            # Get cart count
            cursor.execute("""
                SELECT COUNT(*) as count FROM cart 
                WHERE user_id = %s
            """, (session['user_id'],))
            cart_count = cursor.fetchone()['count']
        
        cursor.close()
        connection.close()
        
        return render_template('medicines.html', 
                              medicines=medicines,
                              medicine_groups=medicine_groups,
                              categories=categories,
                              companies=companies,
                              current_category=category,
                              search=search,
                              group=group,
                              company=company,
                              availability=availability,
                              page=page,
                              total_pages=total_pages,
                              page_range=page_range,
                              user=user,
                              cart_count=cart_count)
    return "Database connection error", 500



# ==================== SHOPPING CART ROUTES ====================
# Buy Now route
@app.route('/buy_now', methods=['POST'])
@login_required
def buy_now():
    medicine_id = request.form.get('medicine_id')
    if not medicine_id:
        flash('Medicine not found', 'danger')
        return redirect(url_for('medicines'))

    try:
        quantity = int(request.form.get('quantity', 1))
    except ValueError:
        quantity = 1

    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM medicines WHERE id = %s", (medicine_id,))
        medicine = cursor.fetchone()

        if not medicine:
            flash('Medicine not found', 'danger')
            cursor.close()
            connection.close()
            return redirect(url_for('medicines'))

        if medicine['stock_quantity'] < quantity:
            flash('Not enough stock available', 'danger')
            cursor.close()
            connection.close()
            return redirect(url_for('medicines'))

        cursor.close()
        connection.close()

        return redirect(url_for('checkout', medicine_id=medicine_id, quantity=quantity))

    flash('Database connection error', 'danger')
    return redirect(url_for('medicines'))

# Add to Cart route
@app.route('/add_to_cart', methods=['POST'])
@login_required
def add_to_cart():
    # Check if request is AJAX or form submission
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    # Get data from request
    if is_ajax:
        data = request.get_json() or {}
        medicine_id = data.get('medicine_id')
        quantity = data.get('quantity', 1)
        purchase_unit = data.get('purchase_unit', 'strip')
    else:
        medicine_id = request.form.get('medicine_id')
        quantity = request.form.get('quantity', 1, type=int)
        purchase_unit = request.form.get('purchase_unit', 'strip')
    if purchase_unit not in ('unit', 'strip'):
        purchase_unit = 'strip'
    
    user_id = session.get('user_id')
    
    if not medicine_id or not user_id:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Invalid request'})
        else:
            flash('Invalid request', 'danger')
            return redirect(url_for('medicines'))
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Check if medicine exists and has enough stock
        cursor.execute("SELECT * FROM medicines WHERE id = %s", (medicine_id,))
        medicine = cursor.fetchone()
        
        if not medicine:
            cursor.close()
            connection.close()
            if is_ajax:
                return jsonify({'success': False, 'message': 'Medicine not found'})
            else:
                flash('Medicine not found', 'danger')
                return redirect(url_for('medicines'))
        
        if medicine['stock_quantity'] < quantity:
            cursor.close()
            connection.close()
            if is_ajax:
                return jsonify({'success': False, 'message': 'Not enough stock available'})
            else:
                flash('Not enough stock available', 'danger')
                return redirect(url_for('medicines'))
        
        # Check if item is already in cart
        cursor.execute("SELECT * FROM cart WHERE user_id = %s AND medicine_id = %s", (user_id, medicine_id))
        existing_item = cursor.fetchone()
        
        if existing_item:
            # Update quantity
            new_quantity = existing_item['quantity'] + quantity
            if new_quantity > medicine['stock_quantity']:
                cursor.close()
                connection.close()
                if is_ajax:
                    return jsonify({'success': False, 'message': 'Not enough stock available'})
                else:
                    flash('Not enough stock available', 'danger')
                    return redirect(url_for('medicines'))
            
            cursor.execute("""
                UPDATE cart
                SET quantity = %s, purchase_unit = %s
                WHERE user_id = %s AND medicine_id = %s
            """, (new_quantity, purchase_unit, user_id, medicine_id))
        else:
            cursor.execute("""
                INSERT INTO cart (user_id, medicine_id, quantity, purchase_unit)
                VALUES (%s, %s, %s, %s)
            """, (user_id, medicine_id, quantity, purchase_unit))
        
        # Get updated cart count
        cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
        cart_count = cursor.fetchone()['count']
        
        connection.commit()
        cursor.close()
        connection.close()
        
        if is_ajax:
            return jsonify({
                'success': True, 
                'message': 'Item added to cart successfully!',
                'cart_count': cart_count
            })
        else:
            flash('Item added to cart!', 'success')
            return redirect(url_for('medicines'))
    else:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Database connection error'})
        else:
            flash('Database connection error', 'danger')
            return redirect(url_for('medicines'))

# Cart page route
@app.route('/cart')
@login_required
def cart():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # Get cart items
        cursor.execute("""
            SELECT c.id as cart_id, c.quantity, COALESCE(c.purchase_unit, 'strip') AS purchase_unit, m.*
            FROM cart c
            JOIN medicines m ON c.medicine_id = m.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        # Get user info (needed early now for B2B wholesale pricing)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        # B2B accounts see wholesale price automatically once they hit the
        # medicine's minimum bulk quantity (see apply_wholesale_pricing()).
        cart_items = apply_wholesale_pricing(cart_items, user)

        # Calculate totals using Decimal for precision
        subtotal = Decimal('0.00')
        for item in cart_items:
            item['image'] = image_url_filter(item.get('image'))
            item['line_price'] = item_unit_price(item, item.get('purchase_unit', 'strip'))
            item['sale_price'] = item['price']
            subtotal += item['line_price'] * int(item['quantity'])
        
        # Fixed values for now (can be made dynamic later)
        delivery_fee = Decimal('50.00')
        tax_rate = Decimal('0.10')  # 10% tax
        tax = subtotal * tax_rate
        total = subtotal + delivery_fee + tax
        
        # Get recommendations (medicines not in cart)
        if cart_items:
            cart_medicine_ids = [item['id'] for item in cart_items]
            placeholders = ', '.join(['%s'] * len(cart_medicine_ids))
            cursor.execute(f"""
                SELECT * FROM medicines 
                WHERE id NOT IN ({placeholders})
                ORDER BY sold_quantity DESC 
                LIMIT 4
            """, cart_medicine_ids)
        else:
            cursor.execute("""
                SELECT * FROM medicines 
                ORDER BY sold_quantity DESC 
                LIMIT 4
            """)
        recommendations = cursor.fetchall()
        
        # Get recently viewed (placeholder - random medicines for now)
        cursor.execute("""
            SELECT * FROM medicines 
            ORDER BY RAND() 
            LIMIT 6
        """)
        recently_viewed = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return render_template('cart.html', 
                              cart_items=cart_items,
                              subtotal=subtotal,
                              delivery_fee=delivery_fee,
                              tax=tax,
                              total=total,
                              recommendations=recommendations,
                              recently_viewed=recently_viewed,
                              user=user)
    return "Database connection error", 500

# Change whether a cart item is bought as an individual unit or a strip/pack.
@app.route('/change_cart_unit', methods=['POST'])
@login_required
def change_cart_unit():
    cart_id = request.form.get('cart_id', type=int)
    purchase_unit = request.form.get('purchase_unit', 'strip')
    if purchase_unit not in ('unit', 'strip'):
        purchase_unit = 'strip'
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("UPDATE cart SET purchase_unit=%s WHERE id=%s AND user_id=%s", (purchase_unit, cart_id, session['user_id']))
        conn.commit(); cur.close(); conn.close()
        flash('Purchase type updated.', 'success')
    return redirect(url_for('cart'))

# Update cart route
@app.route('/update_cart', methods=['POST'])
@login_required
def update_cart():
    cart_id = request.form.get('cart_id')
    action = request.form.get('action')
    user_id = session['user_id']
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        if action == 'increase' or action == 'decrease':
            # Get current quantity and medicine info
            cursor.execute("""
                SELECT c.quantity, m.stock_quantity, m.id as medicine_id
                FROM cart c
                JOIN medicines m ON c.medicine_id = m.id
                WHERE c.id = %s AND c.user_id = %s
            """, (cart_id, user_id))
            cart_item = cursor.fetchone()
            
            if not cart_item:
                flash('Cart item not found', 'danger')
                return redirect(url_for('cart'))
            
            new_quantity = cart_item['quantity']
            if action == 'increase':
                if new_quantity < cart_item['stock_quantity']:
                    new_quantity += 1
                else:
                    flash('Not enough stock available', 'danger')
                    return redirect(url_for('cart'))
            elif action == 'decrease':
                if new_quantity > 1:
                    new_quantity -= 1
                else:
                    flash('Quantity cannot be less than 1', 'danger')
                    return redirect(url_for('cart'))
            
            # Update quantity
            cursor.execute("""
                UPDATE cart SET quantity = %s 
                WHERE id = %s AND user_id = %s
            """, (new_quantity, cart_id, user_id))
            connection.commit()
            flash('Cart updated successfully', 'success')
            
        elif action == 'remove':
            # Remove item from cart
            cursor.execute("""
                DELETE FROM cart 
                WHERE id = %s AND user_id = %s
            """, (cart_id, user_id))
            connection.commit()
            flash('Item removed from cart', 'success')
            
        elif action == 'clear':
            # Clear entire cart
            cursor.execute("""
                DELETE FROM cart 
                WHERE user_id = %s
            """, (user_id,))
            connection.commit()
            flash('Cart cleared successfully', 'success')
        
        cursor.close()
        connection.close()
        return redirect(url_for('cart'))
    
    flash('Database connection error', 'danger')
    return redirect(url_for('cart'))

# Add to cart from recommendations
@app.route('/add_to_cart_from_recommendations', methods=['POST'])
@login_required
def add_to_cart_from_recommendations():
    medicine_id = request.form.get('medicine_id')
    user_id = session['user_id']
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Check if medicine is already in cart
        cursor.execute("""
            SELECT * FROM cart 
            WHERE user_id = %s AND medicine_id = %s
        """, (user_id, medicine_id))
        existing_item = cursor.fetchone()
        
        if existing_item:
            # Update quantity
            cursor.execute("""
                UPDATE cart 
                SET quantity = quantity + 1 
                WHERE user_id = %s AND medicine_id = %s
            """, (user_id, medicine_id))
        else:
            # Add new item
            cursor.execute("""
                INSERT INTO cart (user_id, medicine_id, quantity) 
                VALUES (%s, %s, 1)
            """, (user_id, medicine_id))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        flash('Item added to cart!', 'success')
    else:
        flash('Database connection error', 'danger')
    
    return redirect(url_for('cart'))




# ==================== CHECKOUT AND ORDER MANAGEMENT ROUTES ====================

# ---------------- Checkout Route ----------------
@app.route('/checkout', methods=['GET', 'POST'])
@app.route('/checkout/<int:medicine_id>', methods=['GET', 'POST'])
@app.route('/checkout/<int:medicine_id>/<int:quantity>', methods=['GET', 'POST'])
@login_required
def checkout(medicine_id=None, quantity=1):
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('medicines'))

    cursor = connection.cursor(dictionary=True)
    user_id = session['user_id']

    # Get user info
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    # Delivery options
    address = user.get('address') or '' if user else ''
    inside_dhaka = 'dhaka' in address.lower()
    if inside_dhaka:
        delivery_options = {'standard': Decimal('70.00'), 'fast': Decimal('100.00'), 'sameday': Decimal('150.00')}
    else:
        delivery_options = {'standard': Decimal('120.00'), 'fast': Decimal('150.00')}

    # Get cart or buy_now
    if medicine_id:
        cursor.execute("SELECT * FROM medicines WHERE id = %s", (medicine_id,))
        medicine = cursor.fetchone()
        if not medicine:
            flash('Medicine not found', 'danger')
            cursor.close()
            connection.close()
            return redirect(url_for('medicines'))

        cart_items = [{
            'id': medicine['id'],
            'name': medicine['name'],
            'price': medicine['price'],
            'quantity': quantity,
            'purchase_unit': 'strip',
            'image': image_url_filter(medicine['image']),
            'stock_quantity': medicine['stock_quantity'],
            'wholesale_price': medicine.get('wholesale_price'),
            'min_bulk_qty': medicine.get('min_bulk_qty')
        }]
        source = 'buy_now'
    else:
        cursor.execute("""
            SELECT c.id as cart_id, c.quantity, COALESCE(c.purchase_unit, 'strip') AS purchase_unit, m.*
            FROM cart c
            JOIN medicines m ON c.medicine_id = m.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()
        source = 'cart'

    if not cart_items and source == 'cart':
        flash('Your cart is empty', 'danger')
        cursor.close()
        connection.close()
        return redirect(url_for('cart'))

    # B2B accounts automatically get wholesale pricing once quantity meets
    # each medicine's minimum bulk quantity (see apply_wholesale_pricing()).
    cart_items = apply_wholesale_pricing(cart_items, user)

    # Calculate subtotal
    for item in cart_items:
        item['image'] = image_url_filter(item.get('image'))
        item['line_price'] = item_unit_price(item, item.get('purchase_unit', 'strip'))
    subtotal = sum(item['line_price'] * int(item['quantity']) for item in cart_items)
    tax = subtotal * Decimal('0.05')
    checkout_delivery_fee = Decimal('70.00') if inside_dhaka else Decimal('120.00')
    total = subtotal + tax + checkout_delivery_fee
    applied_promo = None
    discount = Decimal('0.00')

    # Promo handling
    if request.method == 'POST' and 'promo_code' in request.form:
        promo_code_input = request.form.get('promo_code', '').strip().upper()
        cursor.execute("""
            SELECT * FROM promo_codes
            WHERE code = %s AND is_active = TRUE
            AND valid_from <= CURDATE() AND valid_until >= CURDATE()
            AND used_count < max_uses
        """, (promo_code_input,))
        promo_code = cursor.fetchone()

        if promo_code:
            # Check if user already used promo
            cursor.execute("""
                SELECT * FROM user_promo_codes
                WHERE user_id = %s AND promo_code_id = %s
            """, (user_id, promo_code['id']))
            user_promo = cursor.fetchone()

            if not user_promo:
                # Save promo info in session for GET
                session['applied_promo_id'] = promo_code['id']
                session['discount'] = float(subtotal * (Decimal(str(promo_code['discount_value'])) / 100) 
                                            if promo_code['discount_type']=='percentage' else
                                            Decimal(str(promo_code['discount_value'])) if promo_code['discount_type']=='fixed' else 0)
                flash('Promo code applied successfully!', 'success')
            else:
                flash('You have already used this promo code', 'danger')
        else:
            flash('Invalid or expired promo code', 'danger')

        cursor.close()
        connection.close()

        # Redirect to GET to show flash
        if medicine_id:
            return redirect(url_for('checkout', medicine_id=medicine_id, quantity=quantity))
        return redirect(url_for('checkout'))

    # GET request
    # Apply session promo if exists
    if 'applied_promo_id' in session:
        applied_promo = {'id': session['applied_promo_id']}
        discount = Decimal(str(session.get('discount', '0.00')))
        total -= discount

    b2b_minimum_remaining = max(Decimal('0.00'), Decimal('3000.00') - subtotal) if user and user.get('account_type') == 'b2b' else Decimal('0.00')

    # Get cart count
    cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
    cart_count = cursor.fetchone()['count']
    
    cursor.close()
    connection.close()

    return render_template('checkout.html',
                           cart_items=cart_items,
                           subtotal=subtotal,
                           delivery_fee=checkout_delivery_fee,
                           tax=tax,
                           discount=discount,
                           total=total,
                           user=user,
                           source=source,
                           delivery_options=delivery_options,
                           inside_dhaka=inside_dhaka,
                           applied_promo=applied_promo,
                           cart_count=cart_count,
                           b2b_minimum_remaining=b2b_minimum_remaining)

# ---------------- Place Order Route ----------------
@app.route('/place_order', methods=['POST'])
@login_required
def place_order():
    user_id = session['user_id']
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('cart'))

    cursor = connection.cursor(dictionary=True)

    # User info
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    first_name = request.form.get('firstName')
    last_name = request.form.get('lastName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    address = request.form.get('address')
    city = request.form.get('city')
    postal_code = request.form.get('postalCode')
    instructions = request.form.get('instructions', '')
    payment_method = request.form.get('paymentMethod', 'cod')
    source = request.form.get('source', 'cart')

    full_address = f"{address}, {city}, {postal_code}" if address or city or postal_code else ""
    inside_dhaka = 'dhaka' in full_address.lower()
    delivery_fee = Decimal('70.00') if inside_dhaka else Decimal('120.00')

    # Re-read prices from the database so hidden form fields cannot change prices.
    item_ids = request.form.getlist('item_id')
    item_quantities = request.form.getlist('item_quantity')
    item_units = request.form.getlist('item_unit')
    if not item_ids:
        flash('No items in order', 'danger')
        cursor.close(); connection.close(); return redirect(url_for('cart'))

    item_rows = []
    subtotal = Decimal('0.00')
    any_rx = False
    for i, item_id in enumerate(item_ids):
        try:
            quantity = max(1, int(item_quantities[i]))
        except (ValueError, IndexError):
            quantity = 1
        purchase_unit = item_units[i] if i < len(item_units) and item_units[i] in ('unit','strip') else 'strip'
        cursor.execute("SELECT * FROM medicines WHERE id=%s", (item_id,))
        med = cursor.fetchone()
        if not med:
            flash('One of the selected medicines is no longer available.', 'danger')
            cursor.close(); connection.close(); return redirect(url_for('cart'))
        if quantity > int(med.get('stock_quantity') or 0):
            flash(f"Not enough stock for {med['name']}.", 'danger')
            cursor.close(); connection.close(); return redirect(url_for('cart'))
        base = Decimal(str(med.get('price') or 0))
        dp = Decimal(str(med.get('discount_percent') or 0))
        sale = (base * (Decimal('1') - dp/Decimal('100'))).quantize(Decimal('0.01'))
        med['price'] = sale
        if user and user.get('account_type') == 'b2b' and med.get('wholesale_price'):
            med['price'] = Decimal(str(med['wholesale_price'])).quantize(Decimal('0.01'))
        line_price = item_unit_price(med, purchase_unit)
        subtotal += line_price * quantity
        any_rx = any_rx or bool(med.get('prescription_required'))
        item_rows.append((med, quantity, purchase_unit, line_price))

    if user and user.get('account_type') == 'b2b' and subtotal < Decimal('3000.00'):
        flash(f'B2B wholesale orders require a minimum merchandise subtotal of ৳3,000. Current subtotal: ৳{subtotal:.2f}.', 'warning')
        cursor.close(); connection.close(); return redirect(url_for('checkout'))

    if any_rx:
        cursor.execute("SELECT id FROM prescriptions WHERE user_id=%s AND image_path IS NOT NULL ORDER BY created_at DESC LIMIT 1", (user_id,))
        rx = cursor.fetchone()
        if not rx:
            flash('A prescription is required for one or more selected medicines. Please upload it before placing the order.', 'warning')
            cursor.close(); connection.close(); return redirect(url_for('upload_prescription_page'))

    tax = subtotal * Decimal('0.05')
    total_amount = subtotal + tax + delivery_fee

    # Promo handling
    promo_id = request.form.get('promo_code_id', type=int)
    discount = Decimal('0.00')
    if promo_id:
        cursor.execute("SELECT * FROM promo_codes WHERE id=%s", (promo_id,))
        promo = cursor.fetchone()
        if promo:
            if promo['discount_type'] == 'percentage':
                discount = subtotal * (Decimal(str(promo['discount_value'])) / 100)
            elif promo['discount_type'] == 'fixed':
                discount = Decimal(str(promo['discount_value']))
            elif promo['discount_type'] == 'free_delivery':
                discount = delivery_fee
            total_amount -= discount

    # One checkout = one customer-facing Order ID, even when the cart contains many medicines.
    order_group_id = f"MH-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
    order_ids = []
    for med, quantity, purchase_unit, unit_price in item_rows:
        item_name = med['name']
        price = unit_price * quantity
        for table in ['orders', 'all_orders', 'dborders']:
            cursor.execute(f"""
                INSERT INTO {table} (
                    ordered_by, phone, email, address, product,
                    quantity, unit_price, price, delivery_charge, discount,
                    payment_method, special_instruction, status, order_group_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                f"{first_name} {last_name}", phone, email, full_address, item_name,
                quantity, unit_price, price, delivery_fee, discount,
                payment_method, instructions, 'Pending', order_group_id
            ))
            order_ids.append(cursor.lastrowid)

        # Update stock
        cursor.execute("SELECT stock_quantity, sold_quantity FROM medicines WHERE id=%s", (med['id'],))
        medicine = cursor.fetchone()
        if medicine:
            new_stock = medicine['stock_quantity'] - quantity
            new_sold = medicine['sold_quantity'] + quantity
            cursor.execute("UPDATE medicines SET stock_quantity=%s, sold_quantity=%s WHERE id=%s",
                           (new_stock, new_sold, med['id']))

    # Promo usage
    if promo_id:
        cursor.execute("INSERT INTO user_promo_codes (user_id, promo_code_id) VALUES (%s, %s)",
                       (user_id, promo_id))
        cursor.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE id=%s", (promo_id,))

    # Clear cart if needed
    if source == 'cart':
        cursor.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))

    connection.commit()
    cursor.close()
    connection.close()

    # Send order confirmation email
    send_order_email(
        to_email=email,
        user_name=f"{first_name} {last_name}",
        order_ref=order_group_id,
        total_amount=total_amount
    )

    session["order_just_placed"] = True
    flash("Order placed successfully!", "success")
    
    return redirect(url_for("order_confirmation", order_ids=order_group_id))

# Order confirmation route
@app.route('/order_confirmation/<order_ids>')
@login_required
def order_confirmation(order_ids):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # New orders use one shared customer-facing reference. Legacy numeric
        # links are still supported for older records.
        if order_ids.startswith('MH-'):
            cursor.execute("SELECT * FROM all_orders WHERE order_group_id = %s ORDER BY id ASC", (order_ids,))
        else:
            order_id_list = order_ids.split(',')
            placeholders = ', '.join(['%s'] * len(order_id_list))
            cursor.execute(f"SELECT * FROM all_orders WHERE id IN ({placeholders}) ORDER BY id ASC", order_id_list)
        orders = cursor.fetchall()
        
        if not orders:
            flash('Order not found', 'danger')
            return redirect(url_for('index'))
        
        # Calculate total amount
        total_amount = Decimal('0.00')
        for order in orders:
            total_amount += order['price']
        
        # Calculate unit prices for each order item
        for order in orders:
            order['unit_price'] = order['price'] / Decimal(str(order['quantity']))
        
        # Get user info
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        # Get cart count
        cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
        cart_count = cursor.fetchone()['count']
        
        cursor.close()
        connection.close()
        
        return render_template('order-confirmation.html', 
                              orders=orders,
                              total_amount=total_amount,
                              user=user,
                              order_ids=order_ids,
                              invoice_order_ids=','.join(str(o['id']) for o in orders),
                              cart_count=cart_count)
    return "Database connection error", 500


# Invoice route
@app.route('/invoice/<order_ids>')
@login_required
def invoice(order_ids):
    connection = get_db_connection()
    if not connection:
        return "Database connection error", 500

    cursor = connection.cursor(dictionary=True)
    user_id = session['user_id']

    # Accept the new shared order reference and legacy numeric IDs.
    if order_ids.startswith('MH-'):
        cursor.execute("SELECT * FROM dborders WHERE order_group_id = %s ORDER BY id ASC", (order_ids,))
    else:
        try:
            order_id_list = [int(oid) for oid in order_ids.split(',')]
        except ValueError:
            flash('Invalid order ID', 'danger')
            return redirect(url_for('dashboard'))
        placeholders = ', '.join(['%s'] * len(order_id_list))
        cursor.execute(f"SELECT * FROM dborders WHERE id IN ({placeholders}) ORDER BY id ASC", order_id_list)
    orders = cursor.fetchall()

    if not orders:
        flash('Order not found', 'danger')
        return redirect(url_for('dashboard'))

    # Fetch user info
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    # Permission check: non-admin users can only see their own orders
    if user.get('role') != 'admin':
        if not any(order['email'] == user['email'] for order in orders):
            flash('You do not have permission to view this invoice', 'danger')
            return redirect(url_for('dashboard'))

    # Calculate delivery fee (example: Dhaka = 70, outside = 120)
    delivery_fee = Decimal('0.00')
    for order in orders:
        if 'dhaka' in order['address'].lower():
            delivery_fee += Decimal('70.00')
        else:
            delivery_fee += Decimal('120.00')

    # Calculate subtotal (sum of unit_price * quantity)
    subtotal = sum(order['price'] for order in orders)

    # Example discount handling (assume stored in order table or 0)
    discount = sum(order.get('discount', 0) for order in orders)  # default 0 if not present

    # Tax
    tax_amount = subtotal * Decimal('0.05')

    # Total amount
    total_amount = subtotal + tax_amount + delivery_fee - discount

    # Compute unit price per order for template
    for order in orders:
        order['unit_price'] = order['price'] / Decimal(str(order['quantity']))

    # Estimated delivery
    order_date = orders[0]['created_at']
    estimated_delivery = order_date + timedelta(days=3)

    # Company info
    company_info = {
        'name': 'MediHome',
        'address': '123 Healthcare Avenue, Dhaka 1205, Bangladesh',
        'phone': '+880 1234 567890',
        'email': 'info@medihome.com',
        'license': 'DGDA PHARM-2024-0123'
    }

    cursor.close()
    connection.close()

    return render_template(
        'invoice.html',
        orders=orders,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        discount=discount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        user=user,
        company_info=company_info,
        order_ids=order_ids,
        estimated_delivery=estimated_delivery
    )

# Register the filter
@app.template_filter('number_to_words')
def number_to_words_filter(number):
    try:
        # Convert to float first to handle Decimal
        num = float(number)
        # For simplicity, just return the number as string
        return f"{num:.2f} Taka Only"
    except:
        return str(number)




# ==================== USER DASHBOARD AND PROFILE MANAGEMENT ====================
# Change Password Route
@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('currentPassword')
    new_password = request.form.get('newPassword')
    confirm_password = request.form.get('confirmPassword')
    
    # Validate passwords
    if new_password != confirm_password:
        flash('New passwords do not match', 'danger')
        return redirect(url_for('dashboard'))
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get current user
        cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        
        # Verify current password
        if user and user['password'] == current_password:  # In production, use password hashing
            # Update password
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_password, session['user_id']))
            connection.commit()
            flash('Password changed successfully!', 'success')
        else:
            flash('Current password is incorrect', 'danger')
        
        cursor.close()
        connection.close()
    
    return redirect(url_for('dashboard'))

# Submit Review Route
@app.route('/submit_review', methods=['GET', 'POST'])
@login_required
def submit_review():
    if request.method == 'POST':
        medicine_id = request.form.get('medicine_id')
        rating = request.form.get('rating')
        review_text = request.form.get('reviewText')

        if not medicine_id or not rating or not review_text:
            flash('All fields are required', 'danger')
            return redirect(url_for('submit_review'))

        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("""
                INSERT INTO reviews (user_id, medicine_id, ratings, quote)
                VALUES (%s, %s, %s, %s)
            """, (
                session['user_id'],
                medicine_id,
                rating,
                review_text
            ))
            connection.commit()
            flash('Review submitted successfully!', 'success')
        except Exception:
            connection.rollback()
            flash('Error submitting review', 'danger')
        finally:
            cursor.close()
            connection.close()

        return redirect(url_for('dashboard'))

    # GET: load medicines user ordered
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT DISTINCT m.id, m.name
        FROM medicines m
        JOIN dborders o ON o.product = m.name
        WHERE o.email = %s
    """, (session['email'],))

    user_medicines = cursor.fetchall()
    cursor.close()
    connection.close()

    return render_template('review.html', user_medicines=user_medicines)

# Reorder Order Route
@app.route('/reorder_order/<int:order_id>', methods=['GET', 'POST'])
@login_required
def reorder_order(order_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get order details
        cursor.execute("SELECT * FROM all_orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()
        
        if order:
            # Get medicine by name
            cursor.execute("SELECT * FROM medicines WHERE name = %s", (order['product'],))
            medicine = cursor.fetchone()
            
            if medicine:
                cursor.close()
                connection.close()
                
                # Redirect to checkout with medicine details
                return redirect(url_for('checkout', medicine_id=medicine['id'], quantity=order['quantity']))
            else:
                flash('Medicine not found', 'danger')
        else:
            flash('Order not found', 'danger')
        
        cursor.close()
        connection.close()
    
    return redirect(url_for('dashboard'))

# Dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # Get user info
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        # Get user's orders from dborders table
        cursor.execute("""
            SELECT * FROM dborders 
            WHERE email = %s 
            ORDER BY created_at DESC
            LIMIT 5
        """, (user['email'],))
        recent_orders = cursor.fetchall()
        
        # Get all user's orders
        cursor.execute("""
            SELECT * FROM dborders 
            WHERE email = %s 
            ORDER BY created_at DESC
        """, (user['email'],))
        all_orders = cursor.fetchall()
        
        # Get user's prescriptions
        cursor.execute("""
            SELECT * FROM prescriptions 
            WHERE user_id = %s 
            ORDER BY created_at DESC
        """, (user_id,))
        prescriptions = cursor.fetchall()
        
        # Calculate statistics
        cursor.execute("""
            SELECT COUNT(*) as total_orders, SUM(price) as total_spent 
            FROM dborders 
            WHERE email = %s
        """, (user['email'],))
        order_stats = cursor.fetchone()
        
        total_orders = order_stats['total_orders'] or 0
        total_spent = order_stats['total_spent'] or Decimal('0.00')
        
        # Get wishlist count (placeholder for now)
        wishlist_count = 8  # This would come from a wishlist table
        
        # Get medicines the user has ordered (for review modal)
        cursor.execute("""
            SELECT DISTINCT m.* 
            FROM medicines m
            JOIN dborders o ON m.name = o.product
            WHERE o.email = %s
        """, (user['email'],))
        user_medicines = cursor.fetchall()
        
        # Get cart count
        cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
        cart_count_result = cursor.fetchone()
        cart_count = cart_count_result['count'] if cart_count_result else 0
        
        # Get active tab from session and clear it
        active_tab = session.pop('active_tab', None)
        
        # Check if review modal should be shown
        show_review_modal = active_tab == 'review'
        
        # Add estimated delivery dates to orders
        for order in recent_orders:
            order['estimated_delivery'] = (order['created_at'] + timedelta(days=3)).strftime('%d %b %Y')
        
        for order in all_orders:
            order['estimated_delivery'] = (order['created_at'] + timedelta(days=3)).strftime('%d %b %Y')
        
        cursor.close()
        connection.close()
        
        return render_template('dashboard.html', 
                              user=user,
                              recent_orders=recent_orders,
                              all_orders=all_orders,
                              prescriptions=prescriptions,
                              total_orders=total_orders,
                              total_spent=total_spent,
                              wishlist_count=wishlist_count,
                              user_medicines=user_medicines,
                              cart_count=cart_count,
                              active_tab=active_tab,
                              show_review_modal=show_review_modal)
    return "Database connection error", 500

# Update profile route
@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # Get form data
        name = request.form.get('profileName')
        email = request.form.get('profileEmail')
        phone = request.form.get('profilePhone')
        address = request.form.get('profileAddress')
        
        # Handle profile image upload
        profile_image = None
        if 'profileImage' in request.files:
            file = request.files['profileImage']
            if file.filename != '':
                # Check if the file is allowed
                if file and allowed_file(file.filename):
                    # Create a secure filename
                    filename = secure_filename(file.filename)
                    # Save the file and get the path
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    profile_image = file_path
                else:
                    flash('Invalid file type. Only images are allowed.', 'danger')
                    return redirect(url_for('dashboard'))
        
        # Update user profile
        update_query = "UPDATE users SET name = %s, email = %s, phone = %s, address = %s"
        update_params = [name, email, phone, address]
        
        if profile_image:
            update_query += ", image = %s"
            update_params.append(profile_image)
        
        update_query += " WHERE id = %s"
        update_params.append(user_id)
        
        cursor.execute(update_query, update_params)
        connection.commit()
        
        # Update session data
        session['user_name'] = name
        
        cursor.close()
        connection.close()
        
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    flash('Database connection error', 'danger')
    return redirect(url_for('dashboard'))


@app.route('/set_active_tab', methods=['POST'])
@login_required
def set_active_tab():
    tab = request.form.get('tab')
    session['active_tab'] = tab
    return redirect(url_for('dashboard'))

@app.route('/reorder_most_recent', methods=['POST'])
@login_required
def reorder_most_recent():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM dborders 
            WHERE email = %s 
            ORDER BY created_at DESC 
            LIMIT 1
        """, (session['email'],))
        order = cursor.fetchone()
        
        if order:
            # Get the medicine by name
            cursor.execute("SELECT * FROM medicines WHERE name = %s", (order['product'],))
            medicine = cursor.fetchone()
            
            if medicine:
                cursor.close()
                connection.close()
                return redirect(url_for('checkout', medicine_id=medicine['id'], quantity=order['quantity']))
            else:
                flash('Medicine not found', 'danger')
        else:
            flash('No recent orders found', 'danger')
        
        cursor.close()
        connection.close()
    
    return redirect(url_for('dashboard'))




# ==================== PRESCRIPTION MANAGEMENT ====================
# Upload prescription page route
@app.route('/upload_prescription_page')
@login_required
def upload_prescription_page():
    # Get cart count for the header
    cart_count = 0
    user_id = session.get('user_id')
    user = None
    
    if user_id:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            # Get user info
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            # Get cart count
            cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
            cart_count = cursor.fetchone()['count']
            
            cursor.close()
            connection.close()
    
    return render_template('upload-prescription.html', cart_count=cart_count, user=user)

# Handle prescription upload route
@app.route('/handle_prescription_upload', methods=['POST'])
@login_required
def handle_prescription_upload():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # Get form data
        patient_name = request.form.get('patientName')
        patient_age = request.form.get('patientAge')
        patient_phone = request.form.get('patientPhone')
        patient_email = request.form.get('patientEmail')
        patient_address = request.form.get('patientAddress')
        special_instructions = request.form.get('specialInstructions', '')
        
        # Handle file upload
        if 'prescriptionFile' in request.files:
            file = request.files['prescriptionFile']
            if file.filename != '':
                # Check if the file is allowed
                if file and allowed_file(file.filename):
                    # Create a secure filename
                    filename = secure_filename(file.filename)
                    # Add timestamp to make filename unique
                    filename = f"{int(time())}_{filename}"
                    # Save the file and get the path
                    file_path = os.path.join(app.config['PRESCRIPTION_FOLDER'], filename)
                    file.save(file_path)
                    # Convert to relative path for database
                    relative_path = f"/static/prescriptions/{filename}"
                    
                    # Insert prescription into database
                    cursor.execute("""
                        INSERT INTO prescriptions (
                            user_id, patient_name, patient_age, patient_phone, 
                            patient_email, patient_address, image_path, special_instructions
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        user_id, patient_name, patient_age, patient_phone,
                        patient_email, patient_address, relative_path, special_instructions
                    ))
                    connection.commit()
                    
                    flash('Prescription uploaded successfully! Our team will contact you soon.', 'success')
                else:
                    flash('Invalid file type. Only images and PDFs are allowed.', 'danger')
            else:
                flash('Please select a file to upload', 'danger')
        else:
            flash('No file selected', 'danger')
        
        cursor.close()
        connection.close()
        
        return redirect(url_for('upload_prescription_page'))
    
    flash('Database connection error', 'danger')
    return redirect(url_for('upload_prescription_page'))

# Upload prescription route (from dashboard)
@app.route('/upload_prescription', methods=['POST'])
@login_required
def upload_prescription():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # Get form data
        patient_name = request.form.get('patientName')
        patient_age = request.form.get('patientAge')
        patient_phone = request.form.get('patientPhone')
        patient_email = request.form.get('patientEmail')
        patient_address = request.form.get('patientAddress')
        special_instructions = request.form.get('specialInstructions', '')
        
        # Handle file upload
        if 'prescriptionFile' in request.files:
            file = request.files['prescriptionFile']
            if file.filename != '':
                # Check if the file is allowed
                if file and allowed_file(file.filename):
                    # Create a secure filename
                    filename = secure_filename(file.filename)
                    # Save the file and get the path
                    file_path = os.path.join(app.config['PRESCRIPTION_FOLDER'], filename)
                    file.save(file_path)
                    
                    # Insert prescription into database
                    cursor.execute("""
                        INSERT INTO prescriptions (
                            user_id, patient_name, patient_age, patient_phone, 
                            patient_email, patient_address, image_path, special_instructions
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        user_id, patient_name, patient_age, patient_phone,
                        patient_email, patient_address, file_path, special_instructions
                    ))
                    connection.commit()
                    
                    flash('Prescription uploaded successfully!', 'success')
                else:
                    flash('Invalid file type. Only images and PDFs are allowed.', 'danger')
            else:
                flash('Please select a file to upload', 'danger')
        else:
            flash('No file selected', 'danger')
        
        cursor.close()
        connection.close()
        
        return redirect(url_for('dashboard'))
    
    flash('Database connection error', 'danger')
    return redirect(url_for('dashboard'))



# Create order from prescription route
@app.route('/create_order_from_prescription', methods=['POST'])
@login_required
def create_order_from_prescription():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        user_id = session['user_id']
        
        # Get form data
        prescription_id = request.form.get('prescriptionId')
        patient_name = request.form.get('patientName')
        patient_phone = request.form.get('patientPhone')
        patient_email = request.form.get('patientEmail')
        patient_address = request.form.get('patientAddress')
        special_instructions = request.form.get('specialInstructions', '')
        
        # Get user info
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        # Create order in all three tables
        order_price = Decimal('0.00')  # Price will be determined later by admin
        
        # Insert into all_orders
        cursor.execute("""
            INSERT INTO all_orders (
                ordered_by, phone, email, address, product, 
                quantity, price, payment_method, special_instruction, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            patient_name, patient_phone, patient_email, patient_address,
            f"Prescription Order #{prescription_id}", 1, order_price,
            "Cash on Delivery", special_instructions, "Pending"
        ))
        all_order_id = cursor.lastrowid
        
        # Insert into orders
        cursor.execute("""
            INSERT INTO orders (
                ordered_by, phone, email, address, product, 
                quantity, price, payment_method, special_instruction, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            patient_name, patient_phone, patient_email, patient_address,
            f"Prescription Order #{prescription_id}", 1, order_price,
            "Cash on Delivery", special_instructions, "Pending"
        ))
        
        # Insert into dborders
        cursor.execute("""
            INSERT INTO dborders (
                ordered_by, phone, email, address, product, 
                quantity, price, payment_method, special_instruction, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            patient_name, patient_phone, patient_email, patient_address,
            f"Prescription Order #{prescription_id}", 1, order_price,
            "Cash on Delivery", special_instructions, "Pending"
        ))
        
        # Update prescription status
        cursor.execute("""
            UPDATE prescriptions 
            SET status = 'Order Created' 
            WHERE id = %s
        """, (prescription_id,))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        flash('Order created from prescription successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    flash('Database connection error', 'danger')
    return redirect(url_for('dashboard'))


# ==================== STATIC PAGES ====================
# About page
@app.route('/about')
def about():
    # Get cart count for the header
    cart_count = 0
    user = None
    user_id = session.get('user_id')
    
    if user_id:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if user:
                cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
                cart_count = cursor.fetchone()['count']
            
            cursor.close()
            connection.close()
    
    return render_template('about.html', cart_count=cart_count, user=user)


# Contact page
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    cart_count = 0
    user_id = session.get('user_id')
    user = None

    if user_id:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) AS count FROM cart WHERE user_id = %s", (user_id,))
            cart_count = cursor.fetchone()['count']
            cursor.close()
            connection.close()

    # Old contact form submit stays untouched
    if request.method == 'POST' and 'subject' in request.form:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        subject = request.form.get('subject')
        message = request.form.get('message')
        newsletter = request.form.get('newsletter') == 'on'

        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            cursor.execute("""
                INSERT INTO contact_messages 
                (name, email, phone, subject, message, newsletter, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (name, email, phone, subject, message, newsletter))
            connection.commit()
            cursor.close()
            connection.close()

        flash('Your message has been sent successfully!', 'success')
        return redirect(url_for('contact'))

    return render_template('contact.html',
    cart_count=cart_count,
    user=user,
    uid=session.get('user_id'),
    uname=session.get('user_name')
)



# Services page
@app.route('/services')
def services():
    # Get cart count for the header
    cart_count = 0
    user_id = session.get('user_id')
    user = None
    
    if user_id:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            # Get user info
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            # Get cart count
            cursor.execute("SELECT COUNT(*) as count FROM cart WHERE user_id = %s", (user_id,))
            cart_count = cursor.fetchone()['count']
            
            cursor.close()
            connection.close()
    
    return render_template('services.html', cart_count=cart_count, user=user)


# Newsletter subscription
@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    
    if not email:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Please provide an email address'})
        else:
            flash('Please provide an email address', 'danger')
            return redirect(request.referrer or url_for('index'))
    
    # Email validation
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Please provide a valid email address'})
        else:
            flash('Please provide a valid email address', 'danger')
            return redirect(request.referrer or url_for('index'))
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor()
        
        # Check if email already exists
        cursor.execute("SELECT * FROM newsletter_subscribers WHERE email = %s", (email,))
        existing_subscriber = cursor.fetchone()
        
        if existing_subscriber:
            cursor.close()
            connection.close()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'This email is already subscribed'})
            else:
                flash('This email is already subscribed to our newsletter', 'info')
                return redirect(request.referrer or url_for('index'))
        
        # Add new subscriber
        cursor.execute("""
            INSERT INTO newsletter_subscribers (email, subscribed_at) 
            VALUES (%s, NOW())
        """, (email,))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Thank you for subscribing to our newsletter!'})
        else:
            flash('Thank you for subscribing to our newsletter!', 'success')
            return redirect(request.referrer or url_for('index'))
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Database connection error'})
        else:
            flash('Database connection error', 'danger')
            return redirect(request.referrer or url_for('index'))


# ==================== PLACEHOLDER ROUTES FOR UPCOMING FEATURES ====================
@app.route('/medicine_delivery')
def medicine_delivery():
    flash('Medicine Delivery service is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/health_consultation')
def health_consultation():
    flash('Health Consultation service is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/prescription_upload')
def prescription_upload():
    flash('Prescription Upload service is Avaialable on your Dashboard ', 'info')
    return redirect(url_for('dashboard'))


@app.route('/lab_tests')
def lab_tests():
    flash('Lab Tests service is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/healthcare_products')
def healthcare_products():
    flash('Healthcare Products service is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/terms')
def terms():
    flash('Terms & Conditions page is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/privacy')
def privacy():
    flash('Privacy Policy page is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/faq')
def faq():
    flash('FAQ page is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/shipping_policy')
def shipping_policy():
    flash('Shipping Policy page is coming soon!', 'info')
    return redirect(url_for('services'))


@app.route('/returns')
def returns():
    flash('Returns & Refunds page is coming soon!', 'info')
    return redirect(url_for('services'))

@app.route('/track_order')
def track_order():
    flash('Please go to your Dashboard to Check Order Status', 'info')
    return redirect(url_for('dashboard'))


@app.route('/<page_name>')
def coming_soon(page_name):
    # List of valid page names to handle
    valid_pages = [
        'medicine_delivery', 'health_consultation', 'prescription_upload',
        'lab_tests', 'healthcare_products', 'terms', 'privacy',
        'faq', 'shipping_policy', 'returns', 'track_order'
    ]
    
    if page_name in valid_pages:
        return render_template('coming_soon.html', page_name=page_name)
    else:
        return "Page not found", 404




# ==================== ADMIN ROUTES ====================
# Admin Dashboard
@app.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get stats for dashboard
        # Total Sales
        cursor.execute("SELECT SUM(price) as total FROM all_orders")
        sales_data = cursor.fetchone()
        total_sales = sales_data['total'] if sales_data and sales_data['total'] else 0
        
        # Total Users
        cursor.execute("SELECT COUNT(*) as total FROM users")
        users_data = cursor.fetchone()
        total_users = users_data['total']
        
        # Total Orders
        cursor.execute("SELECT COUNT(*) as total FROM all_orders")
        orders_data = cursor.fetchone()
        total_orders = orders_data['total']
        
        # Total Medicines
        cursor.execute("SELECT COUNT(*) as total FROM medicines")
        medicines_data = cursor.fetchone()
        total_medicines = medicines_data['total']
        
        # Recent Activity
        cursor.execute("""
            SELECT 'user' as type, name, created_at as time 
            FROM users 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        recent_users = cursor.fetchall()
        
        cursor.execute("""
            SELECT 'order' as type, ordered_by as name, created_at as time 
            FROM all_orders 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        recent_orders = cursor.fetchall()
        
        # Combine and sort recent activity
        recent_activity = recent_users + recent_orders
        recent_activity.sort(key=lambda x: x['time'], reverse=True)
        recent_activity = recent_activity[:5]
        
        # New Orders
        cursor.execute("""
            SELECT * FROM all_orders 
            WHERE status = 'Pending' OR status = 'New'
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        new_orders = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return render_template('admin-dashboard.html', 
                              total_sales=total_sales,
                              total_users=total_users,
                              total_orders=total_orders,
                              total_medicines=total_medicines,
                              recent_activity=recent_activity,
                              new_orders=new_orders,
                              active_section='dashboard',
                              current_page=1,
                              total_pages=1,
                              settings=get_settings())
    return "Database connection error", 500


# Manage Users
@app.route('/admin/users')
@login_required
@admin_required
def manage_users():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get total users count for pagination
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()['total']
        total_pages = (total_users + per_page - 1) // per_page
        
        # Get users with pagination
        cursor.execute("SELECT * FROM users LIMIT %s OFFSET %s", (per_page, offset))
        users = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return render_template('admin-dashboard.html', 
                              users=users,
                              current_page=page,
                              total_pages=total_pages,
                              active_section='users',
                              # Add these to prevent errors in other sections
                              total_sales=0,
                              total_orders=0,
                              total_medicines=0,
                              settings=get_settings())
    return "Database connection error", 500



# Add User
@app.route('/admin/users/add', methods=['POST'])
@login_required
@admin_required
def add_user():
    if request.method == 'POST':
        name = request.form.get('userName')
        email = request.form.get('userEmail')
        phone = request.form.get('userPhone')
        password = request.form.get('userPassword')
        address = request.form.get('userAddress')
        role = request.form.get('userRole', 'customer')
        
        # Handle image upload
        image_file = request.files.get('userImage')
        image_path = None
        if image_file and image_file.filename != '':
            # Save the image file
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)
            # Convert to relative path for database
            image_path = f"/static/uploads/{filename}"
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO users (name, email, phone, password, address, role, image)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (name, email, phone, password, address, role, image_path))
                
                connection.commit()
                flash('User added successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error adding user: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('manage_users'))



# Edit User
@app.route('/admin/users/edit/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def edit_user(user_id):
    if request.method == 'POST':
        name = request.form.get('userName')
        email = request.form.get('userEmail')
        phone = request.form.get('userPhone')
        address = request.form.get('userAddress')
        role = request.form.get('userRole', 'customer')
        
        # Handle image upload
        image_file = request.files.get('userImage')
        image_path = None
        if image_file and image_file.filename != '':
            # Save the image file
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)
            # Convert to relative path for database
            image_path = f"/static/uploads/{filename}"
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            try:
                if image_path:
                    cursor.execute("""
                        UPDATE users 
                        SET name = %s, email = %s, phone = %s, address = %s, role = %s, image = %s
                        WHERE id = %s
                    """, (name, email, phone, address, role, image_path, user_id))
                else:
                    cursor.execute("""
                        UPDATE users 
                        SET name = %s, email = %s, phone = %s, address = %s, role = %s
                        WHERE id = %s
                    """, (name, email, phone, address, role, user_id))
                
                connection.commit()
                flash('User updated successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error updating user: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('manage_users'))


# Delete User
@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor()
        
        try:
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            connection.commit()
            flash('User deleted successfully!', 'success')
        except Exception as e:
            connection.rollback()
            flash(f'Error deleting user: {str(e)}', 'danger')
        finally:
            cursor.close()
            connection.close()
    
    return redirect(url_for('manage_users'))


# View User
@app.route('/admin/users/view/<int:user_id>')
@login_required
@admin_required
def view_user(user_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if user:
            return render_template('admin-dashboard.html', 
                              user=user,
                              active_section='users',
                              current_page=1,
                              total_pages=1,
                              settings=get_settings())
        else:
            flash('User not found', 'danger')
            return redirect(url_for('manage_users'))
    
    return "Database connection error", 500



# Get User Data for Edit Form (AJAX)
@app.route('/admin/users/get/<int:user_id>')
@login_required
@admin_required
def get_user(user_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if user:
            return jsonify(user)
        else:
            return jsonify({"error": "User not found"}), 404
    return jsonify({"error": "Database connection error"}), 500



# Manage Medicines
@app.route('/admin/medicines')
@login_required
@admin_required
def manage_medicines():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get total medicines count for pagination
        cursor.execute("SELECT COUNT(*) as total FROM medicines")
        total_medicines = cursor.fetchone()['total']
        total_pages = (total_medicines + per_page - 1) // per_page
        
        # Get medicines with pagination
        cursor.execute("SELECT * FROM medicines LIMIT %s OFFSET %s", (per_page, offset))
        medicines = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return render_template('admin-dashboard.html', 
                              medicines=medicines,
                              current_page=page,
                              total_pages=total_pages,
                              active_section='medicines',
                              # Add these to prevent errors in other sections
                              total_sales=0,
                              total_orders=0,
                              total_users=0,
                              settings=get_settings())
    return "Database connection error", 500



# Add Medicine
@app.route('/admin/medicines/add', methods=['POST'])
@login_required
@admin_required
def add_medicine():
    if request.method == 'POST':
        name = request.form.get('medicineName')
        price = request.form.get('medicinePrice')
        stock = request.form.get('medicineStock')
        rating = request.form.get('medicineRating')
        details = request.form.get('medicineDetails')
        category = request.form.get('medicineCategory', 'General')
        company = request.form.get('medicineCompany') or None
        
        # Handle image upload
        image_file = request.files.get('medicineImage')
        image_path = None
        if image_file and image_file.filename != '':
            # Save the image file
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)
            # Convert to relative path for database
            image_path = f"/static/uploads/{filename}"
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO medicines (name, price, stock_quantity, ratings, details, category, image, company)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (name, price, stock, rating, details, category, image_path, company))
                
                connection.commit()
                flash('Medicine added successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error adding medicine: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('manage_medicines'))

# Edit Medicine
@app.route('/admin/medicines/edit/<int:medicine_id>', methods=['POST'])
@login_required
@admin_required
def edit_medicine(medicine_id):
    if request.method == 'POST':
        name = request.form.get('medicineName')
        price = request.form.get('medicinePrice')
        stock = request.form.get('medicineStock')
        rating = request.form.get('medicineRating')
        details = request.form.get('medicineDetails')
        category = request.form.get('medicineCategory', 'General')
        company = request.form.get('medicineCompany') or None
        
        # Handle image upload
        image_file = request.files.get('medicineImage')
        image_path = None
        if image_file and image_file.filename != '':
            # Save the image file
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)
            # Convert to relative path for database
            image_path = f"/static/uploads/{filename}"
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            try:
                if image_path:
                    cursor.execute("""
                        UPDATE medicines 
                        SET name = %s, price = %s, stock_quantity = %s, ratings = %s, details = %s, category = %s, image = %s, company = %s
                        WHERE id = %s
                    """, (name, price, stock, rating, details, category, image_path, company, medicine_id))
                else:
                    cursor.execute("""
                        UPDATE medicines 
                        SET name = %s, price = %s, stock_quantity = %s, ratings = %s, details = %s, category = %s, company = %s
                        WHERE id = %s
                    """, (name, price, stock, rating, details, category, company, medicine_id))
                
                connection.commit()
                flash('Medicine updated successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error updating medicine: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('manage_medicines'))

# Delete Medicine
@app.route('/admin/medicines/delete/<int:medicine_id>', methods=['POST'])
@login_required
@admin_required
def delete_medicine(medicine_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor()
        
        try:
            cursor.execute("DELETE FROM medicines WHERE id = %s", (medicine_id,))
            connection.commit()
            flash('Medicine deleted successfully!', 'success')
        except Exception as e:
            connection.rollback()
            flash(f'Error deleting medicine: {str(e)}', 'danger')
        finally:
            cursor.close()
            connection.close()
    
    return redirect(url_for('manage_medicines'))

# View Medicine
@app.route('/admin/medicines/view/<int:medicine_id>')
@login_required
@admin_required
def view_medicine(medicine_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM medicines WHERE id = %s", (medicine_id,))
        medicine = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if medicine:
            return render_template('admin-dashboard.html', 
                              medicine=medicine,
                              active_section='medicines',
                              current_page=1,
                              total_pages=1,
                              settings=get_settings())
        else:
            flash('Medicine not found', 'danger')
            return redirect(url_for('manage_medicines'))
    
    return "Database connection error", 500

# Get Medicine Data for Edit Form (AJAX)
@app.route('/admin/medicines/get/<int:medicine_id>')
@login_required
@admin_required
def get_medicine(medicine_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM medicines WHERE id = %s", (medicine_id,))
        medicine = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if medicine:
            return jsonify(medicine)
        else:
            return jsonify({"error": "Medicine not found"}), 404
    return jsonify({"error": "Database connection error"}), 500

# Manage Orders
@app.route('/admin/orders')
@login_required
@admin_required
def manage_orders():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get total orders count for pagination
        cursor.execute("SELECT COUNT(*) as total FROM all_orders")
        total_orders = cursor.fetchone()['total']
        total_pages = (total_orders + per_page - 1) // per_page
        
        # Get orders with pagination
        cursor.execute("SELECT * FROM all_orders ORDER BY created_at DESC LIMIT %s OFFSET %s", (per_page, offset))
        orders = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return render_template('admin-dashboard.html', 
                              orders=orders,
                              current_page=page,
                              total_pages=total_pages,
                              active_section='orders',
                              # Add these to prevent errors in other sections
                              total_sales=0,
                              total_users=0,
                              total_medicines=0,
                              settings=get_settings())
    return "Database connection error", 500

# Add Order
@app.route('/admin/orders/add', methods=['POST'])
@login_required
@admin_required
def add_order():
    if request.method == 'POST':
        customer = request.form.get('orderCustomer')
        email = request.form.get('orderEmail')
        phone = request.form.get('orderPhone')
        product = request.form.get('orderProduct')
        quantity = request.form.get('orderQuantity')
        price = request.form.get('orderPrice')
        payment = request.form.get('orderPayment')
        status = request.form.get('orderStatus')
        address = request.form.get('orderAddress')
        instructions = request.form.get('orderInstructions')
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            try:
                # Insert into all_orders table
                cursor.execute("""
                    INSERT INTO all_orders (ordered_by, phone, email, address, product, quantity, price, payment_method, special_instruction, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (customer, phone, email, address, product, quantity, price, payment, instructions, status))
                
                # Get the last inserted ID
                order_id = cursor.lastrowid
                
                # Insert into orders table
                cursor.execute("""
                    INSERT INTO orders (ordered_by, phone, email, address, product, quantity, price, payment_method, special_instruction, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (customer, phone, email, address, product, quantity, price, payment, instructions, status))
                
                # Insert into dborders table
                cursor.execute("""
                    INSERT INTO dborders (ordered_by, phone, email, address, product, quantity, price, payment_method, special_instruction, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (customer, phone, email, address, product, quantity, price, payment, instructions, status))
                
                connection.commit()
                flash('Order added successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error adding order: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('manage_orders'))

# Edit Order
@app.route('/admin/orders/edit/<int:order_id>', methods=['POST'])
@login_required
@admin_required
def edit_order(order_id):
    if request.method == 'POST':
        customer = request.form.get('orderCustomer')
        email = request.form.get('orderEmail')
        phone = request.form.get('orderPhone')
        product = request.form.get('orderProduct')
        quantity = int(request.form.get('orderQuantity'))
        price = request.form.get('orderPrice')
        payment = request.form.get('orderPayment')
        status = request.form.get('orderStatus')
        address = request.form.get('orderAddress')
        instructions = request.form.get('orderInstructions')
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            
            try:
                # Get the original order to compare quantities
                cursor.execute("SELECT * FROM all_orders WHERE id = %s", (order_id,))
                original_order = cursor.fetchone()
                
                if original_order:
                    original_quantity = original_order['quantity']
                    quantity_diff = quantity - original_quantity
                    
                    # If quantity increased, decrease stock
                    if quantity_diff > 0:
                        # Find the medicine by name
                        cursor.execute("SELECT * FROM medicines WHERE name = %s", (product,))
                        medicine = cursor.fetchone()
                        
                        if medicine:
                            new_stock = medicine['stock_quantity'] - quantity_diff
                            if new_stock >= 0:
                                cursor.execute("UPDATE medicines SET stock_quantity = %s WHERE id = %s", (new_stock, medicine['id']))
                            else:
                                flash('Not enough stock available!', 'danger')
                                connection.rollback()
                                cursor.close()
                                connection.close()
                                return redirect(url_for('manage_orders'))
                
                # Update all_orders table
                cursor.execute("""
                    UPDATE all_orders 
                    SET ordered_by = %s, phone = %s, email = %s, address = %s, product = %s, quantity = %s, price = %s, payment_method = %s, special_instruction = %s, status = %s
                    WHERE id = %s
                """, (customer, phone, email, address, product, quantity, price, payment, instructions, status, order_id))
                
                # Update orders table
                cursor.execute("""
                    UPDATE orders 
                    SET ordered_by = %s, phone = %s, email = %s, address = %s, product = %s, quantity = %s, price = %s, payment_method = %s, special_instruction = %s, status = %s
                    WHERE id = %s
                """, (customer, phone, email, address, product, quantity, price, payment, instructions, status, order_id))
                
                # Update dborders table
                cursor.execute("""
                    UPDATE dborders 
                    SET ordered_by = %s, phone = %s, email = %s, address = %s, product = %s, quantity = %s, price = %s, payment_method = %s, special_instruction = %s, status = %s
                    WHERE id = %s
                """, (customer, phone, email, address, product, quantity, price, payment, instructions, status, order_id))
                
                connection.commit()
                flash('Order updated successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error updating order: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('manage_orders'))

# Update Order Status
@app.route('/admin/orders/update_status/<int:order_id>', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    status = request.form.get('status')
    
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor()
        
        try:
            # Update all_orders table
            cursor.execute("UPDATE all_orders SET status = %s WHERE id = %s", (status, order_id))
            
            # Update orders table
            cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
            
            # Update dborders table
            cursor.execute("UPDATE dborders SET status = %s WHERE id = %s", (status, order_id))
            
            connection.commit()
            flash('Order status updated successfully!', 'success')
        except Exception as e:
            connection.rollback()
            flash(f'Error updating order status: {str(e)}', 'danger')
        finally:
            cursor.close()
            connection.close()
    
    return redirect(url_for('manage_orders'))

# Delete Order
@app.route('/admin/orders/delete/<int:order_id>', methods=['POST'])
@login_required
@admin_required
def delete_order(order_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor()
        
        try:
            # Delete from all_orders table
            cursor.execute("DELETE FROM all_orders WHERE id = %s", (order_id,))
            
            # Delete from orders table
            cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
            
            # Delete from dborders table
            cursor.execute("DELETE FROM dborders WHERE id = %s", (order_id,))
            
            connection.commit()
            flash('Order deleted successfully!', 'success')
        except Exception as e:
            connection.rollback()
            flash(f'Error deleting order: {str(e)}', 'danger')
        finally:
            cursor.close()
            connection.close()
    
    return redirect(url_for('manage_orders'))

# View Order
@app.route('/admin/orders/view/<int:order_id>')
@login_required
@admin_required
def view_order(order_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM all_orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if order:
            return render_template('admin-dashboard.html', 
                              order=order,
                              active_section='orders',
                              current_page=1,
                              total_pages=1,
                              settings=get_settings())
        else:
            flash('Order not found', 'danger')
            return redirect(url_for('manage_orders'))
    
    return "Database connection error", 500



# Get Order Data for Edit Form (AJAX)
@app.route('/admin/orders/get/<int:order_id>')
@login_required
@admin_required
def get_order(order_id):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM all_orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if order:
            return jsonify(order)
        else:
            return jsonify({"error": "Order not found"}), 404
    return jsonify({"error": "Database connection error"}), 500



# Settings
@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        site_name = request.form.get('siteName')
        site_email = request.form.get('siteEmail')
        site_phone = request.form.get('sitePhone')
        site_address = request.form.get('siteAddress')
        
        # Payment settings
        bkash_enabled = 'bkash' in request.form
        nagad_enabled = 'nagad' in request.form
        rocket_enabled = 'rocket' in request.form
        cod_enabled = 'cod' in request.form
        
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            try:
                # Update or insert site settings
                cursor.execute("""
                    INSERT INTO settings (setting_key, setting_value)
                    VALUES ('site_name', %s), ('site_email', %s), ('site_phone', %s), ('site_address', %s)
                    ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """, (site_name, site_email, site_phone, site_address))
                
                # Update payment settings
                cursor.execute("""
                    INSERT INTO settings (setting_key, setting_value)
                    VALUES ('bkash_enabled', %s), ('nagad_enabled', %s), ('rocket_enabled', %s), ('cod_enabled', %s)
                    ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """, (str(int(bkash_enabled)), str(int(nagad_enabled)), str(int(rocket_enabled)), str(int(cod_enabled))))
                
                connection.commit()
                flash('Settings updated successfully!', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Error updating settings: {str(e)}', 'danger')
            finally:
                cursor.close()
                connection.close()
        
        return redirect(url_for('settings'))
    else:
        settings = get_settings()
        
        return render_template('admin-dashboard.html', 
                              settings=settings,
                              active_section='settings',
                              current_page=1,
                              total_pages=1)


# Reports
@app.route('/admin/reports')
@login_required
@admin_required
def reports():
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        # Get sales data for the chart
        cursor.execute("""
            SELECT MONTH(created_at) as month, SUM(price) as total
            FROM all_orders
            WHERE YEAR(created_at) = YEAR(CURRENT_DATE)
            GROUP BY MONTH(created_at)
            ORDER BY month
        """)
        sales_data = cursor.fetchall()
        
        # Get top selling medicines
        cursor.execute("""
            SELECT product, SUM(quantity) as total_sold
            FROM all_orders
            GROUP BY product
            ORDER BY total_sold DESC
            LIMIT 5
        """)
        top_medicines = cursor.fetchall()
        
        # Get user growth data
        cursor.execute("""
            SELECT MONTH(created_at) as month, COUNT(*) as total
            FROM users
            WHERE YEAR(created_at) = YEAR(CURRENT_DATE)
            GROUP BY MONTH(created_at)
            ORDER BY month
        """)
        user_growth = cursor.fetchall()
        
        # Create a complete array for all 12 months for user growth
        user_growth_array = [0] * 12
        for item in user_growth:
            if 1 <= item['month'] <= 12:
                user_growth_array[item['month'] - 1] = item['total']
        
        # Prepare medicine data for the chart
        medicine_names = []
        medicine_sales = []
        
        if top_medicines:
            for item in top_medicines:
                medicine_names.append(item['product'])
                medicine_sales.append(item['total_sold'])
        else:
            # Default data if no data is available
            medicine_names = ['Paracetamol 500mg', 'Vitamin C 1000mg', 'Cough Syrup', 'Ibuprofen 400mg', 'Antihistamine']
            medicine_sales = [245, 187, 132, 98, 76]
        
        cursor.close()
        connection.close()
        
        return render_template('admin-dashboard.html', 
                              sales_data=sales_data,
                              top_medicines=top_medicines,
                              user_growth=user_growth,
                              user_growth_array=user_growth_array,
                              medicine_names=medicine_names,
                              medicine_sales=medicine_sales,
                              active_section='reports',
                              current_page=1,
                              total_pages=1,
                              settings=get_settings())
    return "Database connection error", 500


# Export Report Route
@app.route('/admin/export/<report_type>')
@login_required
@admin_required
def export_report(report_type):
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        
        if report_type == 'sales':
            # Get sales data
            cursor.execute("""
                SELECT id, ordered_by, phone, email, product, quantity, price, payment_method, status, created_at
                FROM all_orders
                ORDER BY created_at DESC
            """)
            data = cursor.fetchall()
            
            # Create CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Order ID', 'Customer', 'Phone', 'Email', 'Product', 'Quantity', 'Price', 'Payment Method', 'Status', 'Date'])
            
            # Write data
            for row in data:
                writer.writerow([
                    row['id'],
                    row['ordered_by'],
                    row['phone'],
                    row['email'],
                    row['product'],
                    row['quantity'],
                    row['price'],
                    row['payment_method'],
                    row['status'],
                    row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                ])
            
            filename = f"sales_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        elif report_type == 'users':
            # Get users data
            cursor.execute("""
                SELECT id, name, email, phone, address, role, created_at
                FROM users
                ORDER BY created_at DESC
            """)
            data = cursor.fetchall()
            
            # Create CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['User ID', 'Name', 'Email', 'Phone', 'Address', 'Role', 'Registration Date'])
            
            # Write data
            for row in data:
                writer.writerow([
                    row['id'],
                    row['name'],
                    row['email'],
                    row['phone'],
                    row['address'],
                    row['role'],
                    row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                ])
            
            filename = f"users_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        elif report_type == 'medicines':
            # Get medicines data
            cursor.execute("""
                SELECT id, name, price, stock_quantity, sold_quantity, ratings, category, details
                FROM medicines
                ORDER BY name ASC
            """)
            data = cursor.fetchall()
            
            # Create CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Medicine ID', 'Name', 'Price', 'Stock Quantity', 'Sold Quantity', 'Rating', 'Category', 'Details'])
            
            # Write data
            for row in data:
                writer.writerow([
                    row['id'],
                    row['name'],
                    row['price'],
                    row['stock_quantity'],
                    row['sold_quantity'],
                    row['ratings'],
                    row['category'],
                    row['details']
                ])
            
            filename = f"medicines_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        elif report_type == 'orders':
            # Get orders data
            cursor.execute("""
                SELECT id, ordered_by, phone, email, product, quantity, price, payment_method, status, created_at
                FROM all_orders
                ORDER BY created_at DESC
            """)
            data = cursor.fetchall()
            
            # Create CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Order ID', 'Customer', 'Phone', 'Email', 'Product', 'Quantity', 'Price', 'Payment Method', 'Status', 'Date'])
            
            # Write data
            for row in data:
                writer.writerow([
                    row['id'],
                    row['ordered_by'],
                    row['phone'],
                    row['email'],
                    row['product'],
                    row['quantity'],
                    row['price'],
                    row['payment_method'],
                    row['status'],
                    row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                ])
            
            filename = f"orders_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        else:
            flash('Invalid report type', 'danger')
            return redirect(url_for('reports'))
        
        cursor.close()
        connection.close()
        
        # Create response
        output.seek(0)
        
        # Create a temporary file
        temp_file = io.BytesIO()
        temp_file.write(output.getvalue().encode('utf-8'))
        temp_file.seek(0)
        
        return send_file(
            temp_file,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    
    return "Database connection error", 500


# Update Admin Profile
@app.route('/admin/update_profile', methods=['POST'])
@login_required
@admin_required
def update_admin_profile():
    # Handle image upload
    image_file = request.files.get('adminProfileImage')
    image_path = None
    if image_file and image_file.filename != '':
        # Create a unique filename
        filename = secure_filename(image_file.filename)
        # Add a timestamp to make it unique
        filename = f"{int(time())}_{filename}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(image_path)
        # Convert to relative path for database and session
        image_path = f"/static/uploads/{filename}"
        # Update session with new image path
        session['admin_image'] = image_path
    
    name = request.form.get('adminName')
    email = request.form.get('adminEmail')
    phone = request.form.get('adminPhone')
    bio = request.form.get('adminBio')
    
    # Update session
    session['user_name'] = name
    
    # In a real application, you would update the admin user in the database
    # For now, we'll just flash a message
    flash('Profile updated successfully!', 'success')
    
    return redirect(url_for('admin_dashboard'))

#chatting Feature
socketio = SocketIO(app)
#admin chat
@app.route("/admin/live-chat")
@admin_required
def admin_live_chat():
    previous_url = request.referrer or url_for('admin_dashboard')
    return render_template(
        "admin_chat.html",
        admin_name=session['user_name'],
        previous_url=previous_url
    )


# Customer & Admin SocketIO
@socketio.on('join')
def handle_join(data):
    if 'role' in session and session['role']=='admin':
        join_room("admin_room")
    elif 'user_id' in session:
        join_room(f"user_{data['user_id']}")

@socketio.on('send_message')
def handle_send_message(data):
    sender_id = data.get('sender_id')
    sender_name = data.get('sender_name')
    receiver = data.get('receiver')
    message = data.get('message')

    if not receiver or not message:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chat_messages (sender_id, sender_name, receiver, message, is_read)
        VALUES (%s,%s,%s,%s,%s)
    """, (sender_id, sender_name, receiver, message, 1 if sender_id==0 else 0))
    conn.commit()
    cur.close()
    conn.close()

    # Emit only to the **receiver**
    if sender_id == 0:
        # Admin → send to specific customer
        emit('receive_message', data, to=f"user_{receiver}")  # only that customer
    else:
        # Customer → send to admin room
        emit('receive_message', data, to="admin_room")


@app.route("/admin/chat/customers")
@admin_required
def admin_chat_customers():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT sender_id, sender_name,
               SUM(CASE WHEN receiver='admin' AND is_read=0 THEN 1 ELSE 0 END) AS unread_count
        FROM chat_messages
        WHERE sender_id != 0 AND receiver='admin'
        GROUP BY sender_id, sender_name
        ORDER BY MAX(timestamp) DESC
    """)
    customers = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(customers)

@app.route("/admin/chat/messages/<int:customer_id>")
@admin_required
def admin_chat_messages(customer_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT * FROM chat_messages
        WHERE (sender_id=%s AND receiver='admin')
           OR (sender_id=0 AND receiver=%s)
        ORDER BY timestamp ASC
    """, (customer_id, customer_id))
    messages = cur.fetchall()

    # mark customer messages as read
    cur.execute("""
        UPDATE chat_messages
        SET is_read=1
        WHERE sender_id=%s AND receiver='admin' AND is_read=0
    """, (customer_id,))
    conn.commit()

    cur.close()
    conn.close()
    return jsonify(messages)



# ==================== MAIN EXECUTION BLOCK ====================
if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)



