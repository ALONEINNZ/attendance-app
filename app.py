from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime
import socket
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from pathlib import Path
from flask_mail import Mail, Message
from flask import flash
from flask import redirect, url_for
import random
from flask import session
from functools import wraps
from flask import g
app = Flask(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "attendance.db")
load_dotenv(Path(".env"))
key = os.getenv("KEY")
app.config.update(
    MAIL_SERVER="smtp.gmail.com",
    MAIL_PORT=587,
    MAIL_USERNAME=os.getenv("USERNAME"),
    MAIL_PASSWORD=os.getenv("PASSWORD"),
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
)
mail = Mail(app)
SCHOOL_EMAIL_DOMAIN = "@burnside.school.nz"


def login_required(f):
    """Restrict access to logged-in users."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated
def send_email(user_email, key):
    """Send verification email to Burnside students only."""
    if not user_email.lower().endswith(SCHOOL_EMAIL_DOMAIN):
        flash("Please use your Burnside school email!")
        return
    msg = Message(
        subject="Verify your email",
        sender=app.config["MAIL_USERNAME"],
        recipients=[user_email],
        body=f"Confirm your email by clicking: http://127.0.0.1:5000/verify/{key}",
    )
    mail.send(msg)



@app.route("/signup", methods=["GET", "POST"])
def signup():
    """User signup route with email verification."""
    error = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        email = request.form["email"]
        code = request.form["code"]

        if password != confirm_password:
            error = "Passwords don't match!"
        elif len(password) > 8:
            error = "password is too long!"
        elif not email.endswith("@burnside.school.nz") or email.split("@")[0] != code:
            error = "Invalid email — must be @burnside and match student ID."
        elif len(code) != 5 or not code.isdigit():
            error = "Invalid student ID"
        else:
            conn = sqlite3.connect("main.db")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE username = ? OR code = ?",
                (username, code),
            )
            existing_user = cursor.fetchone()

            if existing_user:
                error = "User already exists"
            elif len(username) > 10:
                error = "username too long"
            else:
                key = random.randint(1000000000, 1000000000000000000)
                hashed_password = generate_password_hash(password)
                sql = "INSERT INTO users(username, password, code, email, key, is_verified) VALUES(?,?,?,?,?,?)"
                cursor.execute(
                    sql, (username, hashed_password, code, email, key, False)
                )
                conn.commit()
                conn.close()
                send_email(email, key)
                return render_template(
                    "login.html", header="login", error="check your email."
                )
            conn.close()

    return render_template("signup.html", header="signup", error=error)


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    """User account route with profile picture upload."""
    if request.method == "GET":
        return render_template("account.html", header="account")

    if "file" not in request.files:
        flash("No file part")
        return redirect(request.url)

    file = request.files["file"]
    filename = secure_filename(file.filename)

    # Check if a file was selected and is not empty
    if filename and file and file.filename != "":
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        conn = sqlite3.connect("main.db")
        cursor = conn.cursor()
        sql = "UPDATE users SET pfp = ? WHERE username = ?"
        cursor.execute(sql, (filename, session["username"]))
        conn.commit()
        conn.close()

        session["pfp"] = filename
        return redirect(url_for("home"))
    else:
        flash("No file selected")
        return redirect(request.url)


@app.route("/login", methods=["GET", "POST"])
def login():
    """User login route with session management."""
    error = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("main.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user is None:
            error = "User not found or Not Verified."
        elif user[5] == 0:  # is_verified check
            error = "Not verified. Check your email!"
        elif check_password_hash(user[2], password):  # hashed password
            session["username"] = username
            session["pfp"] = user[6]  # pfp assumed at index 6
            session["code"] = user[4]
            return redirect(url_for("home"))
        else:
            error = "Incorrect password."

    return render_template("login.html", header="login", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            time TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def load_data():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT name, time FROM attendance')
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def save_data(name, time):
    try:
        init_db()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO attendance (name, time) VALUES (?, ?)', (name, time))
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError as e:
        raise Exception(f"Duplicate name: {name}")
    except Exception as e:
        raise Exception(f"Database error: {str(e)}")


@app.route("/")
def index():
    return render_template("Home.html")


@app.route("/teacher")
def teacher():
    return render_template("Teacher.html")


def get_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "unknown"

@app.route("/checkin", methods=["POST"])
def checkin():
    try:
        name = request.json.get("name") if request.json else None
        if not name:
            return jsonify({"message": "Name is required"})

        server_ip = get_server_ip()
        SCHOOL_PREFIXES = ["10.1."]

        on_school_wifi = any(server_ip.startswith(prefix) for prefix in SCHOOL_PREFIXES)
        if not on_school_wifi:
            return jsonify({"message": f"You must be on the school WiFi to check in. (Server IP: {server_ip})"})

        attendance = load_data()

        if name in attendance:
            return jsonify({"message": "Already checked in"})

        current_time = datetime.now().strftime("%H:%M:")
        save_data(name, current_time)
        return jsonify({"message": "Checked in successfully"})
    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500
    

@app.route("/attendance")
def attendance():
    try:
        data = load_data()
        result = [{"name": n, "time": t} for n, t in data.items()]
        return jsonify(result)
    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500

@app.errorhandler(500)
def server_err(err):
    return render_template("500.html"), 500


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)