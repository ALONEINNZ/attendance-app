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
import secrets

from datetime import datetime
from functools import wraps

from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

from flask_mail import Mail
from werkzeug.middleware.proxy_fix import ProxyFix

from authlib.integrations.flask_client import OAuth

from zoneinfo import ZoneInfo


# =========================================================
# LOAD ENVIRONMENT VARIABLES
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
# SECRET KEY
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

                if client_ip in ipaddress.ip_network(
                    network
                ):

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

    MAIL_USERNAME=os.getenv(
        "USERNAME"
    ),

    MAIL_PASSWORD=os.getenv(
        "PASSWORD"
    ),

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
    # A student can have many study topics.
    # A study topic can belong to many students.
    #
    # This creates the MANY-TO-MANY relationship.
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
    # STUDENT <-> STUDY TOPIC
    #
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

            FOREIGN KEY (student_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            FOREIGN KEY (topic_id)
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

            FOREIGN KEY (student_id)
                REFERENCES users(id)
                ON DELETE CASCADE

        )

    """)


    conn.commit()

    cursor.close()

    conn.close()


    print(
        "DATABASE INITIALISED SUCCESSFULLY",
        flush=True
    )


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

@app.route(
    "/auth/google/callback"
)
def google_callback():

    try:

        token = google.authorize_access_token()

        user = token.get(
            "userinfo"
        )


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


        # =================================================
        # BURNSIDE EMAIL CHECK
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


        # =================================================
        # DATABASE
        # =================================================

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

            username = (
                email.split("@")[0]
            )


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
        # GENERATE CODE
        # =================================================

        code = secrets.token_hex(3)


        # =================================================
        # PASSWORD
        # =================================================

        password = generate_password_hash(

            secrets.token_urlsafe(32)

        )


        # =================================================
        # VERIFICATION KEY
        # =================================================

        verify_key = secrets.token_urlsafe(
            32
        )


        # =================================================
        # CREATE USER
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
        # SESSION
        # =================================================

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

            username,

            user_id,

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

            "Google login error: "
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

@app.route(
    "/my-attendance"
)
@login_required
def my_attendance():

    try:

        user_id = session.get(
            "user_id"
        )


        if not user_id:

            return redirect(
                url_for("login")
            )


        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT

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

    user_id = session.get(
        "user_id"
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

        WHERE id = %s

    """, (

        user_id,

    ))


    user = cursor.fetchone()


    cursor.close()

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
# STUDY TOPICS
# =========================================================

def get_student_study_topics(
    student_id
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

            ON study_topics.id =
               student_study_topics.topic_id

        WHERE student_study_topics.student_id = %s

        ORDER BY study_topics.subject,
                 study_topics.name

    """, (

        student_id,

    ))


    topics = cursor.fetchall()


    cursor.close()

    conn.close()


    return topics


# =========================================================
# ADD STUDY TOPIC
# =========================================================

@app.route(
    "/study-topic",
    methods=["POST"]
)
@login_required
def add_study_topic():

    try:

        student_id = session.get(
            "user_id"
        )


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
                    "Study topic name and subject are required."

            }), 400


        conn = get_db()

        cursor = conn.cursor()


        # =================================================
        # FIND / CREATE TOPIC
        # =================================================

        cursor.execute("""

            SELECT id

            FROM study_topics

            WHERE name = %s

            AND subject = %s

        """, (

            name,

            subject

        ))


        topic = cursor.fetchone()


        if topic:

            topic_id = topic["id"]

        else:

            cursor.execute("""

                INSERT INTO study_topics

                (

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

            topic_id = topic["id"]


        # =================================================
        # CONNECT STUDENT TO TOPIC
        #
        # THIS IS THE MANY-TO-MANY RELATIONSHIP
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

            ON CONFLICT DO NOTHING

        """, (

            student_id,

            topic_id

        ))


        conn.commit()

        cursor.close()

        conn.close()


        return jsonify({

            "message":
                "Study topic added successfully."

        })


    except Exception as e:

        print(

            "STUDY TOPIC ERROR:",

            repr(e),

            flush=True

        )


        return jsonify({

            "message":
                f"Error: {str(e)}"

        }), 500


# =========================================================
# GET MY STUDY TOPICS
# =========================================================

@app.route(
    "/study-topics"
)
@login_required
def study_topics():

    try:

        student_id = session.get(
            "user_id"
        )


        topics = get_student_study_topics(
            student_id
        )


        return jsonify({

            "topics": [

                dict(topic)

                for topic in topics

            ]

        })


    except Exception as e:

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
# RESET USERS
# =========================================================

@app.route(
    "/reset-users"
)
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

    cursor.close()

    conn.close()


    session.clear()


    return "All users deleted."


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


        return render_template(

            "checkin.html",

            header="checkin",

            entries=entries

        )


    # =====================================================
    # POST
    # =====================================================

    try:

        student_id = session.get(
            "user_id"
        )


        username = session.get(
            "username"
        )


        print(

            "CHECKIN USER:",

            repr(username),

            "USER ID:",

            repr(student_id),

            flush=True

        )


        if not student_id:

            return jsonify({

                "message":
                    "You must be logged in."

            }), 401


        # =================================================
        # STUDY ACTIVITY
        # =================================================

        study_activity = request.form.get(

            "study_activity",

            ""

        ).strip()


        # =================================================
        # VERIFY USER STILL EXISTS
        # =================================================

        conn = get_db()

        cursor = conn.cursor()


        cursor.execute("""

            SELECT

                id,

                username,

                email,

                pfp

            FROM users

            WHERE id = %s

        """, (

            student_id,

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
                    "Your account no longer exists. Please log in again."

            }), 404


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

            student_id,

        ))


        existing_attendance = (
            cursor.fetchone()
        )


        cursor.close()

        conn.close()


        if existing_attendance:

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

        ).strftime(
            "%H:%M"
        )


        # =================================================
        # SAVE
        # =================================================

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


        # =================================================
        # ADMIN CHECK
        # =================================================

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
        # ADMIN PAGE
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
# DATABASE INITIALISATION
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

