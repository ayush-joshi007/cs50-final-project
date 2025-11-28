import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, session, url_for

def db_username_exists(username):
    db=sqlite3.connect("transactions.db")
    cur = db.cursor()
    cur.execute("SELECT username FROM users WHERE username=?", (username,))
    rows=cur.fetchone()
    if not rows:
        return False
    return True

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # if user not logged in → redirect to login
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper