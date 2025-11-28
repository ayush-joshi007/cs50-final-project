from flask import Flask, render_template, request, redirect, session, url_for, flash, get_flashed_messages
from flask_session import Session
from helpers import db_username_exists, login_required
import os
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
                SELECT strftime('%Y-%m', MAX(created_at)) FROM transactions
            )
        """)

        latest_month_rows = cur.fetchall()

        total_income  = sum(r['amount'] for r in latest_month_rows if r['type'] == 'income')
        total_expense = sum(r['amount'] for r in latest_month_rows if r['type'] == 'expense')
        balance = total_income - total_expense


        
        return render_template("index.html", username=username, income=total_income, expenses=total_expense, balance=balance)
    
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










if __name__ == "__main__":
    app.run(debug=True)