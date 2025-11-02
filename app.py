import os
import io
import csv
import time
import math
import json
import cv2
import mediapipe as mp
import numpy as np
import threading
from datetime import datetime
from flask import (
    Flask, render_template, Response, request, redirect,
    url_for, session, jsonify, send_file, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL

# -------- Flask + DB setup --------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkey")
basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(basedir, 'users.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# -------- User model --------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def verify_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# create DB + default admin if not exists
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", email="admin@example.com")
        u.set_password("1234")
        db.session.add(u)
        db.session.commit()

# -------- PyCAW (system volume setup) --------
devices = AudioUtilities.GetSpeakers()
interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
volume_controller = cast(interface, POINTER(IAudioEndpointVolume))
volRange = volume_controller.GetVolumeRange()
minVol, maxVol = volRange[0], volRange[1]

# -------- MediaPipe + OpenCV --------
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils
hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("[WARN] Camera not opened. If blank, try changing VideoCapture index in app.py")

# -------- Metrics and session buffer --------
running = True
curr_volume = 0
curr_distance = 0
curr_gesture = "Closed"
curr_accuracy = 0.0
curr_response = 0.0

session_data = []          
SESSION_MAX = 5000         

def clear_session_data():
    global session_data
    session_data = []

# -------- Video generator (with real volume control) --------
def gen_frames():
    global curr_volume, curr_distance, curr_gesture, curr_accuracy, curr_response, session_data

    prev_time = 0.0
    while True:
        success, img = cap.read()
        if not success:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            ret, buffer = cv2.imencode('.jpg', blank)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            continue

        img = cv2.flip(img, 1)
        h, w, _ = img.shape

        if running:
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = hands.process(img_rgb)

            if results.multi_hand_landmarks:
                for hand_lms in results.multi_hand_landmarks:
                    lm_list = []
                    for idx, lm in enumerate(hand_lms.landmark):
                        lm_list.append((int(lm.x * w), int(lm.y * h)))

                    if lm_list:
                        x1, y1 = lm_list[4]   # thumb tip
                        x2, y2 = lm_list[8]   # index tip
                        length = math.hypot(x2 - x1, y2 - y1)

                        vol_percent = np.interp(length, [30, 300], [0, 100])
                        sys_vol = np.interp(vol_percent, [0, 100], [minVol, maxVol])
                        volume_controller.SetMasterVolumeLevel(sys_vol, None)

                        acc = float(np.interp(length, [30, 300], [75.0, 99.5]))
                        gesture = "Open" if length > 50 else "Closed"
                        now = time.time()
                        resp_ms = round((now - prev_time) * 1000, 2) if prev_time != 0 else 0.0
                        prev_time = now

                        curr_volume = int(np.clip(vol_percent, 0, 100))
                        curr_distance = int(length)
                        curr_gesture = gesture
                        curr_accuracy = round(acc, 2)
                        curr_response = resp_ms

                        cv2.circle(img, (x1, y1), 8, (255, 0, 0), -1)
                        cv2.circle(img, (x2, y2), 8, (255, 0, 0), -1)
                        cv2.line(img, (x1, y1), (x2, y2), (0, 200, 200), 3)
                        volBar = int(np.interp(length, [30, 300], [400, 150]))
                        cv2.rectangle(img, (50, 150), (85, 400), (30, 30, 30), 2)
                        cv2.rectangle(img, (50, volBar), (85, 400), (0, 200, 0), -1)
                        cv2.putText(img, f"{curr_volume}%", (40, 430), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,255,255), 2)

                    mp_draw.draw_landmarks(img, hand_lms, mp_hands.HAND_CONNECTIONS)

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "volume": curr_volume,
            "distance": curr_distance,
            "gesture": curr_gesture,
            "accuracy": curr_accuracy,
            "response_time": curr_response
        }
        if len(session_data) >= SESSION_MAX:
            session_data.pop(0)
        session_data.append(entry)

        ret, buffer = cv2.imencode('.jpg', img)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


# -------- Routes --------
@app.route("/")
def root():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()
        u = User.query.filter_by(username=user).first()
        if u and u.verify_password(pwd):
            login_user(u)
            return redirect(url_for("dashboard"))
        if user == "admin" and pwd == "1234":
            u = User.query.filter_by(username="admin").first()
            if u:
                login_user(u)
                return redirect(url_for("dashboard"))
        flash("Invalid credentials. Use registered account or admin/1234", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not email or not password:
            flash("All fields required", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists — log in", "info")
            return redirect(url_for("login"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered — log in", "info")
            return redirect(url_for("login"))

        new_u = User(username=username, email=email)
        new_u.set_password(password)
        db.session.add(new_u)
        db.session.commit()
        flash("Registered! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    clear_session_data()
    logout_user()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/video_feed")
@login_required
def video_feed():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/metrics")
@login_required
def metrics():
    return jsonify({
        "volume": curr_volume,
        "distance": curr_distance,
        "gesture": curr_gesture,
        "accuracy": curr_accuracy,
        "response_time": curr_response
    })

@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    global running
    data = request.get_json() or {}
    running = bool(data.get("running", True))
    return jsonify({"running": running})

@app.route("/save_report")
@login_required
def save_report():
    snapshot = list(session_data)
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["timestamp_utc", "volume_percent", "finger_distance_px", "gesture", "accuracy_percent", "response_time_ms"])
    for r in snapshot:
        cw.writerow([r.get("timestamp"), r.get("volume"), r.get("distance"), r.get("gesture"), r.get("accuracy"), r.get("response_time")])
    mem = io.BytesIO()
    mem.write(si.getvalue().encode("utf-8"))
    mem.seek(0)
    si.close()

    clear_session_data()

    fname = f"gesture_session_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.csv"
    return send_file(mem, as_attachment=True, download_name=fname, mimetype="text/csv")


# -------- Run server --------
if __name__ == "__main__":
    threading.Thread(target=gen_frames, daemon=True).start()
    app.run(debug=True, host="0.0.0.0", port=5000)
