from flask import Flask, render_template, request, redirect, session
from flask_session import Session
import sqlite3

app = Flask(__name__)                          #Start the web app
app.config["SESSION_PERMANENT"] = False        #Don’t keep user logged in forever
app.config["SESSION_TYPE"] = "filesystem"      #Store login sessions on the server
Session(app)                                   #Activate the session system

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register")
def register():
    if request.method=="GET":
        return render_template("register.html")
    
    if request.method=="POST":
        










if __name__ == "__main__":
    app.run(debug=True)
