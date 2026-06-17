from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

# Use absolute path relative to this script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "attendance.db")


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
    return render_template("index.html")


@app.route("/teacher")
def teacher():
    return render_template("teacher.html")


@app.route("/checkin", methods=["POST"])
def checkin():
    try:
        name = request.json.get("name") if request.json else None

        if not name:
            return jsonify({"message": "Name is required"})
        
        student_ip = request.remote_addr


        SCHOOL_PREFIXES = ["10.45", "10.1"]  
        # Allow localhost for testing, or school network
        if not (student_ip.startswith("127.") or any(student_ip.startswith(prefix) for prefix in SCHOOL_PREFIXES)):
            return jsonify({"message": f"You must be on school Wi-Fi to check in (IP: {student_ip})"})

        
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

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)