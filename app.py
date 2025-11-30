from flask import Flask, render_template, request, redirect, session, url_for, flash, get_flashed_messages,Response, g
from flask_session import Session
from helpers import db_username_exists, login_required
import io
import os
import time
from werkzeug.utils import secure_filename
import csv
import pytz
import calendar
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
from functools import wraps

import sqlite3

app = Flask(__name__)                          #Start the web app
app.config["SESSION_PERMANENT"] = False        #Don’t keep user logged in forever
app.config["SESSION_TYPE"] = "filesystem"      #Store login sessions on the server
Session(app)                                   #Activate the session system
app.secret_key = "something_super_secret"
ALLOWED_EXT = {"png","jpg","jpeg","gif","pdf"}

# upload folder (relative to project root)
UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# optional: cap upload size (e.g. 8 MB)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024







def allowed_ext(ext):
    return ext.lower() in ALLOWED_EXT

def build_final_filename(user_filename_base, uploaded_file_ext, user_id, avoid_collision=True):
    """
    user_filename_base: string provided by user (e.g. "electricity_jan")
    uploaded_file_ext: extension like 'png' (no dot)
    returns a safe final filename (e.g. 'electricity_jan_1698762304.png')
    """
    # sanitize the user-provided base
    safe_base = secure_filename(user_filename_base) or "file"
    ext = uploaded_file_ext.lower().lstrip(".")
    if not allowed_ext(ext):
        return None

    # add user id and timestamp to reduce collisions
    ts = int(time.time())
    final = f"{safe_base}_u{user_id}_{ts}.{ext}"
    return final


# ----------------------------
# Helper: check & update alerts
# ----------------------------
def check_and_update_alert_single_table(user_id, category_id, db):
    """
    After a transaction is inserted and committed, call this with the same db connection.
    Updates alerts.last_triggered_month/last_triggered_at/last_total only once per month.
    Returns a list of triggered alerts (as dicts) for UI if any.
    """
    cur = db.cursor()

    # current month key like '2025-11'
    cur.execute("SELECT strftime('%Y-%m','now') as m")
    month_row = cur.fetchone()
    month_key = month_row[0] if month_row is not None else None
    if not month_key:
        return []

    # --------- Compute totals ----------
    # total across all categories for this user this month (used by "all categories" alerts)
    cur.execute("""
        SELECT COALESCE(SUM(amount),0) AS total_all
        FROM transactions
        WHERE user_id = ? AND type = 'expense'
          AND strftime('%Y-%m', created_at) = ?
    """, (user_id, month_key))
    total_all_row = cur.fetchone()
    total_all = float(total_all_row[0] if total_all_row is not None else 0.0)

    # total for the specific category (if category_id provided) — used by category-specific alerts
    total_for_category = 0.0
    if category_id:
        cur.execute("""
            SELECT COALESCE(SUM(amount),0) AS total_cat
            FROM transactions
            WHERE user_id = ? AND category_id = ? AND type = 'expense'
              AND strftime('%Y-%m', created_at) = ?
        """, (user_id, category_id, month_key))
        total_cat_row = cur.fetchone()
        total_for_category = float(total_cat_row[0] if total_cat_row is not None else 0.0)

    # fetch alerts relevant to this user and (global or this category)
    cur.execute("""
        SELECT id, amount_threshold, category_id, last_triggered_month
        FROM alerts
        WHERE user_id = ? AND active = 1
          AND (category_id IS NULL OR category_id = ?)
    """, (user_id, category_id))
    alerts = cur.fetchall()

    triggered_alerts = []
    for a in alerts:
        alert_id = a["id"]
        threshold = float(a["amount_threshold"])
        last_month = a["last_triggered_month"]  # may be None

        already_triggered = (last_month == month_key)

        # choose correct total to compare against:
        # - if alert is global (category_id is NULL) -> compare against total_all
        # - else -> compare against total_for_category
        compare_total = total_all if a["category_id"] is None else total_for_category

        if compare_total > threshold:
            # Update alert only if not already triggered this month
            if not already_triggered:
                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("""
                    UPDATE alerts
                    SET last_triggered_month = ?, last_triggered_at = ?, last_total = ?
                    WHERE id = ?
                """, (month_key, now, compare_total, alert_id))
                db.commit()

            # Include alert for UI (whether newly updated or previously triggered)
            triggered_alerts.append({
                "alert_id": alert_id,
                "threshold": threshold,
                "total": compare_total,
                "category_id": a["category_id"],
                "last_triggered_month": month_key
            })

    return triggered_alerts



# ----------------------------
# Routes
# ----------------------------
@app.route("/", methods=["GET","POST"])
@login_required
def index():
    if request.method=="GET":
        username = session.get("username")
        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()

        # Latest month rows (same as your original)
        cur.execute("""
            SELECT *
            FROM transactions
            WHERE strftime('%Y-%m', created_at) = (
                SELECT strftime('%Y-%m', MAX(created_at)) FROM transactions) AND user_id=?
        """, (session["user_id"],))

        latest_month_rows = cur.fetchall()

        # categories for dropdowns (kept as cat_rows to avoid renaming templates)
        cur.execute("SELECT id, name FROM categories WHERE (user_id IS NULL OR user_id=?)",(session["user_id"],))
        cat_rows=cur.fetchall()
        # also pass categories alias for any templates expecting 'categories'
        categories = cat_rows

        # recent transactions (same as original)
        cur.execute("""
            SELECT 
                t.amount,
                t.type,
                c.name AS category,
                t.created_at
            FROM transactions t
            LEFT JOIN categories c 
                ON t.category_id = c.id
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
            LIMIT 10
            """, (session["user_id"],))
        rows = cur.fetchall()
        rows = [dict(r) for r in rows]

        ist = pytz.timezone("Asia/Kolkata")

        for r in rows:
            dt = datetime.fromisoformat(r["created_at"])  # convert string → datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            r["created_at_fmt"] = dt.astimezone(ist).strftime("%d %b %Y, %I:%M %p")


        total_income  = sum(r['amount'] for r in latest_month_rows if r['type'] == 'income')
        total_expense = sum(r['amount'] for r in latest_month_rows if r['type'] == 'expense')
        balance = total_income - total_expense

        cur.execute("""
            SELECT c.name AS category, SUM(t.amount) AS total_expense
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.user_id = ?
            AND t.type = 'expense'
            AND strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
            GROUP BY t.category_id ORDER BY SUM(t.amount) DESC LIMIT 5
            """, (session["user_id"],))

        category_expenses = cur.fetchall()


        # This month total expense
        cur.execute("""
            SELECT SUM(amount)
            FROM transactions
            WHERE user_id = ?
            AND type = 'expense'
            AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
            """, (session["user_id"],))
        this_month = cur.fetchone()[0] or 0   # prevent None

        # Last month total expense
        cur.execute("""
            SELECT SUM(amount)
            FROM transactions
            WHERE user_id = ?
            AND type = 'expense'
            AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', '-1 month')
            """, (session["user_id"],))
        last_month = cur.fetchone()[0] or 0

        if last_month == 0:
            percent_change = 0   # or you can set it to None or 100
        else:
            percent_change = ((this_month - last_month) / last_month) * 100

        # ---- NEW: fetch triggers (alerts that fired this month) ----
        cur.execute("SELECT strftime('%Y-%m','now') as m")
        month_key_row = cur.fetchone()
        month_key = month_key_row[0] if month_key_row is not None else None

        triggers = []
        if month_key:
            cur.execute("""
                SELECT id AS alert_id, amount_threshold, category_id, last_triggered_at, last_total
                FROM alerts
                WHERE user_id = ? AND last_triggered_month = ?
            """, (session["user_id"], month_key))
            triggers = cur.fetchall()  # list of sqlite3.Row

        db.close()

        return render_template("index.html",
                               username=username,
                               income=total_income,
                               expenses=total_expense,
                               balance=balance,
                               rows=rows,
                               category_expenses=category_expenses,
                               this_month=this_month,
                               last_month=last_month,
                               change=percent_change,
                               cat_rows=cat_rows,
                               categories=categories,
                               triggers=triggers)

    # ----------------- POST: add a transaction -----------------
    if request.method=="POST":
        amount=request.form.get("amount")
        category=request.form.get("category")
        txn_type=request.form.get("type")

        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()

        cur.execute("SELECT id FROM categories WHERE name = ? AND (user_id IS NULL OR user_id = ?)", (category, session["user_id"]))
        row = cur.fetchone()
        if not row:
            db.close()
            flash("Category not found", "danger")
            return redirect(url_for("index"))

        cat_id = row["id"]

        # -------------------------
        # Minimal change: convert amount to float before insert
        # -------------------------
        try:
            amount = float(amount)   # <-- convert to numeric to avoid lexicographic compares later
        except (TypeError, ValueError):
            db.close()
            flash("Invalid amount", "danger")
            return redirect(url_for("index"))

        cur.execute('INSERT INTO transactions (user_id,amount,"type",category_id) VALUES (?,?,?,?)',(session["user_id"],amount,txn_type,cat_id))
        db.commit()

        # ---- NEW: check alerts (will update alerts.last_triggered_* once per month) ----
        try:
            triggered = check_and_update_alert_single_table(session["user_id"], cat_id, db)
            if triggered:
                # use the first triggered alert for message (can iterate if you want multiple)
                alert = triggered[0]

                # IMPORTANT: decide category name based on the alert row's category_id,
                # NOT the transaction's cat_id variable (which is always the transaction's category).
                alert_cat_id = alert.get("category_id")  # this may be None for "All Categories"
                if alert_cat_id is None:
                    cat_name = "All Categories"
                else:
                    # fetch the name for the alert's category_id
                    cur.execute("SELECT name FROM categories WHERE id = ?", (alert_cat_id,))
                    cat_row = cur.fetchone()
                    cat_name = cat_row["name"] if cat_row else "Unknown"

                # use the monthly total from the alert, not the current transaction amount
                monthly_total = float(alert.get("total", 0))
                threshold = float(alert.get("threshold", 0))

                # format and flash
                flash(
                    f"⚠ Limit exceeded for {cat_name} — Spent ₹{monthly_total:.0f} (Limit: ₹{threshold:.0f})",
                    "warning"
                )

                # debug
                app.logger.debug("Alert fired: alert_cat_id=%s cat_name=%s monthly_total=%s threshold=%s triggered=%s",
                                alert_cat_id, cat_name, monthly_total, threshold, triggered)



        except Exception as e:
            # do not break user flow if alert check fails
            print("Alert check failed:", e)

        db.close()
        return redirect(url_for("index"))


@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="GET":
        return render_template("register.html")

    if request.method=="POST":
        username=request.form.get("username")
        if not username:
            flash("Username cannot be empty!", "danger")
            return redirect(url_for("register"))

        password=request.form.get("password")
        if not password:
            flash("Must enter Password!","danger")
            return redirect(url_for("register"))

        confirmation=request.form.get("confirmation")
        if not confirmation:
            flash("Must confirm password!","danger")
            return redirect(url_for("register"))

        terms = request.form.get("terms")
        if not terms:
            flash("You must agree to the Terms & Conditions!", "danger")
            return redirect(url_for("register"))

        if password!=confirmation:
            flash("Passwords do not match!","danger")
            return redirect(url_for("register"))

        if db_username_exists(username):
            flash("Username already taken!","danger")
            return redirect(url_for("register"))

        hash=generate_password_hash(password)

        db=sqlite3.connect("transactions.db")
        cur=db.cursor()
        cur.execute("INSERT INTO users(username,password_hash) VALUES(?,?)",(username, hash))
        db.commit()

        session.clear()
        new_user_id = cur.lastrowid
        session["user_id"] = new_user_id
        session["username"] = username


        return redirect(url_for("index", username=username))


@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="GET":
        return render_template("login.html")

    if request.method=="POST":
        username=request.form.get("username")
        if not username:
            flash("Username cannot be empty!", "danger")
            return redirect(url_for("login"))

        password=request.form.get("password")
        if not password:
            flash("Must enter Password!","danger")
            return redirect(url_for("login"))

        if not db_username_exists(username):
            flash("Username does not exist!","danger")
            return redirect(url_for("login"))

        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()
        cur.execute("SELECT password_hash FROM users WHERE username=?",(username,))
        user_pass=cur.fetchone()

        if not check_password_hash(user_pass["password_hash"], password):
            flash("Incorrect password!","danger")
            return redirect(url_for("login"))

        session.clear()
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        user_id = cur.fetchone()["id"]
        session["user_id"] = user_id
        session["username"] = username


        return redirect(url_for("index", username=username))



@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))



@app.route("/transactions", methods=["GET"])
@login_required
def transactions():
    if request.method=="GET":
        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()


        cur.execute("""
            SELECT
                t.id,
                t.amount,
                t.type,
                c.name AS category,
                t.created_at
            FROM transactions t
            LEFT JOIN categories c 
                ON t.category_id = c.id
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
            """, (session["user_id"],))
        rows = cur.fetchall()
        rows = [dict(r) for r in rows]

        ist = pytz.timezone("Asia/Kolkata")

        for r in rows:
            dt = datetime.fromisoformat(r["created_at"])  # convert string → datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            r["created_at_fmt"] = dt.astimezone(ist).strftime("%d %b %Y, %I:%M %p")


        cur.execute("""
            SELECT name 
            FROM categories 
            WHERE user_id = ? OR user_id IS NULL
            """, (session["user_id"],))

        all_categories = cur.fetchall()


        return render_template("transactions.html",rows=rows,categories=all_categories)



@app.route("/edit", methods=["POST"])
@login_required
def edit_transaction():
    id = request.form.get("id")
    amount = request.form.get("amount")
    txn_type = request.form.get("type")
    category = request.form.get("category")

    db = sqlite3.connect("transactions.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # find category id
    cur.execute("SELECT id FROM categories WHERE name=? AND (user_id=? OR user_id IS NULL)",
        (category, session["user_id"]))
    cat = cur.fetchone()
    if not cat:
        flash("Category not found", "danger")
        return redirect("/transactions")

    cat_id = cat["id"]

    cur.execute("""
        UPDATE transactions SET amount=?, type=?, category_id=?
        WHERE id=? AND user_id=?
    """, (amount, txn_type, cat_id, id, session["user_id"]))

    db.commit()
    db.close()

    return redirect("/transactions")




@app.route("/categories", methods=["GET","POST"])
@login_required
def category():
    if request.method=="GET":
        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()
        cur.execute("SELECT * FROM categories WHERE (user_id IS NULL OR user_id=?)", (session["user_id"],))
        rows=cur.fetchall()
        db.close()
        return render_template("category.html",rows=rows)




@app.route("/edit-category", methods=["POST"])
@login_required
def edit_category():
    if request.method=="POST":
        id = request.form.get("id")
        name = request.form.get("name")

        db = sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur = db.cursor()

        # Check if category exists and belongs to this user (or is global)
        cur.execute("SELECT id, user_id FROM categories WHERE id = ?", (id,))
        cat = cur.fetchone()
        if not cat:
            db.close()
            flash("Category not found.", "danger")
            return redirect("/categories")

        # Prevent editing global categories if you want them locked
        if cat["user_id"] is None:
            db.close()
            flash("Cannot edit global category.", "danger")
            return redirect("/categories")

        # Update category name
        cur.execute("UPDATE categories SET name = ? WHERE id = ?", (name, id))
        db.commit()
        db.close()

        flash("Category updated.", "success")
        return redirect("/categories")




@app.route("/delete-category", methods=["GET","POST"])
@login_required
def delete_category():
    if request.method=="POST":
        id = request.form.get("id")
        name = request.form.get("name")

        db = sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur = db.cursor()
        cur.execute("SELECT id, user_id, name FROM categories WHERE id = ?", (id,))
        cat = cur.fetchone()
        if not cat:
            db.close()
            flash("Category not found.", "danger")
            return redirect(url_for("category"))

        if cat["user_id"] is None:
            db.close()
            flash("Cannot delete global category.", "danger")
            return redirect(url_for("category"))

        if cat["user_id"] != session["user_id"]:
            db.close()
            flash("You are not allowed to delete this category.", "danger")
            return redirect(url_for("category"))



        cur.execute("SELECT COUNT(*) FROM transactions WHERE category_id = ?", (id,))
        ref_count = cur.fetchone()[0] or 0
        if ref_count > 0:
            db.close()
            flash(f"Cannot delete — {ref_count} transaction(s) use this category.", "danger")
            return redirect(url_for("category"))

        cur.execute("DELETE FROM categories WHERE id = ?", (id,))
        db.commit()
        db.close()
        flash(f"Category '{cat['name']}' deleted.", "success")
        return redirect(url_for("category"))




@app.route("/add-category",methods=["POST"])
@login_required
def add_category():
    if request.method=="POST":
        name=request.form.get("name")
        db = sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur = db.cursor()
        cur.execute("SELECT id FROM categories WHERE name=? AND (user_id=? OR user_id IS NULL)", (name, session['user_id']))
        if cur.fetchone():
            db.close()
            flash("Category already exists.", "danger")
            return redirect(url_for("category"))
        if not name.strip():
            db.close()
            flash("Category name cannot be empty.", "danger")
            return redirect(url_for("category"))

        cur.execute("INSERT INTO categories (name,user_id) VALUES (?,?)",(name,session["user_id"]))
        db.commit()
        db.close()
        return redirect("/categories")




@app.route("/charts",methods=["GET"])
@login_required
def charts():
    if request.method=="GET":
        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()
        cur.execute("""
            SELECT 
                c.name AS category,
                SUM(t.amount) AS total_expense
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE 
                t.type = 'expense'
                AND t.user_id = ?
                AND strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
            GROUP BY c.name
            """, (session["user_id"],))

        rows = cur.fetchall()


        labels_donut = [row["category"] for row in rows]
        values_donut = [row["total_expense"] for row in rows]
        labels_donut_js = str(labels_donut)
        values_donut_js = str(values_donut)

        cur.execute("""
            SELECT 
                strftime('%Y-%m-%d', t.created_at) AS day,
                COALESCE(SUM(t.amount), 0) AS total_expense
            FROM transactions t
            WHERE 
                t.type = 'expense'
                AND t.user_id = ?
                AND date(t.created_at) BETWEEN date('now','-6 days') AND date('now')
            GROUP BY day
        """, (session["user_id"],))
        rows_7 = cur.fetchall()

        # Build a dict like {"2025-01-21": 312.1, ...}
        day_to_sum = {row["day"]: float(row["total_expense"] or 0) for row in rows_7}

        # Create labels for last 7 days in correct order
        from datetime import datetime, timedelta
        today = datetime.now().date()

        labels_7 = []
        values_7 = []

        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            day_sql = d.strftime("%Y-%m-%d")
            labels_7.append(d.strftime("%d %b"))      # pretty date like "29 Nov"
            values_7.append(day_to_sum.get(day_sql, 0))

        labels_7_js = str(labels_7)
        values_7_js = str(values_7)

        cur.execute("""
            SELECT 
                strftime('%d', t.created_at) AS day,
                SUM(t.amount) AS total_expense
            FROM transactions t
            WHERE 
                t.type = 'expense'
                AND t.user_id = ?
                AND strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
            GROUP BY day
            ORDER BY day
            """, (session["user_id"],))

        rows_month_line = cur.fetchall()

        today = datetime.now()
        days_in_month = calendar.monthrange(today.year, today.month)[1]

        # dict like {"01": 120.0, "02": 0, ...}
        day_to_sum = {row["day"]: float(row["total_expense"] or 0) for row in rows_month_line}

        labels_line = []
        values_line = []

        for d in range(1, days_in_month + 1):
            day_str = f"{d:02d}"   # "01", "02", etc.
            labels_line.append(day_str)
            values_line.append(day_to_sum.get(day_str, 0))

        labels_line_js = str(labels_line)
        values_line_js = str(values_line)

        return render_template("charts.html", labels_donut_js=labels_donut_js, values_donut_js=values_donut_js, labels_7_js=labels_7_js, values_7_js=values_7_js, labels_line_js=labels_line_js, values_line_js=values_line_js)




@app.route("/download/transactions.csv")
@login_required
def download_transactions_csv():
    user_id = session["user_id"]

    db = sqlite3.connect("transactions.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("""
        SELECT t.id, t.created_at, t.amount, t.type, c.name AS category
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.created_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    db.close()

    # build CSV in-memory
    si = io.StringIO()
    writer = csv.writer(si)

    # header row
    writer.writerow(["id", "created_at_IST", "amount", "type", "category"])

    # CSV-injection protection
    def safe_cell(val):
        if val is None:
            return ""
        s = str(val)
        if s and s[0] in ("=", "+", "-", "@", "\t"):
            return "'" + s
        return s

    # Convert UTC --> IST (UTC + 5:30)
    IST_OFFSET = timedelta(hours=5, minutes=30)

    for r in rows:
        # convert from string → datetime → add offset → format back
        try:
            utc_dt = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
            ist_dt = utc_dt + IST_OFFSET
            ist_str = ist_dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            # if parsing fails, just use original string
            ist_str = r["created_at"]

        writer.writerow([
            r["id"],
            ist_str,                # <-- IST timestamp
            r["amount"],
            r["type"],
            safe_cell(r["category"])
        ])

    output = si.getvalue()
    si.close()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"transactions_{user_id}_{ts}.csv"

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )



@app.route("/alerts", methods=["POST"])
@login_required
def alerts():
    if request.method == "POST":
        threshold = request.form.get("amount_threshold")
        cat_id = request.form.get("category_id")
        if cat_id == "all":
            cat_id = None
        else:
            # -------------------------
            # Minimal change: ensure cat_id stored as integer (or None)
            # -------------------------
            try:
                cat_id = int(cat_id)   # <-- convert form value to integer id
            except (TypeError, ValueError):
                cat_id = None          # <-- fallback (prevents storing names accidentally)

        # validate threshold
        try:
            threshold_val = float(threshold)
        except (TypeError, ValueError):
            flash("Invalid alert amount", "danger")
            return redirect(url_for("index"))

        db = sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur = db.cursor()

        # Insert alert with empty last_triggered_* fields (no trigger yet)
        cur.execute("""
            INSERT INTO alerts (user_id, amount_threshold, category_id, last_triggered_month, last_total)
            VALUES (?, ?, ?, ?, ?)
        """, (session["user_id"], threshold_val, cat_id, None, None))

        db.commit()
        db.close()
        flash("Alert added", "success")
        return redirect(url_for("index"))
    








@app.route("/bills", methods=["GET", "POST"])
@login_required
def bills():
    user_id = session["user_id"]

    # --- POST: handle upload ---
    if request.method == "POST":
        # get user-provided filename (base) and optional amount
        user_filename = (request.form.get("filename") or "").strip()
        amount_raw = request.form.get("amount")
        try:
            amount_val = float(amount_raw) if amount_raw not in (None, "",) else None
        except ValueError:
            flash("Invalid amount", "danger")
            return redirect(url_for("bills"))

        # file field
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please select a file to upload", "danger")
            return redirect(url_for("bills"))

        # infer extension from uploaded file name
        if "." not in file.filename:
            flash("Uploaded file has no extension", "danger")
            return redirect(url_for("bills"))
        ext = file.filename.rsplit(".", 1)[1].lower()
        if not allowed_ext(ext):
            flash("File type not allowed. Allowed: png, jpg, jpeg, gif, pdf", "danger")
            return redirect(url_for("bills"))

        # build final filename (user-provided base + ext) and sanitize
        final_filename = build_final_filename(user_filename or "bill", ext, user_id)
        if not final_filename:
            flash("Invalid filename", "danger")
            return redirect(url_for("bills"))

        # ensure upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        save_path = os.path.join(app.config['UPLOAD_FOLDER'], final_filename)
        try:
            file.save(save_path)
        except Exception as e:
            app.logger.exception("Failed saving uploaded file")
            flash("Failed to save file", "danger")
            return redirect(url_for("bills"))

        # insert DB row (uploaded_at remains UTC in DB)
        db = sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur = db.cursor()
        cur.execute("""
            INSERT INTO bills (user_id, filename, amount)
            VALUES (?, ?, ?)
        """, (user_id, final_filename, amount_val))
        db.commit()
        db.close()

        flash("Bill uploaded successfully", "success")
        return redirect(url_for("bills"))

    # --- GET: show bills list ---
    db = sqlite3.connect("transactions.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute("""
        SELECT id, filename, amount, uploaded_at
        FROM bills
        WHERE user_id = ?
        ORDER BY uploaded_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    db.close()

    # convert stored UTC uploaded_at -> IST and format nicely ("30 November 2025")
    ist = pytz.timezone("Asia/Kolkata")
    bills = []
    for r in rows:
        rec = dict(r)
        ua = rec.get("uploaded_at")
        formatted = ""
        if ua:
            try:
                # try common SQLite format first: "YYYY-MM-DD HH:MM:SS"
                dt = datetime.strptime(ua, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    # fallback: ISO format / other variants
                    dt = datetime.fromisoformat(ua)
                except Exception:
                    dt = None

            if dt is not None:
                # assume stored time is UTC if naive
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC)
                # convert to IST and format
                try:
                    dt_ist = dt.astimezone(ist)
                    formatted = dt_ist.strftime("%d %B %Y")  # e.g., "30 November 2025"
                except Exception:
                    formatted = ua
            else:
                formatted = ua

        rec["uploaded_at_fmt"] = formatted
        bills.append(rec)

    return render_template("bills.html", bills=bills)



@app.route("/bills/delete/<int:bill_id>", methods=["POST"])
@login_required
def delete_bill(bill_id):
    db = sqlite3.connect("transactions.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute("SELECT filename, user_id FROM bills WHERE id = ?", (bill_id,))
    row = cur.fetchone()
    if not row:
        db.close()
        flash("Bill not found", "danger")
        return redirect(url_for("bills"))

    if row["user_id"] != session["user_id"]:
        db.close()
        flash("Not allowed", "danger")
        return redirect(url_for("bills"))

    # delete file on disk
    try:
        path = os.path.join(app.config['UPLOAD_FOLDER'], row["filename"])
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        app.logger.debug("Error removing file: %s", e)

    cur.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
    db.commit()
    db.close()
    flash("Bill deleted", "success")
    return redirect(url_for("bills"))



if __name__ == "__main__":
    app.run(debug=True)
