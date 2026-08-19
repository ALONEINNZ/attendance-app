from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import sqlite3
import os
import ipaddress
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

SCHOOL_NETWORKS = {
    "Burnside WiFi": [
        "202.150.123.193/32",
        "122.63.129.201/32",
        "202.36.179.108/32",
    ],
}
def is_school_ip(ip):
    try:
        client_ip = ipaddress.ip_address(ip)


        for network_name, networks in SCHOOL_NETWORKS.items():
            for network in networks:
                if client_ip in ipaddress.ip_network(network):
                    return True, network_name


    except ValueError:
        pass


    return False, None
def get_real_ip():
    cf_ip = request.headers.get("CF-Connecting-IP")
    forwarded = request.headers.get("X-Forwarded-For", "")
    direct_ip = request.remote_addr

    return cf_ip or (
        forwarded.split(",")[0].strip()
        if forwarded
        else direct_ip
    )


def is_school_ip(ip):
    try:
        client_ip = ipaddress.ip_address(ip)

        for network_name, networks in SCHOOL_NETWORKS.items():
            for network in networks:
                if client_ip in ipaddress.ip_network(network):
                    return True, network_name

    except ValueError:
        pass

    return False, None
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR, "main.db")
ATTENDANCE_DB_FILE = os.path.join(BASE_DIR, "attendance.db")

def get_attendance_db():
    conn = sqlite3.connect(ATTENDANCE_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
print("MAIL USER:", os.getenv("USERNAME"))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

app.config["SECRET_KEY"] = os.getenv("KEY", "dev-secret-key")

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
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

SCHOOL_EMAIL_DOMAIN = "@burnside.school.nz"

# Emails allowed to access the admin dashboard
ADMIN_EMAILS = {
    "22298@burnside.school.nz"
}

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

    # =========================
    # MAIN DATABASE
    # =========================

    conn = get_attendance_db()
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

    conn.commit()
    conn.close()


    # =========================
    # ATTENDANCE DATABASE
    # =========================

    conn = get_attendance_db()
    cursor = conn.cursor()

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

    # Get Google account information
    token = google.authorize_access_token()
    user = token.get("userinfo")

    if not user:
        return render_template(
            "login.html",
            header="login",
            error="Could not get your Google account information."
        )

    email = user.get("email", "").lower().strip()
    name = user.get("name", "").strip()
    picture = user.get("picture")


    # -----------------------------------------
    # ONLY ALLOW BURNSIDE EMAILS
    # -----------------------------------------

    if not email.endswith("@burnside.school.nz"):

        return render_template(
            "login.html",
            header="login",
            error="Please use your Burnside school Google account."
        )


    conn = get_db()
    cursor = conn.cursor()


    # -----------------------------------------
    # CHECK IF USER ALREADY EXISTS
    # -----------------------------------------

    student = cursor.execute("""
        SELECT username, code, email, pfp
        FROM users
        WHERE email = ?
    """, (email,)).fetchone()


    # -----------------------------------------
    # EXISTING USER
    # -----------------------------------------

    if student:

        session.clear()

        session["username"] = student["username"]
        session["code"] = student["code"]
        session["email"] = student["email"]
        session["name"] = name
        session["picture"] = picture
        session["pfp"] = student["pfp"]
        session["signup_complete"] = True

        conn.close()

        print(
            "GOOGLE LOGIN SUCCESS:",
            {
                "username": student["username"],
                "email": student["email"]
            },
            flush=True
        )

        return redirect(url_for("home"))


    # -----------------------------------------
    # NEW USER
    # -----------------------------------------

    # Create a username from their Google name
    username = name.strip()

    if not username:
        username = email.split("@")[0]


    # Make username safe for your database
    username = username.replace(" ", "_")


    # Student code is not supplied by Google.
    # Generate a unique placeholder for now.
    code = secrets.token_hex(3)


    # Generate a random password because
    # Google authentication is now used instead.
    password = generate_password_hash(
        secrets.token_urlsafe(32)
    )


    # Unique verification key
    verify_key = secrets.token_urlsafe(32)


    # Make sure username isn't already taken
    original_username = username
    counter = 1

    while cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,)
    ).fetchone():

        username = f"{original_username}_{counter}"
        counter += 1


    # -----------------------------------------
    # CREATE USER
    # -----------------------------------------

    cursor.execute("""
        INSERT INTO users
        (
            username,
            password,
            code,
            email,
            verify_key,
            is_verified,
            pfp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        username,
        password,
        code,
        email,
        verify_key,
        1,
        picture
    ))


    conn.commit()
    conn.close()


    # -----------------------------------------
    # CREATE SESSION
    # -----------------------------------------

    session["username"] = username
    session["code"] = code
    session["email"] = email
    session["name"] = name
    session["picture"] = picture
    session["pfp"] = picture
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
@app.route("/my-attendance")
@login_required
def my_attendance():
    try:
        username = session.get("username")

        print("MY ATTENDANCE USER:", repr(username), flush=True)
        print("ATTENDANCE DB:", ATTENDANCE_DB_FILE, flush=True)

        conn = get_attendance_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name, time
            FROM attendance
            WHERE name = ?
            ORDER BY time DESC
        """, (username,))

        attendance = cursor.fetchall()

        print(
            "ATTENDANCE FOUND:",
            [dict(row) for row in attendance],
            flush=True
        )

        conn.close()

        return render_template(
            "attendance.html",
            header="My Attendance",
            attendance=attendance
        )

    except Exception as e:
        print("MY ATTENDANCE ERROR:", str(e), flush=True)

        return f"My attendance error: {str(e)}", 500
@app.route("/account")
@login_required
def account():
    username = session.get("username")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, code, email, pfp
        FROM users
        WHERE username = ?
    """, (username,))

    user = cursor.fetchone()
    conn.close()

    return render_template(
        "account.html",
        header="Account",
        user=user
    )

@app.route("/teacher")
@login_required
def teacher():
    return render_template("Teacher.html")


def load_attendance_rows():
    conn = get_attendance_db()
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

    return "All users deleted. Remove this route after testing isaac do NOT foget!."

def save_attendance(name, time):
    conn = get_attendance_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO attendance (name, time)
        VALUES (?, ?)
    """, (name, time))

    conn.commit()
    conn.close()


@app.route("/checkin", methods=["GET", "POST"])
@login_required
def checkin():

    client_ip = get_real_ip()
    allowed, network_name = is_school_ip(client_ip)

    if not allowed:
        return jsonify({
            "message": "Check-in is only allowed from school networks or other verified networks"
        }), 403

    # -----------------------------------------
    # GET - SHOW CHECK-IN PAGE
    # -----------------------------------------

    if request.method == "GET":
        entries = load_attendance_rows()

        return render_template(
            "checkin.html",
            header="checkin",
            entries=entries
        )

    # -----------------------------------------
    # POST - CHECK STUDENT IN
    # -----------------------------------------

    try:

        # We already know who is logged in.
        # Google login stored their username in the session.
        username = session.get("username")

        print(
            "CHECKIN USERNAME FROM SESSION:",
            repr(username),
            flush=True
        )

        if not username:
            return jsonify({
                "message": "You must be logged in."
            }), 401

        # -----------------------------------------
        # FIND USER BY USERNAME
        # -----------------------------------------

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT username, code, email, pfp
            FROM users
            WHERE username = ?
        """, (username,))

        user = cursor.fetchone()

        print(
            "CHECKIN USER FROM DATABASE:",
            dict(user) if user else None,
            flush=True
        )

        conn.close()

        if not user:
            return jsonify({
                "message": "User account not found."
            }), 404

        # -----------------------------------------
        # CHECK IF ALREADY CHECKED IN
        # -----------------------------------------

        name = user["username"]

        attendance = load_attendance()

        if name in attendance:
            return jsonify({
                "message": "Already checked in."
            })

        # -----------------------------------------
        # SAVE CHECK-IN
        # -----------------------------------------

        current_time = datetime.now().strftime("%H:%M")

        save_attendance(
            name,
            current_time
        )

        return jsonify({
            "message": "Checked in successfully."
        })

    except sqlite3.IntegrityError:

        return jsonify({
            "message": "Already checked in."
        }), 400

    except Exception as e:

        print(
            "CHECKIN ERROR:",
            str(e),
            flush=True
        )

        return jsonify({
            "message": f"Error: {str(e)}"
        }), 500


@app.route("/admin/reset-attendance", methods=["POST"])
@login_required
def reset_attendance():

    email = session.get("email", "").lower().strip()

    if email not in ADMIN_EMAILS:
        return jsonify({"message": "Unauthorized"}), 403

    try:
        conn = get_attendance_db()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM attendance")

        conn.commit()
        conn.close()

        return jsonify({
            "message": "Attendance reset successfully."
        })

    except Exception as e:
        return jsonify({
            "message": f"Error: {str(e)}"
        }), 500
    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500

    
@app.route("/admin")
@login_required
def admin():

    email = session.get("email", "").lower().strip()

    # Only approved admin emails can access the dashboard
    if email not in ADMIN_EMAILS:
        return redirect(url_for("home"))

    # -------------------------
    # USERS
    # -------------------------

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, code, email, is_verified, pfp
        FROM users
        ORDER BY username ASC
    """)

    users = cursor.fetchall()
    conn.close()

    # -------------------------
    # ATTENDANCE
    # -------------------------

    attendance_conn = get_attendance_db()
    attendance_cursor = attendance_conn.cursor()
    attendance_cursor.execute("""
        SELECT name, time
        FROM attendance
        ORDER BY time DESC
    """)

    attendance = attendance_cursor.fetchall()
    attendance_conn.close()

    return render_template(
        "admin.html",
        header="admin",
        users=users,
        attendance=attendance,
        admin_name=ADMIN_EMAILS[email]
    )


# Initialise database when Flask/Gunicorn starts
init_db()


if __name__ == "__main__":
    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )