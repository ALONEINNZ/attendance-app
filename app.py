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
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth



app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "main.db")
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "main.db")

load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
print("MAIL USER:", os.getenv("USERNAME"))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

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
print("MAIL USER:", os.getenv("USERNAME"))
print("MAIL USER:", os.getenv("USERNAME"))
print("PASSWORD LENGTH:", len(os.getenv("PASSWORD", "")))
mail = Mail(app)

app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID")
app.config["GOOGLE_CLIENT_SECRET"] = os.getenv("GOOGLE_CLIENT_SECRET")

oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


SCHOOL_EMAIL_DOMAIN = "@burnside.school.nz"
    
@app.before_request
def log_visitor_ip():
    cf_ip = request.headers.get("CF-Connecting-IP")
    forwarded = request.headers.get("X-Forwarded-For", "")
    direct_ip = request.remote_addr

    real_ip = cf_ip or (forwarded.split(",")[0].strip() if forwarded else direct_ip)

    print(f"[IP LOG] path={request.path} cf_connecting_ip={cf_ip!r} "
          f"remote_addr={direct_ip} x-forwarded-for={forwarded!r} resolved={real_ip}", flush=True)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


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
            verify_key TEXT UNIQUE NOT NULL,
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


# def send_email(user_email, verify_key):
#     if not user_email.lower().endswith(SCHOOL_EMAIL_DOMAIN):
#         return False, "Please use your Burnside school email."

#     try:
#         link = url_for("verify", verify_key=verify_key, _external=True)

#         msg = Message(
#             subject="Verify your email",
#             sender=app.config["MAIL_USERNAME"],
#             recipients=[user_email],
#             body=f"Click this link to verify your account:\n\n{link}",
#         )

#         mail.send(msg)
#         print("EMAIL SENT TO:", user_email)
#         return True, None

#     except Exception as e:
#         print("EMAIL FAILED:", e)
        # return False, str(e)


@app.route("/")
def home():
    return render_template("Home.html")


@app.route("/auth/google/callback")
def google_callback():
    token = google.authorize_access_token()
    user = token.get("userinfo")

    email = user["email"]

    if not email.lower().endswith("@burnside.school.nz"):
        return render_template(
            "login.html",
            header="login",
            error="Please use your Burnside school email."
        )

    conn = get_db()
    cur = conn.cursor()
    student = cur.execute('''SELECT username, code, pfp
                        FROM users
                        WHERE email = ?''', (email,)).fetchone()
    conn.close()

    if student is None:
        return render_template(
            "login.html",
            header="login",
            error="No account found for this email. Please sign up first."
        )

    session["username"] = student["username"]
    session["code"] = student["code"]
    session["email"] = email
    session["pfp"] = student["pfp"]
    session["signup_complete"] = True

    return redirect(url_for("home"))

# @app.route("/signup", methods=["GET", "POST"])
# def signup():
#     error = None

#     if request.method == "POST":
#         username = request.form.get("username", "").strip()
#         password = request.form.get("password", "")
#         confirm_password = request.form.get("confirm_password", "")
#         email = request.form.get("email", "").strip().lower()
#         code = request.form.get("code", "").strip()

#         if not username or not password or not confirm_password or not email or not code:
#             error = "Please fill in all fields."

#         elif password != confirm_password:
#             error = "Passwords don't match."

#         elif len(password) < 8:
#             error = "Password must be at least 8 characters."

#         elif len(username) > 10:
#             error = "Username must be 10 characters or less."

#         elif not code.isdigit() or len(code) != 5:
#             error = "Invalid student ID."

#         elif "@" not in email or "." not in email.split("@", 1)[1]:
#             error = "Please enter a valid email address."

#         else:
#             conn = get_db()
#             cursor = conn.cursor()

#             cursor.execute("""
#                 SELECT username, code, email, is_verified 
#                 FROM users 
#                 WHERE username = ? OR code = ? OR email = ?
#             """, (username, code, email))

#             existing_user = cursor.fetchone()

#             if existing_user:
#                 error = "User already exists."
#                 conn.close()
#                 return render_template("signup.html", header="signup", error=error)

#             verify_key = secrets.token_urlsafe(32)
#             hashed_password = generate_password_hash(password)

#             cursor.execute("""
#                 INSERT INTO users 
#                 (username, password, code, email, verify_key, is_verified)
#                 VALUES (?, ?, ?, ?, ?, ?)
#             """, (username, hashed_password, code, email, verify_key, 1))

#             conn.commit()
#             conn.close()
#             session["signup_complete"] = True

#             return render_template(
#                 "login.html",
#                 header="login",
#                 error="Account created successfully. You can now log in."
#             )

#     return render_template("signup.html", header="signup", error=error)


# @app.route("/verify/<verify_key>")
# def verify(verify_key):
#     conn = get_db()
#     cursor = conn.cursor()

#     cursor.execute("""
#         SELECT id 
#         FROM users 
#         WHERE verify_key = ?
#     """, (verify_key,))

#     user = cursor.fetchone()

#     if not user:
#         conn.close()
#         return render_template(
#             "login.html",
#             header="login",
#             error="Invalid verification link."
#         )

#     cursor.execute("""
#         UPDATE users 
#         SET is_verified = 1 
#         WHERE verify_key = ?
#     """, (verify_key,))

#     conn.commit()
#     conn.close()

#     return render_template(
#         "login.html",
#         header="login",
#         error="Email verified. You can now log in."
#     )


@app.route("/login", methods=["GET", "POST"])
def login():
    redirect_uri = url_for("google_callback", _external=True)
    print("GOOGLE REDIRECT URI:", redirect_uri)
    return google.authorize_redirect(redirect_uri)

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
        flash("No selected file.")
        return redirect(request.url)
    
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file and file_ext in allowed_extensions:
        filename = secure_filename(f"pfp_{session['code']}{file_ext}")
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET pfp = ? 
            WHERE username = ?
        """, (filename, session["username"]))
        conn.commit()
        conn.close()

        session["pfp"] = filename
        flash("Profile picture updated successfully!")
        return redirect(url_for("account"))

    flash("Invalid file type. Please upload an image.")
    return redirect(request.url)



@app.route("/teacher")
@login_required
def teacher():
    return render_template("Teacher.html")


def load_attendance_rows():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name, time 
        FROM attendance
        ORDER BY time ASC, name ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [{"name": row["name"], "time": row["time"]} for row in rows]


def load_attendance():
    rows = load_attendance_rows()
    return {row["name"]: row["time"] for row in rows}

@app.route("/reset-users")
def reset_users():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM users")

    conn.commit()
    conn.close()

    return "All users deleted. Remove this route after testing."

def save_attendance(name, time):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO attendance 
        (name, time) 
        VALUES (?, ?)
    """, (name, time))

    conn.commit()
    conn.close()


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    if request.method == "GET":
        entries = load_attendance_rows()
        return render_template("checkin.html", header="checkin", entries=entries)

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

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
       username = request.form.get("username")
       password = request.form.get("password")

    if username == "admin" and password == "admin":
            session["is_admin"] = True
            return redirect(url_for("admin"))

    else:
            error = "Invalid admin credentials."

    return render_template("admin_login.html", header="admin-login", error=error)

@app.route("/admin/reset-attendance", methods=["POST"])
@login_required
def reset_attendance():
    if session.get("username") != "admin":
        return jsonify({"message": "Unauthorized"}), 403

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM attendance")

        conn.commit()
        conn.close()

        return jsonify({"message": "Attendance reset successfully."})

    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500

@app.route("/admin")
@login_required
def admin():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, code, email, is_verified, pfp
        FROM users
    """)

    users = cursor.fetchall()
    conn.close()

    return render_template("admin.html", header="admin", users=users)

@app.route("/admin-logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)