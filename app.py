from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import sqlite3
import os
import ipaddress
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from flask_mail import Mail
import secrets
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth


# =========================================================
# SCHOOL NETWORKS
# =========================================================

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

    forwarded = request.headers.get(
        "X-Forwarded-For",
        ""
    )

    direct_ip = request.remote_addr

    return cf_ip or (
        forwarded.split(",")[0].strip()
        if forwarded
        else direct_ip
    )


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=2
)


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


DB_FILE = os.path.join(
    BASE_DIR,
    "main.db"
)


ATTENDANCE_DB_FILE = os.path.join(
    BASE_DIR,
    "attendance.db"
)


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect(DB_FILE)

    conn.row_factory = sqlite3.Row

    return conn


def get_attendance_db():

    conn = sqlite3.connect(
        ATTENDANCE_DB_FILE
    )

    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv(
    os.path.join(BASE_DIR, ".env"),
    override=True
)


app.config["SECRET_KEY"] = os.getenv(
    "KEY",
    "dev-secret-key"
)


app.config.update(

    SESSION_COOKIE_SECURE=True,

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

)


# =========================================================
# UPLOADS
# =========================================================

app.config["UPLOAD_FOLDER"] = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)


os.makedirs(
    app.config["UPLOAD_FOLDER"],
    exist_ok=True
)


# =========================================================
# MAIL
# =========================================================

app.config.update(

    MAIL_SERVER="smtp.gmail.com",

    MAIL_PORT=587,

    MAIL_USERNAME=os.getenv("USERNAME"),

    MAIL_PASSWORD=os.getenv("PASSWORD"),

    MAIL_USE_TLS=True,

    MAIL_USE_SSL=False,

)


mail = Mail(app)


# =========================================================
# GOOGLE OAUTH
# =========================================================

app.config["GOOGLE_CLIENT_ID"] = os.getenv(
    "GOOGLE_CLIENT_ID"
)

app.config["GOOGLE_CLIENT_SECRET"] = os.getenv(
    "GOOGLE_CLIENT_SECRET"
)


oauth = OAuth(app)


google = oauth.register(

    name="google",

    client_id=app.config[
        "GOOGLE_CLIENT_ID"
    ],

    client_secret=app.config[
        "GOOGLE_CLIENT_SECRET"
    ],

    server_metadata_url=
        "https://accounts.google.com/.well-known/openid-configuration",

    client_kwargs={
        "scope": "openid email profile"
    },

)


# =========================================================
# SETTINGS
# =========================================================

SCHOOL_EMAIL_DOMAIN = "@burnside.school.nz"


# =========================================================
# ADMIN EMAILS
# =========================================================

ADMIN_EMAILS = {

    "22298@burnside.school.nz"

}


# =========================================================
# IP LOGGING
# =========================================================

@app.before_request
def log_visitor_ip():

    cf_ip = request.headers.get(
        "CF-Connecting-IP"
    )

    forwarded = request.headers.get(
        "X-Forwarded-For",
        ""
    )

    direct_ip = request.remote_addr


    real_ip = cf_ip or (
        forwarded.split(",")[0].strip()
        if forwarded
        else direct_ip
    )


    print(
        f"[IP LOG] "
        f"path={request.path} "
        f"cf_connecting_ip={cf_ip!r} "
        f"remote_addr={direct_ip} "
        f"x-forwarded-for={forwarded!r} "
        f"resolved={real_ip}",
        flush=True
    )


# =========================================================
# DATABASE INITIALISATION
# =========================================================

def init_db():

    # =====================================================
    # MAIN DATABASE
    # =====================================================

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


    conn.commit()

    conn.close()


    # =====================================================
    # ATTENDANCE DATABASE
    # =====================================================

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


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(f):

    @wraps(f)
    def decorated(*args, **kwargs):

        if "username" not in session:

            return redirect(
                url_for("login")
            )

        return f(*args, **kwargs)

    return decorated


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "Home.html"
    )


# =========================================================
# GOOGLE CALLBACK
# =========================================================

@app.route("/auth/google/callback")
def google_callback():

    # -----------------------------------------------------
    # GET GOOGLE ACCOUNT INFORMATION
    # -----------------------------------------------------

    token = google.authorize_access_token()

    user = token.get("userinfo")


    if not user:

        return render_template(

            "login.html",

            header="login",

            error=
                "Could not get your Google account information."

        )


    email = user.get(
        "email",
        ""
    ).lower().strip()


    name = user.get(
        "name",
        ""
    ).strip()


    picture = user.get(
        "picture"
    )


    # -----------------------------------------------------
    # ONLY ALLOW BURNSIDE EMAILS
    # -----------------------------------------------------

    if not email.endswith(
        SCHOOL_EMAIL_DOMAIN
    ):

        return render_template(

            "login.html",

            header="login",

            error=
                "Please use your Burnside school Google account."

        )


    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    conn = get_db()

    cursor = conn.cursor()


    # -----------------------------------------------------
    # CHECK EXISTING USER
    # -----------------------------------------------------

    student = cursor.execute("""

        SELECT
            username,
            code,
            email,
            pfp

        FROM users

        WHERE email = ?

    """, (
        email,
    )).fetchone()


    # =====================================================
    # EXISTING USER
    # =====================================================

    if student:

        session.clear()


        session["username"] = student["username"]

        session["code"] = student["code"]

        session["email"] = student["email"]

        session["name"] = name

        session["picture"] = picture

        session["pfp"] = student["pfp"]

        session["signup_complete"] = True


        # -------------------------------------------------
        # ADMIN STATUS
        # -------------------------------------------------

        session["is_admin"] = (
            email in ADMIN_EMAILS
        )


        conn.close()


        print(
            "GOOGLE LOGIN SUCCESS:",
            {
                "username":
                    student["username"],

                "email":
                    student["email"],

                "is_admin":
                    session["is_admin"],
            },
            flush=True
        )


        return redirect(
            url_for("home")
        )


    # =====================================================
    # NEW USER
    # =====================================================

    username = name.strip()


    if not username:

        username = email.split("@")[0]


    username = username.replace(
        " ",
        "_"
    )


    # -----------------------------------------------------
    # GENERATE STUDENT CODE
    # -----------------------------------------------------

    code = secrets.token_hex(3)


    # -----------------------------------------------------
    # RANDOM PASSWORD
    # -----------------------------------------------------

    password = generate_password_hash(
        secrets.token_urlsafe(32)
    )


    # -----------------------------------------------------
    # VERIFICATION KEY
    # -----------------------------------------------------

    verify_key = secrets.token_urlsafe(32)


    # -----------------------------------------------------
    # UNIQUE USERNAME
    # -----------------------------------------------------

    original_username = username

    counter = 1


    while cursor.execute(

        """
        SELECT id
        FROM users
        WHERE username = ?
        """,

        (
            username,
        )

    ).fetchone():

        username = (
            f"{original_username}_{counter}"
        )

        counter += 1


    # -----------------------------------------------------
    # CREATE USER
    # -----------------------------------------------------

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


    # =====================================================
    # CREATE SESSION
    # =====================================================

    session["username"] = username

    session["code"] = code

    session["email"] = email

    session["name"] = name

    session["picture"] = picture

    session["pfp"] = picture

    session["signup_complete"] = True


    # -----------------------------------------------------
    # ADMIN STATUS
    # -----------------------------------------------------

    session["is_admin"] = (
        email in ADMIN_EMAILS
    )


    return redirect(
        url_for("home")
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    redirect_uri = url_for(
        "google_callback",
        _external=True
    )


    print(
        "GOOGLE REDIRECT URI:",
        redirect_uri
    )


    return google.authorize_redirect(
        redirect_uri
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# =========================================================
# MY ATTENDANCE
# =========================================================

@app.route("/my-attendance")
@login_required
def my_attendance():

    try:

        username = session.get(
            "username"
        )


        print(
            "MY ATTENDANCE USER:",
            repr(username),
            flush=True
        )


        print(
            "ATTENDANCE DB:",
            ATTENDANCE_DB_FILE,
            flush=True
        )


        conn = get_attendance_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT
                name,
                time

            FROM attendance

            WHERE name = ?

            ORDER BY time DESC

        """, (
            username,
        ))


        attendance = cursor.fetchall()


        print(
            "ATTENDANCE FOUND:",
            [
                dict(row)
                for row in attendance
            ],
            flush=True
        )


        conn.close()


        return render_template(

            "attendance.html",

            header="My Attendance",

            attendance=attendance

        )


    except Exception as e:

        print(
            "MY ATTENDANCE ERROR:",
            str(e),
            flush=True
        )


        return (
            f"My attendance error: {str(e)}",
            500
        )


# =========================================================
# ACCOUNT
# =========================================================

@app.route("/account")
@login_required
def account():

    username = session.get(
        "username"
    )


    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""

        SELECT
            username,
            code,
            email,
            pfp

        FROM users

        WHERE username = ?

    """, (
        username,
    ))


    user = cursor.fetchone()


    conn.close()


    return render_template(

        "account.html",

        header="Account",

        user=user

    )


# =========================================================
# TEACHER
# =========================================================

@app.route("/teacher")
@login_required
def teacher():

    return render_template(
        "Teacher.html"
    )


# =========================================================
# LOAD ATTENDANCE
# =========================================================

def load_attendance_rows():

    conn = get_attendance_db()

    cursor = conn.cursor()


    cursor.execute("""

        SELECT
            name,
            time

        FROM attendance

        ORDER BY
            time ASC,
            name ASC

    """)


    rows = cursor.fetchall()


    conn.close()


    return [

        {
            "name": row["name"],
            "time": row["time"]
        }

        for row in rows

    ]


def load_attendance():

    rows = load_attendance_rows()


    return {
        row["name"]:
        row["time"]

        for row in rows
    }


# =========================================================
# RESET USERS
# =========================================================

@app.route("/reset-users")
@login_required
def reset_users():

    email = session.get(
        "email",
        ""
    ).lower().strip()


    if email not in ADMIN_EMAILS:

        return (
            "Unauthorized",
            403
        )


    conn = get_db()

    cursor = conn.cursor()


    cursor.execute(
        "DELETE FROM users"
    )


    conn.commit()

    conn.close()


    return "All users deleted."


# =========================================================
# SAVE ATTENDANCE
# =========================================================

def save_attendance(
    name,
    time
):

    conn = get_attendance_db()

    cursor = conn.cursor()


    cursor.execute("""

        INSERT INTO attendance
        (
            name,
            time
        )

        VALUES (?, ?)

    """, (
        name,
        time
    ))


    conn.commit()

    conn.close()


# =========================================================
# CHECK IN
# =========================================================

@app.route(
    "/checkin",
    methods=["GET", "POST"]
)
@login_required
def checkin():

    client_ip = get_real_ip()


    allowed, network_name = is_school_ip(
        client_ip
    )


    if not allowed:

        return jsonify({

            "message":
                "Check-in is only allowed from school networks or other verified networks"

        }), 403


    # =====================================================
    # GET
    # =====================================================

    if request.method == "GET":

        entries = load_attendance_rows()


        return render_template(

            "checkin.html",

            header="checkin",

            entries=entries

        )


    # =====================================================
    # POST
    # =====================================================

    try:

        username = session.get(
            "username"
        )


        print(
            "CHECKIN USERNAME FROM SESSION:",
            repr(username),
            flush=True
        )


        if not username:

            return jsonify({

                "message":
                    "You must be logged in."

            }), 401


        # -------------------------------------------------
        # FIND USER
        # -------------------------------------------------

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT
                username,
                code,
                email,
                pfp

            FROM users

            WHERE username = ?

        """, (
            username,
        ))


        user = cursor.fetchone()


        print(

            "CHECKIN USER FROM DATABASE:",

            dict(user)
            if user
            else None,

            flush=True

        )


        conn.close()


        if not user:

            return jsonify({

                "message":
                    "User account not found."

            }), 404


        # -------------------------------------------------
        # CHECK EXISTING ATTENDANCE
        # -------------------------------------------------

        name = user["username"]


        attendance = load_attendance()


        if name in attendance:

            return jsonify({

                "message":
                    "Already checked in."

            })


        # -------------------------------------------------
        # SAVE
        # -------------------------------------------------

        current_time = datetime.now().strftime(
            "%H:%M"
        )


        save_attendance(

            name,

            current_time

        )


        return jsonify({

            "message":
                "Checked in successfully."

        })


    except sqlite3.IntegrityError:

        return jsonify({

            "message":
                "Already checked in."

        }), 400


    except Exception as e:

        print(

            "CHECKIN ERROR:",

            str(e),

            flush=True

        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# RESET ATTENDANCE
# =========================================================

@app.route(
    "/admin/reset-attendance",
    methods=["POST"]
)
@login_required
def reset_attendance():

    email = session.get(
        "email",
        ""
    ).lower().strip()


    if email not in ADMIN_EMAILS:

        return jsonify({

            "message":
                "Unauthorized"

        }), 403


    try:

        conn = get_attendance_db()

        cursor = conn.cursor()


        cursor.execute(
            "DELETE FROM attendance"
        )


        conn.commit()

        conn.close()


        return jsonify({

            "message":
                "Attendance reset successfully."

        })


    except Exception as e:

        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@login_required
def admin():

    try:

        # =================================================
        # CHECK ADMIN EMAIL
        # =================================================

        email = session.get(
            "email",
            ""
        ).lower().strip()


        print(
            "=================================",
            flush=True
        )


        print(
            "ADMIN PAGE REQUEST",
            flush=True
        )


        print(
            "SESSION:",
            dict(session),
            flush=True
        )


        print(
            "ADMIN EMAIL:",
            repr(email),
            flush=True
        )


        print(
            "=================================",
            flush=True
        )


        # -------------------------------------------------
        # SERVER-SIDE ADMIN CHECK
        # -------------------------------------------------

        if email not in ADMIN_EMAILS:

            print(
                "ADMIN ACCESS DENIED",
                flush=True
            )


            return redirect(
                url_for("home")
            )


        print(
            "ADMIN ACCESS GRANTED",
            flush=True
        )


        # =================================================
        # GET USERS
        # =================================================

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT
                username,
                code,
                email,
                is_verified,
                pfp

            FROM users

            ORDER BY username ASC

        """)


        users = cursor.fetchall()


        conn.close()


        print(
            "USERS LOADED:",
            len(users),
            flush=True
        )


        # =================================================
        # GET ATTENDANCE
        # =================================================

        attendance_conn = get_attendance_db()

        attendance_cursor = attendance_conn.cursor()


        attendance_cursor.execute("""

            SELECT
                name,
                time

            FROM attendance

            ORDER BY time DESC

        """)


        attendance = attendance_cursor.fetchall()


        attendance_conn.close()


        print(
            "ATTENDANCE LOADED:",
            len(attendance),
            flush=True
        )


        # =================================================
        # LOAD ADMIN PAGE
        # =================================================

        return render_template(

            "admin.html",

            header="admin",

            users=users,

            attendance=attendance,

            admin_name=email

        )


    except Exception as e:

        print(
            "=================================",
            flush=True
        )


        print(
            "ADMIN PAGE ERROR:",
            repr(e),
            flush=True
        )


        print(
            "=================================",
            flush=True
        )


        return f"""

        <h1>Admin Error</h1>

        <pre>{str(e)}</pre>

        """, 500


# =========================================================
# INITIALISE DATABASE
# =========================================================

init_db()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(

        debug=True,

        host="0.0.0.0",

        port=5000

    )
