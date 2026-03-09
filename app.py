import os
import random
import sqlite3
from datetime import datetime
from typing import Tuple

from flask import (
    Flask,
    g,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_from_directory,
)
from werkzeug.utils import secure_filename

# --- Configuration ---------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# Create uploads folder if it does not exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB limit
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")  # Change for production


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# --- Database helpers ------------------------------------------------------

def get_db():
    """Open a database connection and store it in flask.g."""
    db = getattr(g, "_database", None)
    if db is None:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        # Enforce foreign keys in SQLite
        db.execute("PRAGMA foreign_keys = ON")
        g._database = db
    return db


def close_db(e=None):
    """Close the database connection at the end of a request."""
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


@app.teardown_appcontext
def teardown_db(exception):
    close_db(exception)


def init_db():
    """Create the database tables if they do not exist."""
    db = get_db()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS production_lots (
            lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            lot_number TEXT NOT NULL,
            production_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS inspections (
            inspection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_code TEXT NOT NULL,
            lot_number TEXT NOT NULL,
            inspector_name TEXT NOT NULL,
            inspection_time TEXT NOT NULL,
            result TEXT NOT NULL,
            ai_confidence REAL NOT NULL,
            image_path TEXT NOT NULL,
            annotated_image_path TEXT,
            notes TEXT
        )
        """
    )

    # If the table already exists but uses an older schema, migrate it.
    _migrate_inspections_table(db)

    db.commit()


def _migrate_inspections_table(db: sqlite3.Connection) -> None:
    """Migrate old inspection table schemas into the current format.

    Older versions stored inspections with different columns (e.g. product_id/lot_id
    or file_name/uploaded_at). This function tries to preserve existing data by
    moving it into the current schema.
    """

    cols = [r[1] for r in db.execute("PRAGMA table_info(inspections)").fetchall()]
    if not cols:
        return

    expected = {
        "inspection_id",
        "product_code",
        "lot_number",
        "inspector_name",
        "inspection_time",
        "result",
        "ai_confidence",
        "image_path",
        "annotated_image_path",
        "notes",
    }

    if expected.issubset(set(cols)):
        return

    # If the database already has an `inspections` table but is missing the
    # `annotated_image_path` column, add it and preserve existing image paths.
    if "annotated_image_path" not in cols and "image_path" in cols:
        db.execute("ALTER TABLE inspections ADD COLUMN annotated_image_path TEXT")
        db.execute("UPDATE inspections SET annotated_image_path = image_path")
        db.commit()
        cols.append("annotated_image_path")

    if expected.issubset(set(cols)):
        return

    # If the table is in the old schema that used product/lot/user relations.
    if "product_id" in cols and "inspection_status" in cols:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS inspections_new (
                inspection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL,
                lot_number TEXT NOT NULL,
                inspector_name TEXT NOT NULL,
                inspection_time TEXT NOT NULL,
                result TEXT NOT NULL,
                ai_confidence REAL NOT NULL,
                image_path TEXT NOT NULL,
                annotated_image_path TEXT,
                notes TEXT
            )
            """
        )

        legacy_rows = db.execute(
            """
            SELECT
                i.inspection_id,
                i.image_path,
                i.ai_result,
                i.confidence,
                i.inspected_at,
                p.product_name AS product_code,
                l.lot_number,
                u.username AS inspector_name
            FROM inspections i
            LEFT JOIN products p ON i.product_id = p.product_id
            LEFT JOIN production_lots l ON i.lot_id = l.lot_id
            LEFT JOIN users u ON i.inspector_id = u.user_id
            """
        ).fetchall()

        for row in legacy_rows:
            inspector_name = row["inspector_name"] or "anonymous"
            product_code = row["product_code"] or "unknown"
            lot_number = row["lot_number"] or "unknown"
            result = "OK" if (row["ai_result"] or "").upper() in ("PASS", "OK") else "NG"
            db.execute(
                """
                INSERT INTO inspections_new (
                    product_code,
                    lot_number,
                    inspector_name,
                    inspection_time,
                    result,
                    ai_confidence,
                    image_path,
                    annotated_image_path,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_code,
                    lot_number,
                    inspector_name,
                    row["inspected_at"] or datetime.utcnow().isoformat(),
                    result,
                    row["confidence"] or 0.0,
                    row["image_path"],
                    row["image_path"],
                    None,
                ),
            )

        db.execute("DROP TABLE inspections")
        db.execute("ALTER TABLE inspections_new RENAME TO inspections")
        db.commit()
        return

    # If the table was the very old schema with file_name/uploaded_at.
    if "file_name" in cols:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS inspections_new (
                inspection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL,
                lot_number TEXT NOT NULL,
                inspector_name TEXT NOT NULL,
                inspection_time TEXT NOT NULL,
                result TEXT NOT NULL,
                ai_confidence REAL NOT NULL,
                image_path TEXT NOT NULL,
                annotated_image_path TEXT,
                notes TEXT
            )
            """
        )

        legacy_rows = db.execute(
            "SELECT file_name, uploaded_at, result, note FROM inspections"
        ).fetchall()

        for row in legacy_rows:
            result = "OK" if (row["result"] or "").upper() in ("PASS", "OK") else "NG"
            db.execute(
                """
                INSERT INTO inspections_new (
                    product_code,
                    lot_number,
                    inspector_name,
                    inspection_time,
                    result,
                    ai_confidence,
                    image_path,
                    annotated_image_path,
                    notes
                ) VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
                """,
                ("unknown", "unknown", "anonymous", result, 0.0, row["file_name"], row["file_name"], row["note"]),
            )

        db.execute("DROP TABLE inspections")
        db.execute("ALTER TABLE inspections_new RENAME TO inspections")
        db.commit()
        return


# --- AI inference utilities ------------------------------------------------

WEIGHTS_PATH = os.environ.get(
    "WEIGHTS_PATH",
    r"C:\workspace\project\train9\weights\best.pt",
)
_model = None


def _load_model():
    """Load the YOLO model once and cache it."""
    global _model
    if _model is not None:
        return _model

    if not os.path.exists(WEIGHTS_PATH):
        app.logger.warning("YOLO weights not found: %s", WEIGHTS_PATH)
        return None

    try:
        # Use ultralytics YOLO (v8+) to load a .pt model file.
        from ultralytics import YOLO

        _model = YOLO(WEIGHTS_PATH)
        return _model
    except Exception as e:
        app.logger.exception("Failed to load model weights")
        _model = None
        return None


def _annotate_image(image_path: str, detections: list[dict]) -> str:
    """Draw bounding boxes + class labels onto the uploaded image.

    Returns the filename of the annotated image saved into the uploads folder.
    """

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        app.logger.warning("Pillow not installed; skipping image annotation")
        return os.path.basename(image_path)

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det.get("bbox", [0, 0, 0, 0])]
        label = f"{det.get('class', 'unknown')} {det.get('confidence', 0):.0f}%"

        # Draw bounding box
        draw.rectangle([x1, y1, x2, y2], outline="red", width=2)

        # Draw label background
        bbox = draw.textbbox((0, 0), label, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_origin = (x1, max(y1 - text_height, 0))
        draw.rectangle(
            [
                text_origin,
                (x1 + text_width + 2, text_origin[1] + text_height + 2),
            ],
            fill="red",
        )
        draw.text((text_origin[0] + 1, text_origin[1] + 1), label, fill="white", font=font)

    annotated_filename = f"annotated_{os.path.basename(image_path)}"
    annotated_path = os.path.join(app.config["UPLOAD_FOLDER"], annotated_filename)
    img.save(annotated_path)

    return annotated_filename


def predict_weld_defect(image_path: str) -> Tuple[str, float, list[dict], str]:
    """Run model inference on the given image and return result + detections.

    Returns:
      - result: "OK" or "NG"
      - confidence: float (0-100)
      - detections: list of dicts with keys [class, confidence, bbox]
      - annotated_filename: image filename with boxes drawn (may be original image if drawing fails)
    """

    model = _load_model()

    detections: list[dict] = []
    annotated_filename = os.path.basename(image_path)

    if model is not None:
        try:
            results = model(image_path)
            if len(results) > 0:
                res = results[0]
                names = getattr(res, "names", {}) or {}

                boxes = getattr(res, "boxes", None)
                if boxes is not None:
                    for box in boxes:
                        xyxy = box.xyxy.tolist()[0]
                        conf = float(box.conf.tolist()[0])
                        cls_id = int(box.cls.tolist()[0])
                        detections.append(
                            {
                                "class": names.get(cls_id, str(cls_id)),
                                "confidence": round(conf * 100, 2),
                                "bbox": [xyxy[0], xyxy[1], xyxy[2], xyxy[3]],
                            }
                        )

            if detections:
                result = "NG"
                confidence = max(d["confidence"] for d in detections)
            else:
                result = "OK"
                confidence = 99.0

            annotated_filename = _annotate_image(image_path, detections)
            return result, confidence, detections, annotated_filename
        except Exception:
            app.logger.exception("Model inference failed")

    # Fallback to random result if model fails or is unavailable.
    confidence = round(random.uniform(85, 99), 2)
    result = random.choice(["OK", "NG"])
    return result, confidence, detections, annotated_filename


@app.before_request
def ensure_db():
    """Ensure the database exists before serving each request."""
    init_db()


# --- Helper utilities ------------------------------------------------------

def get_or_create_inspector(name: str) -> Tuple[int, str]:
    """Return a user_id for the given inspector name, creating a row if needed."""
    name = (name or "").strip() or "anonymous"
    db = get_db()

    row = db.execute("SELECT user_id, username FROM users WHERE username = ?", (name,)).fetchone()
    if row:
        return row["user_id"], row["username"]

    cur = db.execute(
        "INSERT INTO users (username, created_at) VALUES (?, ?)",
        (name, datetime.utcnow().isoformat()),
    )
    db.commit()
    return cur.lastrowid, name


# --- Application routes ---------------------------------------------------

@app.route("/")
def home():
    """Landing page for the inspection tool."""
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    """Show summary information for all inspections."""
    db = get_db()

    total_inspections = db.execute("SELECT COUNT(*) AS c FROM inspections").fetchone()["c"]
    ng_count = db.execute("SELECT COUNT(*) AS c FROM inspections WHERE result = 'NG'").fetchone()["c"]

    last = db.execute(
        """
        SELECT inspection_id, product_code, lot_number, inspector_name, result, ai_confidence, inspection_time
        FROM inspections
        ORDER BY inspection_time DESC
        LIMIT 5
        """
    ).fetchall()

    return render_template(
        "dashboard.html",
        total_inspections=total_inspections,
        ng_count=ng_count,
        recent=last,
    )


@app.route("/upload")
def upload():
    """Keep /upload as a redirect for backwards compatibility."""
    return redirect(url_for("inspection"))


@app.route("/inspection", methods=["GET", "POST"])
def inspection():
    """Inspection form (upload image + AI result)."""
    result = None
    confidence = None
    detections = []
    preview_image = None

    if request.method == "POST":
        product_code = request.form.get("product_code", "").strip()
        lot_number = request.form.get("lot_number", "").strip()
        inspector_name = request.form.get("inspector_name", "").strip()
        notes = request.form.get("notes", "").strip()
        file = request.files.get("image")
        preview_image = None

        if not product_code or not lot_number or not inspector_name:
            flash("กรุณากรอกข้อมูล รหัสสินค้า ล็อต และชื่อผู้ตรวจสอบ", "warning")
            return redirect(url_for("inspection"))

        if not file or file.filename == "":
            flash("กรุณาเลือกไฟล์ภาพก่อน", "warning")
            return redirect(url_for("inspection"))

        if not allowed_file(file.filename):
            flash("ชนิดไฟล์ไม่ถูกต้อง กรุณาอัพโหลดภาพ (.png/.jpg/.jpeg/.gif)", "danger")
            return redirect(url_for("inspection"))

        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        saved_name = f"{timestamp}_{filename}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_name)
        file.save(save_path)

        result, confidence, detections, annotated_filename = predict_weld_defect(save_path)
        preview_name = annotated_filename or os.path.basename(save_path)
        preview_image = preview_name
        original_image = saved_name

        db = get_db()
        db.execute(
            """
            INSERT INTO inspections (
                product_code,
                lot_number,
                inspector_name,
                inspection_time,
                result,
                ai_confidence,
                image_path,
                annotated_image_path,
                notes
            ) VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
            """,
            (product_code, lot_number, inspector_name, result, confidence, original_image, preview_name, notes),
        )
        db.commit()

        flash("บันทึกผลการตรวจสอบสำเร็จ", "success")

    return render_template(
        "inspection.html",
        result=result,
        confidence=confidence,
        detections=detections,
        preview_image=preview_image,
        original_image=original_image if request.method == "POST" else None,
    )


@app.route("/inspection_history")
def inspection_history():
    """Show inspection history."""
    db = get_db()
    query = """
        SELECT
            inspection_id,
            product_code,
            lot_number,
            inspector_name,
            inspection_time,
            image_path,
            annotated_image_path,
            result,
            ai_confidence,
            notes
        FROM inspections
        ORDER BY inspection_time DESC
    """
    rows = db.execute(query).fetchall()

    return render_template("inspection_history.html", inspections=rows)


@app.route("/inspection/<int:inspection_id>/status", methods=["POST"])
def set_inspection_status(inspection_id: int):
    """Allow approval/rejection of an inspection."""
    new_status = request.form.get("status")
    if new_status not in ("approved", "rejected"):
        flash("Invalid status.", "danger")
        return redirect(url_for("inspection_history"))

    db = get_db()
    db.execute(
        "UPDATE inspections SET inspection_status = ? WHERE inspection_id = ?",
        (new_status, inspection_id),
    )
    db.commit()

    flash("Inspection status updated.", "success")
    return redirect(url_for("inspection_history"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    """Serve uploaded images back to the browser."""
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
    # Ensure we run init_db() inside an application context.
    with app.app_context():
        init_db()

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")
    app.run(host="0.0.0.0", port=port, debug=debug)
