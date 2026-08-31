from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session
)

import psycopg2
from psycopg2.extras import RealDictCursor

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
from zoneinfo import ZoneInfo


# =========================================================
# ENVIRONMENT
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

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


# =========================================================
# SECRET KEY / SESSION
# =========================================================

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
# DATABASE
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL")


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
        "scope": "openid email profile"
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

    conn = None

    try:

        conn = get_db()

        cursor = conn.cursor()


        # =================================================
        # USERS
        # =================================================

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


        # =================================================
        # STUDY TOPICS
        # =================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_topics (

                id SERIAL PRIMARY KEY,

                name TEXT NOT NULL,

                subject TEXT NOT NULL,

                description TEXT

            )
        """)


        # =================================================
        # MANY-TO-MANY:
        #
        # USERS <-> STUDY TOPICS
        #
        # One student can have many topics.
        # One topic can belong to many students.
        # =================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_study_topics (

                student_id INTEGER NOT NULL,

                topic_id INTEGER NOT NULL,

                PRIMARY KEY (
                    student_id,
                    topic_id
                ),

                FOREIGN KEY (student_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (topic_id)
                    REFERENCES study_topics(id)
                    ON DELETE CASCADE

            )
        """)


        # =================================================
        # ATTENDANCE
        # =================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (

                id SERIAL PRIMARY KEY,

                student_id INTEGER NOT NULL,

                time TEXT NOT NULL,

                study_activity TEXT,

                FOREIGN KEY (student_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE

            )
        """)


        conn.commit()

        cursor.close()

        print(
            "POSTGRESQL DATABASE INITIALISED",
            flush=True
        )


    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "DATABASE INITIALISATION ERROR:",
            repr(e),
            flush=True
        )

        raise


    finally:

        if conn:
            conn.close()


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(f):

    @wraps(f)
    def decorated(*args, **kwargs):

        if "user_id" not in session:

            return redirect(
                url_for("login")
            )

        return f(*args, **kwargs)

    return decorated


# =========================================================
# GET CURRENT USER
# =========================================================

def get_current_user():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return None


    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            username,
            code,
            email,
            verify_key,
            is_verified,
            pfp

        FROM users

        WHERE id = %s
    """, (
        user_id,
    ))


    user = cursor.fetchone()

    cursor.close()

    conn.close()


    return user


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "Home.html"
    )


# =========================================================
# GOOGLE LOGIN CALLBACK
# =========================================================

@app.route(
    "/auth/google/callback"
)
def google_callback():

    try:

        # =================================================
        # GET GOOGLE ACCOUNT
        # =================================================

        token = google.authorize_access_token()

        user_info = token.get(
            "userinfo"
        )


        if not user_info:

            return render_template(

                "login.html",

                header="login",

                error=
                    "Could not get your Google account information."

            )


        email = user_info.get(
            "email",
            ""
        ).lower().strip()


        name = user_info.get(
            "name",
            ""
        ).strip()


        picture = user_info.get(
            "picture"
        )


        # =================================================
        # CHECK BURNSIDE EMAIL
        # =================================================

        if not email.endswith(
            SCHOOL_EMAIL_DOMAIN
        ):

            return render_template(

                "login.html",

                header="login",

                error=
                    "Please use your Burnside school Google account."

            )


        conn = get_db()

        cursor = conn.cursor()


        # =================================================
        # FIND EXISTING USER
        # =================================================

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


            session["user_id"] = (
                student["id"]
            )

            session["username"] = (
                student["username"]
            )

            session["code"] = (
                student["code"]
            )

            session["email"] = (
                student["email"]
            )

            session["name"] = name

            session["picture"] = picture

            session["pfp"] = (
                student["pfp"]
            )

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
                        session["is_admin"]
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

            username = email.split("@")[0]


        username = username.replace(
            " ",
            "_"
        )


        # =================================================
        # UNIQUE USERNAME
        # =================================================

        original_username = username

        counter = 1


        while True:

            cursor.execute("""
                SELECT id

                FROM users

                WHERE username = %s
            """, (
                username,
            ))


            existing = cursor.fetchone()


            if not existing:

                break


            username = (
                f"{original_username}_{counter}"
            )

            counter += 1


        # =================================================
        # GENERATE ACCOUNT DATA
        # =================================================

        code = secrets.token_hex(3)


        password = generate_password_hash(
            secrets.token_urlsafe(32)
        )


        verify_key = secrets.token_urlsafe(32)


        # =================================================
        # INSERT USER
        # =================================================

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


        # =================================================
        # CREATE SESSION
        # =================================================

        session.clear()


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

        return render_template(

            "login.html",

            header="login",

            error=
                "There was a problem signing you in."

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
        redirect_uri,
        flush=True
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

        user_id = session.get(
            "user_id"
        )


        print(
            "MY ATTENDANCE USER ID:",
            repr(user_id),
            flush=True
        )


        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                attendance.id,
                attendance.time,
                attendance.study_activity

            FROM attendance

            WHERE attendance.student_id = %s

            ORDER BY attendance.time DESC
        """, (
            user_id,
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

        user_id = session.get(
            "user_id"
        )


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

            WHERE id = %s
        """, (
            user_id,
        ))


        user = cursor.fetchone()


        cursor.close()

        conn.close()


        if not user:

            session.clear()

            return redirect(
                url_for("login")
            )


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
# STUDY TOPICS
# =========================================================

def load_study_topics():

    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            name,
            subject,
            description

        FROM study_topics

        ORDER BY
            subject ASC,
            name ASC
    """)


    topics = cursor.fetchall()


    cursor.close()

    conn.close()


    return topics


# =========================================================
# GET CURRENT USER'S STUDY TOPICS
# =========================================================

def load_user_study_topics(
    user_id
):

    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            study_topics.id,
            study_topics.name,
            study_topics.subject,
            study_topics.description

        FROM study_topics

        INNER JOIN student_study_topics

            ON student_study_topics.topic_id =
               study_topics.id

        WHERE student_study_topics.student_id = %s

        ORDER BY
            study_topics.subject ASC,
            study_topics.name ASC
    """, (
        user_id,
    ))


    topics = cursor.fetchall()


    cursor.close()

    conn.close()


    return topics


# =========================================================
# STUDY TOPICS PAGE
# =========================================================

@app.route("/study")
@login_required
def study():

    user_id = session.get(
        "user_id"
    )


    topics = load_study_topics()

    user_topics = load_user_study_topics(
        user_id
    )


    return render_template(

        "study.html",

        topics=topics,

        user_topics=user_topics,

        header="Study"

    )


# =========================================================
# ASSIGN STUDY TOPIC TO USER
# =========================================================

@app.route(
    "/study/topic/add",
    methods=["POST"]
)
@login_required
def add_study_topic():

    user_id = session.get(
        "user_id"
    )


    topic_id = request.form.get(
        "topic_id"
    )


    if not topic_id:

        return jsonify({

            "message":
                "No study topic was selected."

        }), 400


    try:

        topic_id = int(
            topic_id
        )


        conn = get_db()

        cursor = conn.cursor()


        # Make sure topic exists

        cursor.execute("""
            SELECT id

            FROM study_topics

            WHERE id = %s
        """, (
            topic_id,
        ))


        topic = cursor.fetchone()


        if not topic:

            cursor.close()

            conn.close()

            return jsonify({

                "message":
                    "Study topic not found."

            }), 404


        # =================================================
        # MANY-TO-MANY INSERT
        # =================================================

        cursor.execute("""
            INSERT INTO student_study_topics
            (
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

            user_id,

            topic_id

        ))


        conn.commit()


        cursor.close()

        conn.close()


        return jsonify({

            "message":
                "Study topic added successfully."

        })


    except ValueError:

        return jsonify({

            "message":
                "Invalid study topic."

        }), 400


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
# REMOVE STUDY TOPIC
# =========================================================

@app.route(
    "/study/topic/remove",
    methods=["POST"]
)
@login_required
def remove_study_topic():

    user_id = session.get(
        "user_id"
    )


    topic_id = request.form.get(
        "topic_id"
    )


    if not topic_id:

        return jsonify({

            "message":
                "No study topic was selected."

        }), 400


    try:

        topic_id = int(
            topic_id
        )


        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""
            DELETE FROM student_study_topics

            WHERE student_id = %s

            AND topic_id = %s
        """, (

            user_id,

            topic_id

        ))


        conn.commit()


        cursor.close()

        conn.close()


        return jsonify({

            "message":
                "Study topic removed successfully."

        })


    except ValueError:

        return jsonify({

            "message":
                "Invalid study topic."

        }), 400


    except Exception as e:

        print(
            "REMOVE STUDY TOPIC ERROR:",
            repr(e),
            flush=True
        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# LOAD ATTENDANCE
# =========================================================

def load_attendance_rows():

    conn = get_db()

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            attendance.id,
            attendance.student_id,
            users.username,
            attendance.time,
            attendance.study_activity

        FROM attendance

        INNER JOIN users

            ON users.id =
               attendance.student_id

        ORDER BY
            attendance.time ASC,
            users.username ASC
    """)


    rows = cursor.fetchall()


    cursor.close()

    conn.close()


    return rows


def load_attendance():

    rows = load_attendance_rows()


    return {

        row["username"]:
            row["time"]

        for row in rows

    }


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
        INSERT INTO attendance
        (
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
                "Check-in is only allowed from school networks or other verified networks."

        }), 403


    # =====================================================
    # GET
    # =====================================================

    if request.method == "GET":

        entries = load_attendance_rows()

        topics = load_study_topics()


        return render_template(

            "checkin.html",

            header="checkin",

            entries=entries,

            topics=topics

        )


    # =====================================================
    # POST
    # =====================================================

    try:

        user_id = session.get(
            "user_id"
        )


        print(
            "CHECKIN USER ID FROM SESSION:",
            repr(user_id),
            flush=True
        )


        if not user_id:

            return jsonify({

                "message":
                    "You must be logged in."

            }), 401


        # =================================================
        # VERIFY USER EXISTS
        # =================================================

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                id,
                username,
                email

            FROM users

            WHERE id = %s
        """, (
            user_id,
        ))


        user = cursor.fetchone()


        cursor.close()

        conn.close()


        print(
            "CHECKIN USER FROM DATABASE:",
            dict(user)
            if user
            else None,
            flush=True
        )


        if not user:

            session.clear()


            return jsonify({

                "message":
                    "Your account could not be found. Please log in again."

            }), 404


        # =================================================
        # STUDY ACTIVITY
        # =================================================

        study_activity = request.form.get(
            "study_activity",
            ""
        ).strip()


        # =================================================
        # STUDY TOPICS
        #
        # Accepts either:
        #
        # study_topic_ids=1
        #
        # or multiple:
        #
        # study_topic_ids=1&study_topic_ids=2
        # =================================================

        study_topic_ids = request.form.getlist(
            "study_topic_ids"
        )


        # =================================================
        # CHECK EXISTING ATTENDANCE
        # =================================================

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                id,
                student_id,
                time,
                study_activity

            FROM attendance

            WHERE student_id = %s
        """, (
            user_id,
        ))


        existing_attendance = (
            cursor.fetchone()
        )


        if existing_attendance:

            cursor.close()

            conn.close()


            return jsonify({

                "message":
                    "Already checked in."

            }), 400


        # =================================================
        # CURRENT TIME
        # =================================================

        current_time = datetime.now(

            ZoneInfo(
                "Pacific/Auckland"
            )

        ).strftime("%H:%M")


        # =================================================
        # SAVE ATTENDANCE
        # =================================================

        cursor.execute("""
            INSERT INTO attendance
            (
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

            user_id,

            current_time,

            study_activity

        ))


        # =================================================
        # SAVE STUDY TOPIC RELATIONSHIPS
        #
        # This is the MANY-TO-MANY relationship.
        # =================================================

        for topic_id in study_topic_ids:

            try:

                topic_id = int(
                    topic_id
                )

            except ValueError:

                continue


            cursor.execute("""
                SELECT id

                FROM study_topics

                WHERE id = %s
            """, (
                topic_id,
            ))


            topic_exists = (
                cursor.fetchone()
            )


            if not topic_exists:

                continue


            cursor.execute("""
                INSERT INTO student_study_topics
                (
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

                user_id,

                topic_id

            ))


        conn.commit()


        cursor.close()

        conn.close()


        print(
            "CHECK-IN SUCCESS:",
            {
                "user_id":
                    user_id,

                "username":
                    user["username"],

                "time":
                    current_time,

                "study_activity":
                    study_activity,

                "study_topics":
                    study_topic_ids

            },
            flush=True
        )


        return jsonify({

            "message":
                "Checked in successfully."

        })


    except psycopg2.IntegrityError:

        if "conn" in locals():

            conn.rollback()

            cursor.close()

            conn.close()


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


        if "conn" in locals():

            try:
                conn.rollback()

                cursor.close()

                conn.close()

            except Exception:
                pass


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
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@login_required
def admin():

    try:

        # =================================================
        # CHECK ADMIN
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
                id,
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

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                attendance.id,
                attendance.student_id,
                users.username,
                users.email,
                attendance.time,
                attendance.study_activity

            FROM attendance

            INNER JOIN users

                ON users.id =
                   attendance.student_id

            ORDER BY attendance.time DESC
        """)


        attendance = cursor.fetchall()


        cursor.close()

        conn.close()


        print(
            "ATTENDANCE LOADED:",
            len(attendance),
            flush=True
        )


        # =================================================
        # STUDY TOPICS
        # =================================================

        topics = load_study_topics()


        # =================================================
        # USER/TOPIC RELATIONSHIPS
        # =================================================

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                student_study_topics.student_id,
                student_study_topics.topic_id,
                users.username,
                study_topics.name AS topic_name,
                study_topics.subject

            FROM student_study_topics

            INNER JOIN users

                ON users.id =
                   student_study_topics.student_id

            INNER JOIN study_topics

                ON study_topics.id =
                   student_study_topics.topic_id

            ORDER BY
                users.username ASC,
                study_topics.subject ASC,
                study_topics.name ASC
        """)


        student_topics = cursor.fetchall()


        cursor.close()

        conn.close()


        # =================================================
        # RENDER ADMIN
        # =================================================

        return render_template(

            "admin.html",

            header="admin",

            users=users,

            attendance=attendance,

            topics=topics,

            student_topics=student_topics,

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
# DATABASE STARTUP
# =========================================================

init_db()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(

        debug=True,

        host="0.0.0.0",

        port=int(
            os.getenv(
                "PORT",
                5000
            )
        )

    )

