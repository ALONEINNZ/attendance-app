from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_mail import Mail, Message
import secrets

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "main.db")

load_dotenv(Path(".env"))

app.config["SECRET_KEY"] = os.getenv("KEY", "dev-secret-key")
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

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


def get_db():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            verify_key TEXT NOT NULL,
            is_verified INTEGER DEFAULT 0,
            pfp TEXT DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            time TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def send_email(user_email, verify_key):
    try:
        if not user_email.lower().endswith(SCHOOL_EMAIL_DOMAIN):
            print("Email blocked: not Burnside email")
            flash("Please use your Burnside school email!")
            return False

        link = url_for("verify", verify_key=verify_key, _external=True)

        msg = Message(
            subject="Verify your email",
            sender=app.config["MAIL_USERNAME"],
            recipients=[user_email],
            body=f"Click this link to verify your account:\n{link}",
        )

        mail.send(msg)
        print("EMAIL SENT TO:", user_email)
        return True

    except Exception as e:
        print("EMAIL FAILED:", e)
        flash(f"Email failed: {e}")
        return False
    
@app.route("/")
def home():
    return render_template("Home.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        email = request.form.get("email", "").strip().lower()
        code = request.form.get("code", "").strip()

        if not username or not password or not confirm_password or not email or not code:
            error = "Please fill in all fields."
        elif password != confirm_password:
            error = "Passwords don't match!"
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif len(username) > 10:
            error = "Username too long."
        elif not code.isdigit() or len(code) != 5:
            error = "Invalid student ID."
        elif not email.endswith(SCHOOL_EMAIL_DOMAIN):
            error = "Email must be a Burnside school email."
        elif email.split("@")[0] != code:
            error = "Email must match your student ID."
        else:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM users WHERE username = ? OR code = ? OR email = ?",
                (username, code, email),
            )
            existing_user = cursor.fetchone()

            if existing_user:
                error = "User already exists."
            else:
                verify_key = secrets.token_urlsafe(32)
                hashed_password = generate_password_hash(password)

                cursor.execute("""
                    INSERT INTO users 
                    (username, password, code, email, verify_key, is_verified)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (username, hashed_password, code, email, verify_key, 0))

                conn.commit()
                conn.close()

                if not send_email(email, verify_key):
                    error = "Account made, but email failed. Check terminal."
                    return render_template("signup.html", header="signup", error=error)
                
                return render_template(
                    "login.html",
                    header="login",
                    error="Account created. Check your email to verify."
                )

            conn.close()

    return render_template("signup.html", header="signup", error=error)


@app.route("/verify/<verify_key>")
def verify(verify_key):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET is_verified = 1 WHERE verify_key = ?",
        (verify_key,)
    )

    conn.commit()
    conn.close()

    return render_template(
        "login.html",
        header="login",
        error="Email verified. You can now log in."
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, password, code, email, verify_key, is_verified, pfp
            FROM users
            WHERE username = ?
        """, (username,))

        user = cursor.fetchone()
        conn.close()

        if user is None:
            error = "User not found."
        elif user[6] == 0:
            error = "Not verified. Check your email."
        elif check_password_hash(user[2], password):
            session["username"] = user[1]
            session["code"] = user[3]
            session["email"] = user[4]
            session["pfp"] = user[7]
            return redirect(url_for("home"))
        else:
            error = "Incorrect password."

    return render_template("login.html", header="login", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "GET":
        return render_template("account.html", header="account")

    if "file" not in request.files:
        flash("No file uploaded.")
        return redirect(request.url)

    file = request.files["file"]

    if file.filename == "":
        flash("No file selected.")
        return redirect(request.url)

    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET pfp = ? WHERE username = ?",
        (filename, session["username"])
    )

    conn.commit()
    conn.close()

    session["pfp"] = filename

    return redirect(url_for("home"))


@app.route("/teacher")
@login_required
def teacher():
    return render_template("Teacher.html")


def load_attendance():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT name, time FROM attendance")
    rows = cursor.fetchall()

    conn.close()

    return {row[0]: row[1] for row in rows}


def save_attendance(name, time):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO attendance (name, time) VALUES (?, ?)",
        (name, time)
    )

    conn.commit()
    conn.close()


@app.route("/checkin", methods=["POST"])
@login_required
def checkin():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"message": "No data sent."}), 400

        name = data.get("name", "").strip()

        if not name:
            return jsonify({"message": "Name is required."}), 400

        attendance = load_attendance()

        if name in attendance:
            return jsonify({"message": "Already checked in."})

        current_time = datetime.now().strftime("%H:%M")

        save_attendance(name, current_time)

        return jsonify({"message": "Checked in successfully."})

    except sqlite3.IntegrityError:
        return jsonify({"message": "Already checked in."}), 400
    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500


@app.route("/attendance")
@login_required
def attendance():
    try:
        data = load_attendance()
        result = [{"name": name, "time": time} for name, time in data.items()]
        return jsonify(result)

    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)