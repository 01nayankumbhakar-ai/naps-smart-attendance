import os
import csv
import io
import sqlite3
from datetime import datetime, date
from functools import wraps
from math import radians, sin, cos, sqrt, atan2
from zoneinfo import ZoneInfo

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, send_file, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "CHANGE-THIS-SECRET-BEFORE-DEPLOYMENT")
DB_PATH = os.environ.get("ATTENDANCE_DB", "attendance.db")
IST = ZoneInfo("Asia/Kolkata")

# IMPORTANT: Set your company's exact latitude/longitude before enabling GPS.
# Keep GPS_RADIUS_METERS appropriate for your workplace (e.g. 150 metres).
COMPANY_LAT = float(os.environ.get("COMPANY_LAT", "0"))
COMPANY_LON = float(os.environ.get("COMPANY_LON", "0"))
GPS_RADIUS_METERS = float(os.environ.get("GPS_RADIUS_METERS", "150"))
GPS_REQUIRED_FOR_TRAINEE = os.environ.get("GPS_REQUIRED_FOR_TRAINEE", "true").lower() == "true"

SHIFTS = {
    "A": {"name": "A Shift", "start": "05:45", "end": "14:10"},
    "B": {"name": "B Shift", "start": "14:10", "end": "22:40"},
}

def now_ist():
    return datetime.now(IST)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','trainee')),
            trainee_code TEXT UNIQUE,
            department TEXT,
            shift TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            duty_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            punch_in TEXT,
            punch_out TEXT,
            in_lat REAL,
            in_lon REAL,
            out_lat REAL,
            out_lon REAL,
            in_method TEXT NOT NULL DEFAULT 'self',
            out_method TEXT,
            late INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, duty_date)
        );
        """)
        admin_mobile = os.environ.get("ADMIN_MOBILE", "9999999999")
        admin_password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
        existing = db.execute("SELECT id FROM users WHERE mobile=?", (admin_mobile,)).fetchone()
        if not existing:
            db.execute("""
                INSERT INTO users(name,mobile,password_hash,role,created_at)
                VALUES(?,?,?,?,?)
            """, ("System Admin", admin_mobile, generate_password_hash(admin_password),
                  "admin", now_ist().isoformat(timespec="seconds")))

def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * radius * atan2(sqrt(a), sqrt(1-a))

def verify_gps(lat, lon):
    if lat is None or lon is None:
        return False, "GPS location nahi mili. Browser location permission allow karein."
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False, "GPS coordinates valid nahi hain."
    if COMPANY_LAT == 0 and COMPANY_LON == 0:
        return False, "Company GPS coordinates configure nahi kiye gaye hain."
    distance = haversine_m(COMPANY_LAT, COMPANY_LON, lat, lon)
    if distance > GPS_RADIUS_METERS:
        return False, f"Aap company location se lagbhag {int(distance)} metre door hain. Attendance allowed radius {int(GPS_RADIUS_METERS)} metre hai."
    return True, "GPS verified"

def parse_coordinates():
    try:
        lat = float(request.form.get("latitude", ""))
        lon = float(request.form.get("longitude", ""))
        return lat, lon
    except (TypeError, ValueError):
        return None, None

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("trainee_dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE mobile=? AND active=1", (mobile,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            return redirect(url_for("index"))
        flash("Mobile number ya password galat hai.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    today = now_ist().date().isoformat()
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) n FROM users WHERE role='trainee' AND active=1").fetchone()["n"]
        present = db.execute("SELECT COUNT(*) n FROM attendance WHERE duty_date=? AND punch_in IS NOT NULL", (today,)).fetchone()["n"]
        trainees = db.execute("""
            SELECT u.*, a.punch_in, a.punch_out, a.late
            FROM users u LEFT JOIN attendance a
              ON a.user_id=u.id AND a.duty_date=?
            WHERE u.role='trainee' AND u.active=1 ORDER BY u.name
        """, (today,)).fetchall()
        recent = db.execute("""
            SELECT a.*,u.name,u.trainee_code FROM attendance a
            JOIN users u ON u.id=a.user_id ORDER BY a.duty_date DESC,a.id DESC LIMIT 20
        """).fetchall()
    return render_template("admin.html", total=total, present=present,
                           absent=total-present, trainees=trainees,
                           recent=recent, today=today, shifts=SHIFTS)

@app.route("/admin/trainee/add", methods=["POST"])
@login_required("admin")
def add_trainee():
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    password = request.form.get("password", "")
    code = request.form.get("trainee_code", "").strip()
    department = request.form.get("department", "").strip()
    shift = request.form.get("shift", "")
    if not all([name, mobile, password, code, shift in SHIFTS]):
        flash("Sabhi required details sahi se bharein.", "error")
        return redirect(url_for("admin_dashboard"))
    if len(password) < 8:
        flash("Password kam se kam 8 characters ka hona chahiye.", "error")
        return redirect(url_for("admin_dashboard"))
    try:
        with get_db() as db:
            db.execute("""
                INSERT INTO users(name,mobile,password_hash,role,trainee_code,department,shift,created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (name,mobile,generate_password_hash(password),"trainee",code,department,shift,
                  now_ist().isoformat(timespec="seconds")))
        flash("Trainee account create ho gaya.", "success")
    except sqlite3.IntegrityError:
        flash("Mobile number ya Trainee ID pehle se registered hai.", "error")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/trainee/<int:user_id>/toggle", methods=["POST"])
@login_required("admin")
def toggle_trainee(user_id):
    with get_db() as db:
        db.execute("UPDATE users SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND role='trainee'", (user_id,))
    flash("Trainee account status update ho gaya.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/punch/<int:user_id>/<action>", methods=["POST"])
@login_required("admin")
def admin_punch(user_id, action):
    if action not in ("in", "out"):
        abort(404)
    today = now_ist().date().isoformat()
    current = now_ist()
    with get_db() as db:
        trainee = db.execute("SELECT * FROM users WHERE id=? AND role='trainee' AND active=1", (user_id,)).fetchone()
        if not trainee:
            flash("Trainee nahi mila.", "error")
            return redirect(url_for("admin_dashboard"))
        shift = trainee["shift"] or request.form.get("shift", "A")
        if shift not in SHIFTS:
            shift = "A"
        row = db.execute("SELECT * FROM attendance WHERE user_id=? AND duty_date=?", (user_id,today)).fetchone()
        if action == "in":
            if row:
                flash("Aaj ka attendance record pehle se hai.", "error")
            else:
                late = current.strftime("%H:%M") > SHIFTS[shift]["start"]
                db.execute("""INSERT INTO attendance(user_id,duty_date,shift,punch_in,in_method,late)
                              VALUES(?,?,?,?,?,?)""",
                           (user_id,today,shift,current.strftime("%H:%M:%S"),"admin",int(late)))
                flash("Admin ne Punch In record kar diya.", "success")
        else:
            if not row or not row["punch_in"]:
                flash("Pehle Punch In record karein.", "error")
            elif row["punch_out"]:
                flash("Punch Out pehle se record hai.", "error")
            else:
                db.execute("UPDATE attendance SET punch_out=?,out_method='admin' WHERE id=?",
                           (current.strftime("%H:%M:%S"),row["id"]))
                flash("Admin ne Punch Out record kar diya.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/trainee")
@login_required("trainee")
def trainee_dashboard():
    today = now_ist().date().isoformat()
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        today_row = db.execute("SELECT * FROM attendance WHERE user_id=? AND duty_date=?",
                               (session["user_id"],today)).fetchone()
        history = db.execute("SELECT * FROM attendance WHERE user_id=? ORDER BY duty_date DESC LIMIT 30",
                             (session["user_id"],)).fetchall()
    return render_template("trainee.html", user=user, today=today, record=today_row,
                           history=history, shifts=SHIFTS,
                           gps_required=GPS_REQUIRED_FOR_TRAINEE)

@app.route("/trainee/punch/<action>", methods=["POST"])
@login_required("trainee")
def trainee_punch(action):
    if action not in ("in", "out"):
        abort(404)
    lat, lon = parse_coordinates()
    if GPS_REQUIRED_FOR_TRAINEE:
        ok, message = verify_gps(lat, lon)
        if not ok:
            flash(message, "error")
            return redirect(url_for("trainee_dashboard"))
    else:
        message = "GPS optional"

    current = now_ist()
    today = current.date().isoformat()
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=? AND active=1", (session["user_id"],)).fetchone()
        if not user:
            session.clear()
            return redirect(url_for("login"))
        shift = user["shift"]
        row = db.execute("SELECT * FROM attendance WHERE user_id=? AND duty_date=?",
                         (user["id"],today)).fetchone()
        if action == "in":
            if row:
                flash("Aaj ka Punch In pehle hi ho chuka hai.", "error")
            else:
                late = current.strftime("%H:%M") > SHIFTS[shift]["start"]
                db.execute("""
                    INSERT INTO attendance(user_id,duty_date,shift,punch_in,in_lat,in_lon,in_method,late)
                    VALUES(?,?,?,?,?,?,?,?)
                """, (user["id"],today,shift,current.strftime("%H:%M:%S"),lat,lon,"self",int(late)))
                flash("Punch In successful. " + ("Late mark hua." if late else "On time."), "success")
        else:
            if not row or not row["punch_in"]:
                flash("Pehle Punch In karein.", "error")
            elif row["punch_out"]:
                flash("Aaj ka Punch Out pehle hi ho chuka hai.", "error")
            else:
                db.execute("""UPDATE attendance SET punch_out=?,out_lat=?,out_lon=?,out_method='self'
                              WHERE id=?""",
                           (current.strftime("%H:%M:%S"),lat,lon,row["id"]))
                flash("Punch Out successful.", "success")
    return redirect(url_for("trainee_dashboard"))

@app.route("/admin/reports")
@login_required("admin")
def reports():
    month = request.args.get("month", now_ist().strftime("%Y-%m"))
    with get_db() as db:
        rows = db.execute("""
            SELECT a.*,u.name,u.mobile,u.trainee_code,u.department
            FROM attendance a JOIN users u ON u.id=a.user_id
            WHERE substr(a.duty_date,1,7)=?
            ORDER BY a.duty_date DESC,u.name
        """, (month,)).fetchall()
    return render_template("attendance.html", rows=rows, month=month)

@app.route("/admin/reports.csv")
@login_required("admin")
def export_csv():
    month = request.args.get("month", now_ist().strftime("%Y-%m"))
    with get_db() as db:
        rows = db.execute("""
            SELECT u.trainee_code,u.name,u.mobile,u.department,a.duty_date,a.shift,
                   a.punch_in,a.punch_out,a.late,a.in_method,a.out_method
            FROM attendance a JOIN users u ON u.id=a.user_id
            WHERE substr(a.duty_date,1,7)=?
            ORDER BY a.duty_date DESC,u.name
        """, (month,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Trainee ID","Name","Mobile","Department","Date","Shift",
                     "Punch In","Punch Out","Late","In Method","Out Method","Duty Hours"])
    for r in rows:
        hours = ""
        if r["punch_in"] and r["punch_out"]:
            fmt = "%H:%M:%S"
            start = datetime.strptime(r["punch_in"],fmt)
            end = datetime.strptime(r["punch_out"],fmt)
            seconds = int((end-start).total_seconds())
            if seconds < 0:
                seconds += 24*3600
            hours = f"{seconds//3600:02d}:{(seconds%3600)//60:02d}"
        writer.writerow([r["trainee_code"],r["name"],r["mobile"],r["department"],
                         r["duty_date"],r["shift"],r["punch_in"],r["punch_out"],
                         "Yes" if r["late"] else "No",r["in_method"],r["out_method"],hours])
    data = io.BytesIO(("\ufeff"+output.getvalue()).encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True,
                     download_name=f"NAPS_attendance_{month}.csv")

@app.errorhandler(403)
def forbidden(_):
    return "Access denied / Permission nahi hai.", 403

if __name__ == "__main__":
    init_db()
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
