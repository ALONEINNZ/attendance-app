from PIL import Image, ImageEnhance
import pytesseract
import re
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash

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
import re

from datetime import datetime
from functools import wraps
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
# SCHOOL NETWORKS
# =========================================================

SCHOOL_NETWORKS = {

    "Burnside WiFi": [

        "202.150.123.193/32",
        "122.63.129.201/32",
        "202.36.179.108/32",
        "122.58.103.94/32"

    ]

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
# UPLOAD CONFIGURATION
# =========================================================

app.config["UPLOAD_FOLDER"] = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)

app.config["TIMETABLE_FOLDER"] = os.path.join(
    app.config["UPLOAD_FOLDER"],
    "timetables"
)

os.makedirs(
    app.config["UPLOAD_FOLDER"],
    exist_ok=True
)

os.makedirs(
    app.config["TIMETABLE_FOLDER"],
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

    MAIL_USE_SSL=False

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

    }

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

    "22298@burnside.school.nz",
    "22531@burnside.school.nz"

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

    try:

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
        # STUDENT STUDY TOPICS
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


        # =================================================
        # TIMETABLE
        # =================================================

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS timetable (

                id SERIAL PRIMARY KEY,

                student_id INTEGER NOT NULL,

                week TEXT NOT NULL,

                day TEXT NOT NULL,

                period INTEGER NOT NULL,

                subject TEXT NOT NULL,

                start_time TEXT,

                end_time TEXT,

                FOREIGN KEY (student_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE

            )

        """)


        conn.commit()

        print(
            "DATABASE INITIALISED SUCCESSFULLY",
            flush=True
        )

    except Exception:

        conn.rollback()

        raise

    finally:

        cursor.close()
        conn.close()


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    study_topics = []

    if session.get("username"):

        conn = get_db()
        cursor = conn.cursor()

        try:

            cursor.execute("""

                SELECT
                    id,
                    name,
                    subject,
                    description

                FROM study_topics

                ORDER BY
                    subject,
                    name

            """)

            study_topics = cursor.fetchall()

        finally:

            cursor.close()
            conn.close()

    return render_template(
        "Home.html",
        study_topics=study_topics
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

        try:

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

                session["user_id"] = student["id"]

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

                print(
                    "GOOGLE LOGIN SUCCESS:",
                    email,
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
            # GENERATE USER CODE
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

                VALUES

                (
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

        except Exception:

            conn.rollback()

            raise

        finally:

            cursor.close()
            conn.close()

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
# TIMETABLE OCR HELPERS
# =========================================================

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday"
]


def clean_subject(subject):

    subject = subject.strip()

    subject = re.sub(
        r"[^A-Za-z0-9]",
        "",
        subject
    )

    subject = subject.upper()


    # ---------------------------------------------------------
    # Common OCR mistakes
    # ---------------------------------------------------------

    corrections = {

        "138TY": "13STY",

        "13C1S": "13CLS",

        "13CIS": "13CLS",

        "13¢LS": "13CLS",

        "130TG": "13DTG",

    }


    if subject in corrections:

        return corrections[subject]


    return subject


def is_subject_code(value):

    value = clean_subject(
        value
    )

    # Normal timetable subject code:
    #
    # 13XXX
    #
    # Example:
    # 13PHY
    # 13CLS
    # 13MAS
    # 13STY
    # 13DTP
    # 13DTG

    return bool(
        re.fullmatch(
            r"13[A-Z]{2,4}",
            value
        )
    )


def extract_subjects_from_line(line):

    words = line.split()

    subjects = []

    for word in words:

        cleaned = clean_subject(
            word
        )

        if is_subject_code(
            cleaned
        ):

            subjects.append(
                cleaned
            )

    return subjects


def parse_timetable_ocr(ocr_text):
    """
    Parse timetable OCR text.

    Handles OCR where periods and times are on the same line, e.g.

        3 10:50am
        13CLS

    as well as OCR where they are separated:

        3
        10:50am
        13CLS

    The parser keeps each subject tied to the period immediately
    before it and does not search past the next period.
    """

    if not ocr_text:
        return []

    # -------------------------------------------------
    # CLEAN OCR LINES
    # -------------------------------------------------

    lines = [
        line.strip()
        for line in ocr_text.splitlines()
        if line.strip()
    ]

    results = []

    current_day = None
    current_period = None
    current_time = None

    # Valid days
    valid_days = {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday"
    }

    # -------------------------------------------------
    # PROCESS OCR LINE BY LINE
    # -------------------------------------------------

    for line in lines:

        # ---------------------------------------------
        # FIND DAY
        # ---------------------------------------------

        found_day = None

        for day in valid_days:
            if re.search(
                rf"\b{day}\b",
                line,
                re.IGNORECASE
            ):
                found_day = day
                break

        if found_day:

            current_day = found_day

            # Reset period information when moving
            # to a new day.
            current_period = None
            current_time = None

            continue

        # ---------------------------------------------
        # IGNORE DATE / HEADER INFORMATION
        # ---------------------------------------------

        # Examples:
        # Monday - Day 6
        # 07 Sep 2026
        if re.search(
            r"\bDay\s+\d+\b",
            line,
            re.IGNORECASE
        ):
            continue

        if re.search(
            r"\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b",
            line
        ):
            continue

        # ---------------------------------------------
        # FIND PERIOD + OPTIONAL TIME
        # ---------------------------------------------

        period_match = re.match(
            r"^([1-5])(?:\s+(\d{1,2}:\d{2}\s*(?:am|pm)))?\s*$",
            line,
            re.IGNORECASE
        )

        if period_match:

            current_period = int(
                period_match.group(1)
            )

            current_time = period_match.group(2)

            continue

        # ---------------------------------------------
        # FIND TIME ON ITS OWN LINE
        # ---------------------------------------------

        time_match = re.fullmatch(
            r"(\d{1,2}:\d{2}\s*(?:am|pm))",
            line,
            re.IGNORECASE
        )

        if time_match:

            # Only use the time if we already know
            # which period it belongs to.
            if current_period is not None:

                current_time = (
                    time_match.group(1)
                )

            continue

        # ---------------------------------------------
        # DON'T PARSE BREAKS AS SUBJECTS
        # ---------------------------------------------

        if line.upper() in {
            "FORM",
            "INT",
            "LUNCH",
            "AS"
        }:

            # FORM is a real timetable entry only when
            # it occurs after a period.
            #
            # For example:
            #
            # 1 9:10am
            # FORM
            #
            # should become:
            # P1 = FORM
            #
            if (
                line.upper() == "FORM"
                and current_day is not None
                and current_period is not None
            ):

                results.append({
                    "day": current_day,
                    "period": current_period,
                    "subject": "FORM",
                    "start_time": current_time
                })

            # INT / LUNCH / AS are breaks, so ignore them.
            continue

        # ---------------------------------------------
        # FIND SUBJECT CODE
        # ---------------------------------------------

        if (
            current_day is None
            or current_period is None
        ):
            continue

        subject = None

        # Split OCR line into possible words
        words = re.findall(
            r"[A-Za-z0-9]+",
            line
        )

        for word in words:

            cleaned = clean_subject(word)

            # Burnside Year 13 subject format
            #
            # Examples:
            # 13STY
            # 13CLS
            # 13PHY
            # 13DTG
            # 13DTP
            # 13MAS
            if re.fullmatch(
                r"13[A-Z0-9]{3}",
                cleaned
            ):

                subject = cleaned
                break

        if subject:

            results.append({
                "day": current_day,
                "period": current_period,
                "subject": subject,
                "start_time": current_time
            })

            # Clear the current period after successfully
            # assigning its subject.
            #
            # This prevents later text such as a teacher
            # name or room from accidentally being assigned
            # to the same period.
            current_period = None
            current_time = None

    # -------------------------------------------------
    # REMOVE DUPLICATE DAY/PERIOD ENTRIES
    # -------------------------------------------------

    unique_results = {}

    for entry in results:

        key = (
            entry["day"],
            entry["period"]
        )

        unique_results[key] = entry

    # -------------------------------------------------
    # SORT MONDAY -> FRIDAY, PERIOD 1 -> 5
    # -------------------------------------------------

    day_order = {
        "Monday": 1,
        "Tuesday": 2,
        "Wednesday": 3,
        "Thursday": 4,
        "Friday": 5
    }

    results = list(
        unique_results.values()
    )

    results.sort(
        key=lambda x: (
            day_order.get(
                x["day"],
                99
            ),
            x["period"]
        )
    )

    return results

# =========================================================
# TIMETABLE
# =========================================================
# =========================================================
# TIMETABLE
# =========================================================

@app.route(
    "/timetable",
    methods=["GET", "POST"]
)
@login_required
def timetable():

    student_id = session.get("user_id")

    # =====================================================
    # GET
    # =====================================================

    if request.method == "GET":

        return render_template(
            "timetable.html"
        )

    # =====================================================
    # POST
    # =====================================================

    try:

        # -------------------------------------------------
        # WEEK
        # -------------------------------------------------

        week = request.form.get(
            "week",
            "A"
        ).upper().strip()

        if week not in ("A", "B"):

            return jsonify({
                "message":
                    "Invalid timetable week."
            }), 400

        # -------------------------------------------------
        # FILE
        # -------------------------------------------------

        file = request.files.get(
            "timetable"
        )

        if not file or not file.filename:

            return jsonify({
                "message":
                    "Please select a timetable image."
            }), 400

        # -------------------------------------------------
        # FILE TYPE
        # -------------------------------------------------

        allowed_extensions = {
            "png",
            "jpg",
            "jpeg",
            "webp"
        }

        if "." not in file.filename:

            return jsonify({
                "message":
                    "Invalid file type."
            }), 400

        extension = (
            file.filename
            .rsplit(".", 1)[-1]
            .lower()
        )

        if extension not in allowed_extensions:

            return jsonify({
                "message":
                    "Please upload a PNG, JPG, JPEG or WEBP image."
            }), 400

        # -------------------------------------------------
        # SAVE IMAGE
        # -------------------------------------------------

        filename = secure_filename(
            f"{student_id}_week_{week}.{extension}"
        )

        filepath = os.path.join(
            app.config["TIMETABLE_FOLDER"],
            filename
        )

        file.save(filepath)

        print(
            "TIMETABLE IMAGE SAVED:",
            filepath,
            flush=True
        )

        # -------------------------------------------------
        # CHECK TESSERACT
        # -------------------------------------------------

        try:

            tesseract_version = (
                pytesseract
                .get_tesseract_version()
            )

            print(
                "TESSERACT VERSION:",
                tesseract_version,
                flush=True
            )

        except Exception as e:

            print(
                "TESSERACT NOT AVAILABLE:",
                repr(e),
                flush=True
            )

            return jsonify({
                "message":
                    "OCR is not available on the server."
            }), 500

        # -------------------------------------------------
        # OPEN ORIGINAL IMAGE
        # -------------------------------------------------

        try:

            original_image = Image.open(
                filepath
            )

            print(
                "ORIGINAL IMAGE SIZE:",
                original_image.size,
                flush=True
            )

            # Convert once.
            original_image = original_image.convert(
                "L"
            )

        except Exception as e:

            print(
                "IMAGE OPEN ERROR:",
                repr(e),
                flush=True
            )

            return jsonify({
                "message":
                    "Could not open the timetable image."
            }), 400

        # -------------------------------------------------
        # LIMIT IMAGE SIZE
        # -------------------------------------------------
        #
        # We don't need a huge image for timetable OCR.
        #
        # Keeping the largest dimension around 1000 pixels
        # prevents Tesseract from doing unnecessary work.

        max_dimension = 1000

        if max(original_image.size) > max_dimension:

            ratio = (
                max_dimension /
                max(original_image.size)
            )

            new_size = (
                max(
                    1,
                    int(original_image.width * ratio)
                ),
                max(
                    1,
                    int(original_image.height * ratio)
                )
            )

            original_image = original_image.resize(
                new_size,
                Image.Resampling.LANCZOS
            )

        print(
            "OCR BASE IMAGE SIZE:",
            original_image.size,
            flush=True
        )

        # -------------------------------------------------
        # CONTRAST
        # -------------------------------------------------

        original_image = ImageEnhance.Contrast(
            original_image
        ).enhance(1.6)

        # -------------------------------------------------
        # OCR EACH DAY COLUMN
        # -------------------------------------------------

        print(
            f"STARTING OCR FOR WEEK {week}...",
            flush=True
        )

        days = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday"
        ]

        ocr_parts = []

        image_width, image_height = (
            original_image.size
        )

        column_width = (
            image_width / len(days)
        )

        try:

            for index, day in enumerate(days):

                # -----------------------------------------
                # CALCULATE COLUMN
                # -----------------------------------------

                left = int(
                    index * column_width
                )

                right = int(
                    (index + 1) * column_width
                )

                # Small padding prevents grid lines
                # directly touching the OCR area.

                padding = 3

                left = max(
                    0,
                    left + padding
                )

                right = min(
                    image_width,
                    right - padding
                )

                if right <= left:

                    print(
                        f"SKIPPING {day}: invalid crop",
                        flush=True
                    )

                    continue

                # -----------------------------------------
                # CROP
                # -----------------------------------------

                column = original_image.crop(
                    (
                        left,
                        0,
                        right,
                        image_height
                    )
                )

                print(
                    f"OCR {day} column:",
                    column.size,
                    flush=True
                )

                # -----------------------------------------
                # MODERATE UPSCALE
                # -----------------------------------------
                #
                # Previous code doubled the image.
                # That was expensive on Render.
                #
                # 1.25x gives Tesseract slightly more
                # resolution without making the image
                # enormous.

                upscale = 1.25

                new_width = max(
                    1,
                    int(column.width * upscale)
                )

                new_height = max(
                    1,
                    int(column.height * upscale)
                )

                column = column.resize(
                    (
                        new_width,
                        new_height
                    ),
                    Image.Resampling.LANCZOS
                )

                # -----------------------------------------
                # CONTRAST
                # -----------------------------------------

                column = ImageEnhance.Contrast(
                    column
                ).enhance(1.5)

                # -----------------------------------------
                # OCR
                # -----------------------------------------
                #
                # PSM 6 works well for a timetable column
                # because it treats the image as a block
                # of text.
                #
                # timeout prevents one bad OCR operation
                # from hanging forever.

                try:

                    column_text = (
                        pytesseract.image_to_string(
                            column,
                            lang="eng",
                            config="--psm 6",
                            timeout=5
                        )
                    )

                except RuntimeError as e:

                    print(
                        f"OCR TIMEOUT/ERROR FOR {day}:",
                        repr(e),
                        flush=True
                    )

                    column_text = ""

                # -----------------------------------------
                # SAVE RESULT
                # -----------------------------------------

                ocr_parts.append(
                    f"{day}\n{column_text}"
                )

                print(
                    f"OCR {day} COMPLETE",
                    flush=True
                )

                # Explicitly release the crop before
                # processing the next column.

                del column

        finally:

            # Release the large image before parsing.

            del original_image

        # -------------------------------------------------
        # COMBINE OCR
        # -------------------------------------------------

        ocr_text = "\n\n".join(
            ocr_parts
        )

        print(
            "OCR FINISHED",
            flush=True
        )

        print(
            "OCR TEXT:",
            repr(ocr_text),
            flush=True
        )

        # -------------------------------------------------
        # PARSE
        # -------------------------------------------------

        parsed_rows = parse_timetable_ocr(
            ocr_text
        )

        print(
            "PARSED TIMETABLE:",
            parsed_rows,
            flush=True
        )

        # -------------------------------------------------
        # RETURN
        # -------------------------------------------------

        return jsonify({

            "message":
                f"Week {week} timetable read successfully.",

            "week":
                week,

            "ocr_text":
                ocr_text,

            "parsed":
                parsed_rows

        })

    except Exception as e:

        print(
            "TIMETABLE OCR ERROR:",
            repr(e),
            flush=True
        )

        return jsonify({

            "message":
                f"Could not read timetable: {str(e)}"

        }), 500


# =========================================================
# SAVE TIMETABLE
# =========================================================

@app.route(
    "/save-timetable",
    methods=["POST"]
)
@login_required
def save_timetable():

    try:

        student_id = session.get(
            "user_id"
        )

        data = request.get_json(
            silent=True
        ) or {}

        week = str(
            data.get("week", "")
        ).upper().strip()

        ocr_text = data.get(
            "ocr_text",
            ""
        )

        if week not in ["A", "B"]:

            return jsonify({
                "message":
                    "Invalid timetable week."
            }), 400

        if not ocr_text:

            return jsonify({
                "message":
                    "No timetable data found."
            }), 400

        # ================================================
        # PARSE
        # ================================================

        entries = parse_timetable_ocr(
            ocr_text
        )

        if not entries:

            return jsonify({
                "message":
                    "Could not find any timetable periods."
            }), 400

        # ================================================
        # DATABASE
        # ================================================

        conn = get_db()
        cursor = conn.cursor()

        try:

            # --------------------------------------------
            # COMPLETELY REPLACE THIS WEEK
            # --------------------------------------------

            cursor.execute(
                """
                DELETE FROM timetable
                WHERE student_id = %s
                  AND week = %s
                """,
                (
                    student_id,
                    week
                )
            )

            # --------------------------------------------
            # INSERT NEW TIMETABLE
            # --------------------------------------------

            inserted = 0

            for entry in entries:

                cursor.execute(
                    """
                    INSERT INTO timetable
                    (
                        student_id,
                        week,
                        day,
                        period,
                        subject,
                        start_time,
                        end_time
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        student_id,
                        week,
                        entry["day"],
                        entry["period"],
                        entry["subject"],
                        entry.get(
                            "start_time"
                        ),
                        None
                    )
                )

                inserted += 1

            conn.commit()

        except Exception:

            conn.rollback()

            raise

        finally:

            cursor.close()
            conn.close()

        return jsonify({

            "message":
                f"Week {week} timetable saved successfully.",

            "entries":
                inserted

        })

    except Exception as e:

        print(
            "SAVE TIMETABLE ERROR:",
            repr(e),
            flush=True
        )

        return jsonify({

            "message":
                f"Could not save timetable: {str(e)}"

        }), 500

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


        try:

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


        finally:

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

@app.route(
    "/account",
    methods=["GET", "POST"]
)
@login_required
def account():

    student_id = session.get(
        "user_id"
    )


    conn = get_db()
    cursor = conn.cursor()


    try:

        # -------------------------------------------------
        # USER
        # -------------------------------------------------

        cursor.execute("""

            SELECT *

            FROM users

            WHERE id = %s

        """, (
            student_id,
        ))


        user = cursor.fetchone()


        # -------------------------------------------------
        # TIMETABLE
        # -------------------------------------------------

        cursor.execute("""

            SELECT

                id,
                week,
                day,
                period,
                subject,
                start_time,
                end_time

            FROM timetable

            WHERE student_id = %s

            ORDER BY

                week,

                CASE day

                    WHEN 'Monday' THEN 1

                    WHEN 'Tuesday' THEN 2

                    WHEN 'Wednesday' THEN 3

                    WHEN 'Thursday' THEN 4

                    WHEN 'Friday' THEN 5

                    ELSE 6

                END,

                period

        """, (
            student_id,
        ))


        timetable_rows = cursor.fetchall()


    finally:

        cursor.close()
        conn.close()


    return render_template(

        "account.html",

        header="account",

        user=user,

        timetable=timetable_rows

    )


# =========================================================
# TEACHER
# =========================================================

@app.route(
    "/teacher"
)
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


    try:

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

            ORDER BY

                study_topics.subject,

                study_topics.name

        """, (
            student_id,
        ))


        return cursor.fetchall()


    finally:

        cursor.close()
        conn.close()


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


        try:

            # =================================================
            # FIND TOPIC
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


            # =================================================
            # CREATE TOPIC
            # =================================================

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

                    VALUES

                    (
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
            # CONNECT STUDENT
            # =================================================

            cursor.execute("""

                INSERT INTO student_study_topics

                (
                    student_id,
                    topic_id
                )

                VALUES

                (
                    %s,
                    %s
                )

                ON CONFLICT DO NOTHING

            """, (

                student_id,
                topic_id

            ))


            conn.commit()


        except Exception:

            conn.rollback()

            raise


        finally:

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


    try:

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


        return cursor.fetchall()


    finally:

        cursor.close()
        conn.close()


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


    try:

        cursor.execute("""

            INSERT INTO attendance

            (
                student_id,
                time,
                study_activity
            )

            VALUES

            (
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


    except Exception:

        conn.rollback()

        raise


    finally:

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
        # VERIFY USER
        # =================================================

        conn = get_db()
        cursor = conn.cursor()


        try:

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


        finally:

            cursor.close()
            conn.close()


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


        try:

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


            existing_attendance = cursor.fetchone()


        finally:

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


    try:

        cursor.execute(
            "DELETE FROM users"
        )


        conn.commit()


    except Exception:

        conn.rollback()

        raise


    finally:

        cursor.close()
        conn.close()


    session.clear()


    return "All users deleted."


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


        try:

            cursor.execute(
                "DELETE FROM attendance"
            )


            conn.commit()


        except Exception:

            conn.rollback()

            raise


        finally:

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

@app.route(
    "/admin"
)
@login_required
def admin():

    try:

        email = session.get(
            "email",
            ""
        ).lower().strip()


        if email not in ADMIN_EMAILS:

            return redirect(
                url_for("home")
            )


        # =================================================
        # USERS
        # =================================================

        conn = get_db()
        cursor = conn.cursor()


        try:

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


        finally:

            cursor.close()
            conn.close()


        # =================================================
        # ATTENDANCE
        # =================================================

        conn = get_db()
        cursor = conn.cursor()


        try:

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


        finally:

            cursor.close()
            conn.close()


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

            "ADMIN PAGE ERROR:",

            repr(e),

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

