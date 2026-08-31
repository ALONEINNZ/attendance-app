from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session
)

import os
import ipaddress
import secrets
import psycopg2

from psycopg2.extras import RealDictCursor
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from flask_mail import Mail
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from zoneinfo import ZoneInfo


# =========================================================
# BASE DIRECTORY
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv(
    os.path.join(BASE_DIR, ".env"),
    override=True
)


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=2
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
# POSTGRESQL DATABASE
# =========================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


def get_db():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL environment variable is not set."
        )

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =========================================================
# SCHOOL NETWORKS
# =========================================================

SCHOOL_NETWORKS = {

    "Burnside WiFi": [

        "202.150.123.193/32",

        "122.63.129.201/32",

        "202.36.179.108/32",

        "122.58.103.94/32"

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

    cf_ip = request.headers.get(
        "CF-Connecting-IP"
    )

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

        "scope":
            "openid email profile"

    },

)


# =========================================================
# SETTINGS
# =========================================================

SCHOOL_EMAIL_DOMAIN = (
    "@burnside.school.nz"
)


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

    conn = get_db()

    cursor = conn.cursor()


    # =====================================================
    # USERS
    # =====================================================

    cursor.execute("""

        CREATE TABLE IF NOT EXISTS users (

            id SERIAL PRIMARY KEY,

            username TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL,

            code TEXT UNIQUE NOT NULL,

            email TEXT UNIQUE NOT NULL,

            verify_key TEXT UNIQUE NOT NULL,

            is_verified INTEGER DEFAULT 0,

            pfp TEXT DEFAULT NULL

        )

    """)


    # =====================================================
    # STUDY TOPICS
    #
    # One study topic can belong to many students.
    # One student can have many study topics.
    # =====================================================

    cursor.execute("""

        CREATE TABLE IF NOT EXISTS study_topics (

            id SERIAL PRIMARY KEY,

            name TEXT NOT NULL,

            subject TEXT NOT NULL,

            description TEXT

        )

    """)


    # =====================================================
    # MANY-TO-MANY JUNCTION TABLE
    # =====================================================

    cursor.execute("""

        CREATE TABLE IF NOT EXISTS student_study_topics (

            student_id INTEGER NOT NULL,

            topic_id INTEGER NOT NULL,

            PRIMARY KEY (
                student_id,
                topic_id
            ),

            FOREIGN KEY (
                student_id
            )
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (
                topic_id
            )
            REFERENCES study_topics(id)
            ON DELETE CASCADE

        )

    """)


    # =====================================================
    # ATTENDANCE
    # =====================================================

    cursor.execute("""

        CREATE TABLE IF NOT EXISTS attendance (

            id SERIAL PRIMARY KEY,

            student_id INTEGER NOT NULL,

            time TEXT NOT NULL,

            study_activity TEXT,

            FOREIGN KEY (
                student_id
            )
            REFERENCES users(id)
            ON DELETE CASCADE

        )

    """)


    conn.commit()

    cursor.close()

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

        return f(
            *args,
            **kwargs
        )

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

@app.route(
    "/auth/google/callback"
)
def google_callback():

    try:

        # -------------------------------------------------
        # GET GOOGLE ACCOUNT
        # -------------------------------------------------

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


        # -------------------------------------------------
        # BURNSIDE EMAIL ONLY
        # -------------------------------------------------

        if not email.endswith(
            SCHOOL_EMAIL_DOMAIN
        ):

            return render_template(

                "login.html",

                header="login",

                error=
                    "Please use your Burnside school Google account."

            )


        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = get_db()

        cursor = conn.cursor()


        # -------------------------------------------------
        # CHECK EXISTING USER
        # -------------------------------------------------

        cursor.execute("""

            SELECT

                id,

                username,

                code,

                email,

                pfp

            FROM users

            WHERE email = %s

        """, (

            email,

        ))


        student = cursor.fetchone()


        # =================================================
        # EXISTING USER
        # =================================================

        if student:

            session.clear()


            session["user_id"] = student["id"]

            session["username"] = student["username"]

            session["code"] = student["code"]

            session["email"] = student["email"]

            session["name"] = name

            session["picture"] = picture

            session["pfp"] = student["pfp"]

            session["signup_complete"] = True


            session["is_admin"] = (

                email in ADMIN_EMAILS

            )


            cursor.close()

            conn.close()


            print(

                "GOOGLE LOGIN SUCCESS:",

                {

                    "user_id":
                        student["id"],

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


        # =================================================
        # NEW USER
        # =================================================

        username = name.strip()


        if not username:

            username = email.split(
                "@"
            )[0]


        username = username.replace(
            " ",
            "_"
        )


        original_username = username

        counter = 1


        # -------------------------------------------------
        # UNIQUE USERNAME
        # -------------------------------------------------

        while True:

            cursor.execute("""

                SELECT id

                FROM users

                WHERE username = %s

            """, (

                username,

            ))


            if not cursor.fetchone():

                break


            username = (

                f"{original_username}_{counter}"

            )

            counter += 1


        # -------------------------------------------------
        # GENERATE CODE
        # -------------------------------------------------

        code = secrets.token_hex(3)


        # -------------------------------------------------
        # PASSWORD
        # -------------------------------------------------

        password = generate_password_hash(

            secrets.token_urlsafe(32)

        )


        # -------------------------------------------------
        # VERIFICATION KEY
        # -------------------------------------------------

        verify_key = secrets.token_urlsafe(
            32
        )


        # -------------------------------------------------
        # CREATE USER
        # -------------------------------------------------

        cursor.execute("""

            INSERT INTO users (

                username,

                password,

                code,

                email,

                verify_key,

                is_verified,

                pfp

            )

            VALUES (

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s

            )

            RETURNING id

        """, (

            username,

            password,

            code,

            email,

            verify_key,

            1,

            picture

        ))


        new_user = cursor.fetchone()

        user_id = new_user["id"]


        conn.commit()


        cursor.close()

        conn.close()


        # -------------------------------------------------
        # CREATE SESSION
        # -------------------------------------------------

        session["user_id"] = user_id

        session["username"] = username

        session["code"] = code

        session["email"] = email

        session["name"] = name

        session["picture"] = picture

        session["pfp"] = picture

        session["signup_complete"] = True

        session["is_admin"] = (

            email in ADMIN_EMAILS

        )


        print(

            "NEW USER CREATED:",

            {

                "user_id": user_id,

                "username": username,

                "email": email

            },

            flush=True

        )


        return redirect(
            url_for("home")
        )


    except Exception as e:

        print(

            "GOOGLE LOGIN ERROR:",

            repr(e),

            flush=True

        )


        return (

            "Login error: "

            + str(e),

            500

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
# GET CURRENT USER
# =========================================================

def get_current_user():

    user_id = session.get(
        "user_id"
    )


    username = session.get(
        "username"
    )


    conn = get_db()

    cursor = conn.cursor()


    if user_id:

        cursor.execute("""

            SELECT *

            FROM users

            WHERE id = %s

        """, (

            user_id,

        ))

    elif username:

        cursor.execute("""

            SELECT *

            FROM users

            WHERE username = %s

        """, (

            username,

        ))

    else:

        cursor.close()

        conn.close()

        return None


    user = cursor.fetchone()


    cursor.close()

    conn.close()


    return user


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


        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT

                attendance.id,

                users.username AS name,

                attendance.time,

                attendance.study_activity

            FROM attendance

            JOIN users

                ON attendance.student_id = users.id

            WHERE users.username = %s

            ORDER BY attendance.time DESC

        """, (

            username,

        ))


        attendance = cursor.fetchall()


        cursor.close()

        conn.close()


        print(

            "ATTENDANCE FOUND:",

            attendance,

            flush=True

        )


        return render_template(

            "attendance.html",

            header="My Attendance",

            attendance=attendance

        )


    except Exception as e:

        print(

            "MY ATTENDANCE ERROR:",

            repr(e),

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

    try:

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

            WHERE username = %s

        """, (

            username,

        ))


        user = cursor.fetchone()


        cursor.close()

        conn.close()


        return render_template(

            "account.html",

            header="Account",

            user=user

        )


    except Exception as e:

        print(

            "ACCOUNT ERROR:",

            repr(e),

            flush=True

        )


        return (

            f"Account error: {str(e)}",

            500

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
# LOAD ATTENDANCE ROWS
# =========================================================

def load_attendance_rows():

    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""

        SELECT

            attendance.id,

            users.username AS name,

            attendance.time,

            attendance.study_activity

        FROM attendance

        JOIN users

            ON attendance.student_id = users.id

        ORDER BY

            attendance.time ASC,

            users.username ASC

    """)


    rows = cursor.fetchall()


    cursor.close()

    conn.close()


    return [

        {

            "id":
                row["id"],

            "name":
                row["name"],

            "time":
                row["time"],

            "study_activity":
                row["study_activity"]

        }

        for row in rows

    ]


# =========================================================
# LOAD ATTENDANCE
# =========================================================

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


    try:

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute(
            "DELETE FROM users"
        )


        conn.commit()


        cursor.close()

        conn.close()


        session.clear()


        return (
            "All users deleted."
        )


    except Exception as e:

        print(

            "RESET USERS ERROR:",

            repr(e),

            flush=True

        )


        return (

            f"Error: {str(e)}",

            500

        )


# =========================================================
# SAVE ATTENDANCE
# =========================================================

def save_attendance(

    student_id,

    time,

    study_activity

):

    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""

        INSERT INTO attendance (

            student_id,

            time,

            study_activity

        )

        VALUES (

            %s,

            %s,

            %s

        )

    """, (

        student_id,

        time,

        study_activity

    ))


    conn.commit()


    cursor.close()

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

    # =====================================================
    # SCHOOL NETWORK CHECK
    # =====================================================

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
        # STUDY ACTIVITY
        # -------------------------------------------------

        study_activity = request.form.get(

            "study_activity",

            ""

        ).strip()


        # =================================================
        # FIND USER
        # =================================================

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT

                id,

                username,

                code,

                email,

                pfp

            FROM users

            WHERE username = %s

        """, (

            username,

        ))


        user = cursor.fetchone()


        # -------------------------------------------------
        # USER NOT FOUND
        # -------------------------------------------------

        if not user:

            cursor.close()

            conn.close()


            print(

                "CHECKIN USER FROM DATABASE: None",

                flush=True

            )


            return jsonify({

                "message":
                    "User account not found."

            }), 404


        print(

            "CHECKIN USER FROM DATABASE:",

            dict(user),

            flush=True

        )


        student_id = user["id"]


        # =================================================
        # CHECK EXISTING ATTENDANCE
        # =================================================

        cursor.execute("""

            SELECT

                id,

                student_id,

                time,

                study_activity

            FROM attendance

            WHERE student_id = %s

        """, (

            student_id,

        ))


        existing_attendance = (
            cursor.fetchone()
        )


        cursor.close()

        conn.close()


        print(

            "EXISTING ATTENDANCE:",

            dict(existing_attendance)

            if existing_attendance

            else None,

            flush=True

        )


        # -------------------------------------------------
        # ALREADY CHECKED IN
        # -------------------------------------------------

        if existing_attendance:

            return jsonify({

                "message":
                    "Already checked in."

            }), 400


        # =================================================
        # SAVE
        # =================================================

        current_time = datetime.now(

            ZoneInfo(
                "Pacific/Auckland"
            )

        ).strftime(
            "%H:%M"
        )


        save_attendance(

            student_id,

            current_time,

            study_activity

        )


        print(

            "CHECK-IN SUCCESS:",

            username,

            current_time,

            study_activity,

            flush=True

        )


        return jsonify({

            "message":
                "Checked in successfully."

        })


    except psycopg2.IntegrityError as e:

        print(

            "CHECKIN DATABASE ERROR:",

            repr(e),

            flush=True

        )


        return jsonify({

            "message":
                "Already checked in."

        }), 400


    except Exception as e:

        print(

            "CHECKIN ERROR:",

            repr(e),

            flush=True

        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# ADMIN RESET ATTENDANCE
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

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute(
            "DELETE FROM attendance"
        )


        conn.commit()


        cursor.close()

        conn.close()


        return jsonify({

            "message":
                "Attendance reset successfully."

        })


    except Exception as e:

        print(

            "RESET ATTENDANCE ERROR:",

            repr(e),

            flush=True

        )


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
        # ADMIN CHECK
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
        # USERS
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


        cursor.close()

        conn.close()


        print(

            "USERS LOADED:",

            len(users),

            flush=True

        )


        # =================================================
        # ATTENDANCE
        # =================================================

        attendance_conn = get_db()

        attendance_cursor = (
            attendance_conn.cursor()
        )


        attendance_cursor.execute("""

            SELECT

                attendance.id,

                users.username AS name,

                attendance.time,

                attendance.study_activity

            FROM attendance

            JOIN users

                ON attendance.student_id = users.id

            ORDER BY attendance.time DESC

        """)


        attendance = (
            attendance_cursor.fetchall()
        )


        attendance_cursor.close()

        attendance_conn.close()


        print(

            "ATTENDANCE LOADED:",

            len(attendance),

            flush=True

        )


        # =================================================
        # STUDY TOPICS
        # =================================================

        topics_conn = get_db()

        topics_cursor = (
            topics_conn.cursor()
        )


        topics_cursor.execute("""

            SELECT

                id,

                name,

                subject,

                description

            FROM study_topics

            ORDER BY subject ASC, name ASC

        """)


        study_topics = (
            topics_cursor.fetchall()
        )


        topics_cursor.close()

        topics_conn.close()


        # =================================================
        # STUDENT / STUDY RELATIONSHIPS
        # =================================================

        relation_conn = get_db()

        relation_cursor = (
            relation_conn.cursor()
        )


        relation_cursor.execute("""

            SELECT

                student_study_topics.student_id,

                student_study_topics.topic_id,

                users.username,

                study_topics.name AS topic_name,

                study_topics.subject

            FROM student_study_topics

            JOIN users

                ON student_study_topics.student_id = users.id

            JOIN study_topics

                ON student_study_topics.topic_id = study_topics.id

            ORDER BY

                users.username ASC,

                study_topics.name ASC

        """)


        student_study_topics = (
            relation_cursor.fetchall()
        )


        relation_cursor.close()

        relation_conn.close()


        # =================================================
        # ADMIN PAGE
        # =================================================

        return render_template(

            "admin.html",

            header="admin",

            users=users,

            attendance=attendance,

            study_topics=study_topics,

            student_study_topics=
                student_study_topics,

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
# STUDY TOPICS API
# =========================================================

@app.route(
    "/study-topics",
    methods=["GET"]
)
@login_required
def get_study_topics():

    try:

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT

                id,

                name,

                subject,

                description

            FROM study_topics

            ORDER BY subject ASC, name ASC

        """)


        topics = cursor.fetchall()


        cursor.close()

        conn.close()


        return jsonify({

            "topics": topics

        })


    except Exception as e:

        print(

            "STUDY TOPICS ERROR:",

            repr(e),

            flush=True

        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# ADD STUDY TOPIC
# =========================================================

@app.route(
    "/study-topics",
    methods=["POST"]
)
@login_required
def add_study_topic():

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

        name = request.form.get(
            "name",
            ""
        ).strip()


        subject = request.form.get(
            "subject",
            ""
        ).strip()


        description = request.form.get(
            "description",
            ""
        ).strip()


        if not name or not subject:

            return jsonify({

                "message":
                    "Name and subject are required."

            }), 400


        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            INSERT INTO study_topics (

                name,

                subject,

                description

            )

            VALUES (

                %s,

                %s,

                %s

            )

            RETURNING id

        """, (

            name,

            subject,

            description

        ))


        topic = cursor.fetchone()


        conn.commit()


        cursor.close()

        conn.close()


        return jsonify({

            "message":
                "Study topic created.",

            "id":
                topic["id"]

        })


    except Exception as e:

        print(

            "ADD STUDY TOPIC ERROR:",

            repr(e),

            flush=True

        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# ASSIGN STUDY TOPIC TO STUDENT
# =========================================================

@app.route(
    "/study-topics/assign",
    methods=["POST"]
)
@login_required
def assign_study_topic():

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

        student_id = request.form.get(
            "student_id"
        )

        topic_id = request.form.get(
            "topic_id"
        )


        if not student_id or not topic_id:

            return jsonify({

                "message":
                    "Student and study topic are required."

            }), 400


        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            INSERT INTO student_study_topics (

                student_id,

                topic_id

            )

            VALUES (

                %s,

                %s

            )

            ON CONFLICT (

                student_id,

                topic_id

            )

            DO NOTHING

        """, (

            student_id,

            topic_id

        ))


        conn.commit()


        cursor.close()

        conn.close()


        return jsonify({

            "message":
                "Study topic assigned successfully."

        })


    except Exception as e:

        print(

            "ASSIGN STUDY TOPIC ERROR:",

            repr(e),

            flush=True

        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# INITIALISE DATABASE
# =========================================================

try:

    init_db()

    print(

        "POSTGRESQL DATABASE INITIALISED",

        flush=True

    )

except Exception as e:

    print(

        "DATABASE INITIALISATION ERROR:",

        repr(e),

        flush=True

    )


# =========================================================
# RUN LOCALLY
# =========================================================

if __name__ == "__main__":

    app.run(

        debug=True,

        host="0.0.0.0",

        port=5000

    )

