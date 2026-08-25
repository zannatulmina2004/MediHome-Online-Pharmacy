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
