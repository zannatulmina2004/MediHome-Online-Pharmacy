# MediHome — Full Pharmacy Storefront

A Flask + MySQL online-pharmacy demo for Bangladesh with B2C and B2B/wholesale flows.

## Included
- Responsive medicine storefront and cart
- Medicine-name filter (e.g. Paracetamol, Omeprazole, Domperidone)
- Manufacturer/company filter
- Search and stock filters
- Local medicine images with automatic fallback for missing files
- Product details: company, ingredients, dosage form, pack size, safety/prescription notice
- Retail discounts, with stronger promotions on vitamins/supplements
- Unit vs strip/pack selection
- Prescription-required checkout protection for flagged medicines
- One shared customer-facing Order ID per checkout
- B2B profile with business information and wholesale pricing
- B2B minimum merchandise subtotal: ৳3,000
- Cart, checkout, delivery fee, tax, promo-code support
- Prescription upload
- Admin/customer dashboards
- Ratings/review UI removed from the customer storefront
- Meet the Creator section/credit removed

## First run on Windows
1. Extract this ZIP.
2. Open `MediHome-B2B-Wholesale`.
3. Double-click `SETUP_MEDIHOME.bat`.
4. Make sure MySQL/MariaDB is running and the database exists:
   ```sql
   CREATE DATABASE medihome2;
   ```
5. If your MySQL root account has a password, edit `.env` and set `DB_PASSWORD`.
6. Double-click `RUN_MEDIHOME.bat`.
7. Open `http://127.0.0.1:5000`.

The application automatically creates missing tables/columns and synchronizes the catalog when it starts. Existing customer/order data is preserved.

## Email
SMTP is optional. If SMTP credentials are blank or invalid, checkout will still complete and the app logs an email warning instead of crashing.

## Notes
- Prescription-required items are intentionally blocked until a prescription file has been uploaded.
- Product information is demo/catalog content and should not be treated as medical advice.
## Development & Project Structure

### Main Components

- `app.py` — Main Flask backend and application logic
- `templates/` — HTML pages and Jinja templates
- `static/css/` — Stylesheets for different pages
- `static/js/` — Client-side JavaScript functionality
- `static/images/` — Medicine and interface images
- `requirements.txt` — Python package dependencies
- `.env.example` — Example environment configuration

### Development Notes

The project uses Flask for the backend, MySQL/MariaDB for database management, HTML/CSS/JavaScript for the frontend, and environment variables for configuration.

Before running the application, make sure the required database service is running and the environment configuration is properly set.

## Project Workflow

### Customer Workflow

1. Customer registers or logs into the MediHome platform.
2. Customer browses and searches available medicines.
3. Customer views medicine details and adds products to the cart.
4. Prescription-required medicines require a prescription upload before checkout.
5. Customer provides delivery information and selects an available payment method.
6. The system creates an order and displays the order confirmation.

### B2B / Wholesale Workflow

1. Business customers provide their business information during registration.
2. Eligible B2B customers can access wholesale pricing.
3. B2B orders must satisfy the minimum merchandise subtotal requirement.
4. Customers review their cart and checkout information before placing an order.
5. The system stores the order information and provides a shared customer-facing Order ID.

### Administrative Workflow

Administrators can manage the application through the dashboard, review customer and order information, and handle administrative operations supported by the system.