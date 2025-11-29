from flask import Flask, render_template, request, redirect, session, url_for, flash, get_flashed_messages
from flask_session import Session
from helpers import db_username_exists, login_required
import pytz
from flask import jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
from functools import wraps

import sqlite3

app = Flask(__name__)                          #Start the web app
app.config["SESSION_PERMANENT"] = False        #Don’t keep user logged in forever
app.config["SESSION_TYPE"] = "filesystem"      #Store login sessions on the server
Session(app)                                   #Activate the session system
app.secret_key = "something_super_secret"
                           

@app.route("/", methods=["GET","POST"])
@login_required
def index():
    if request.method=="GET":
        username = session.get("username")
        db=sqlite3.connect("transactions.db")
        db.row_factory = sqlite3.Row
        cur=db.cursor()

        cur.execute("""
            SELECT *
            FROM transactions
            WHERE strftime('%Y-%m', created_at) = (
                SELECT strftime('%Y-%m', MAX(created_at)) FROM transactions) AND user_id=?
        """, (session["user_id"],))

        latest_month_rows = cur.fetchall()

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





        
        return render_template("index.html", username=username, income=total_income, expenses=total_expense, balance=balance, rows=rows, category_expenses=category_expenses, this_month=this_month, last_month=last_month, change=percent_change)
    
    if request.method=="POST":
        amount=request.form.get("amount")
        category=request.form.get("category")
        txn_type=request.form.get("type")

    
        db=sqlite3.connect("transactions.db")
        db.row_factory=sqlite3.Row
        cur=db.cursor()
        cur.execute("SELECT id FROM categories WHERE name = ? AND user_id IS NULL OR user_id = ?", (category, session["user_id"]))
        row = cur.fetchone()
        if not row:
            db.close()
            flash("Category not found", "danger")
            return redirect(url_for("index"))

        cat_id = row["id"]
        cur.execute('INSERT INTO transactions (user_id,amount,"type",category_id) VALUES (?,?,?,?)',(session["user_id"],amount,txn_type,cat_id))
        db.commit()
        db.close()

        return redirect("/")









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












if __name__ == "__main__":
    app.run(debug=True)