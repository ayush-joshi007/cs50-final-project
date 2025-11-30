# Personal Finance Tracker
#### Video Demo: <URL HERE>
#### Description:

This project is my CS50x Final Project: a fully functional Personal Finance Tracker Web Application built using Flask, SQLite, Python, Bootstrap 5, and Chart.js. The goal of the project is to provide users with a simple and efficient way to track their income, expenses, categories, budgets, uploaded bills, and to receive alerts whenever they exceed spending limits. This README describes the project, its files, design choices, and how the system works.

## Overview
After registering and logging in, each user accesses a personalized dashboard. The homepage displays the month’s income, expenses, remaining balance, the ten most recent transactions, and a form to add new transactions. All timestamps are stored in UTC but converted to IST for display.

Users can manage categories by creating, editing, and deleting them. Global categories are shared across all users and cannot be modified or removed. This allows flexibility while keeping structure.

The alert system allows users to create monthly spending alerts either for a single category or across all categories. When a user exceeds the set threshold for the current month, the system triggers a one-time alert and displays a warning on the homepage.

The Bills Upload System lets users upload PDFs and images of bills. Filenames are sanitized using Werkzeug, and files are stored securely in `static/uploads/`. Each upload is recorded in the database with timestamps converted to IST on display.

Charts are generated using Chart.js and include a donut chart for category-wise expenses, a 7‑day spending chart, and a monthly day‑wise spending line chart.

A light/dark theme switch is implemented through Bootstrap 5.3’s theming system and saved in localStorage.

## File Breakdown
### app.py
This is the main application file. It manages:
- User authentication (login, logout, registration)
- Adding, editing, and viewing transactions
- Category management
- File uploads and bill deletion
- Alerts system logic
- Data formatting, IST conversion
- Chart data preparation
- Flash messaging
It is the core engine of the web app.

### helpers.py
Contains utility functions:
- `db_username_exists()` ensures no duplicate usernames.
- `login_required` decorator restricts access to logged-in users.

### layout.html
Defines the global structure of all pages. It includes:
- Navbar
- Theme toggle
- Offcanvas menu
- Base Bootstrap CSS/JS
Other templates extend this.

### index.html
Homepage UI:
- Monthly totals (income, expenses, balance)
- Add Amount form
- Recent transactions (IST formatted)
- Category-wise expense summary
- Alerts modal to create alerts
- Month vs last month comparison

### transactions.html
Displays all transactions with timestamps and category names. Includes edit functionality.

### category.html
Allows creation, editing, and deletion of custom categories. Prevents deletion of categories currently used by transactions.

### charts.html
Contains three interactive charts generated using Chart.js. All data values and labels are dynamically passed from Python.

### bills.html
Displays uploaded bills with amounts and formatted timestamps. Allows uploading of new bills and deleting existing ones.

### static/uploads/
Stores uploaded bill files.

### styles.css
Contains optional custom CSS styling.

### transactions.db
SQLite database storing users, categories, transactions, alerts, and bill uploads.

## Design Choices
SQLite was chosen due to its simplicity and suitability for small apps. All timestamps are kept in UTC to avoid inconsistencies and converted to IST during output. Alerts store the `last_triggered_month` so each alert only fires once per month. File uploads include user ID and timestamp in the saved filename to avoid collisions. Bootstrap’s theming makes dark mode trivial and intuitive. Chart.js was selected due to ease of integration and clean visuals.

## How to Run
1. Install dependencies:
```
pip install flask flask-session werkzeug pytz
```
2. Run the application:
```
python app.py
```
3. Visit in browser:
```
http://127.0.0.1:5000
```

## Conclusion
This project incorporates all major concepts from CS50 including Python, SQL, Flask, HTML, CSS, Bootstrap, sessions, user state, validation, secure file handling, chart visualization, and backend logic. It is a complete web application that helps users track and understand their personal financial activity. The combination of technical features and real-world usefulness makes this a fitting CS50 Final Project.

