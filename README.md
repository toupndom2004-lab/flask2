# AI Welding Inspection (Flask)

A simple university-friendly demo project showing how to build a basic **AI welding inspection** system using:

- **Flask** web application framework
- **SQLite** database for users, products, lots, and inspection records
- **Product + lot traceability**, including product names and lot numbers
- **Inspection workflow** (pending/approved/rejected) with AI result + confidence
- **Dashboard** and **history** pages for reviewing inspections


---

## 🏃‍♂️ Run the project

1. Create a Python virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # macOS / Linux
.venv\Scripts\activate     # Windows PowerShell
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
python app.py
```

If `python app.py` fails with `ModuleNotFoundError`, make sure you have installed dependencies (`pip install -r requirements.txt`) and are using the same Python environment. For example:

```bash
C:\Users\Envychii\AppData\Local\Programs\Python\Python310\python.exe app.py
```

Or run the provided helper:

```bash
run.bat
```

4. Open your browser at:

> http://127.0.0.1:5000/

---

## 📂 Project structure

```
project/
  app.py           # Flask app and sqlite logic
  database.db      # SQLite database (created automatically)
  templates/       # HTML templates (Jinja2)
  uploads/         # Uploaded images stored here
  static/          # Static assets (CSS / JS) - empty by default
```

---

## 🔧 Customize the inspection logic

The inspection is currently a placeholder in `run_inspection()` inside `app.py`. Replace it with your own AI/ML model or image analysis logic to compute results.

---

## ⚙️ Notes

- Uploaded images are stored in the `uploads/` folder.
- The inspection results are stored in the SQLite database `database.db`.
- This project is intended as a learning demo for Industry 4.0 manufacturing systems.

---

## 🚀 Deployment (Render)

This project is ready to deploy to **Render** (https://render.com) using **Gunicorn** as the WSGI server.

### ✅ What’s included

- `requirements.txt` with `gunicorn`
- `Procfile` (for Heroku-style environments)
- `render.yaml` (Render service manifest)
- `app.py` reads the `PORT` environment variable and uses `SECRET_KEY` from env

### 📦 Deploy to Render

1. Initialize a git repo (if you haven’t already) and push the code to GitHub:

   ```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <YOUR_GIT_URL>
git push -u origin main
```

2. On Render, create a **New Web Service** and connect your repo.
3. Use these settings (the defaults in `render.yaml` should work):

   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
   - **Environment:** Python

4. (Recommended) Set environment variables in Render:
   - `SECRET_KEY` - a random secret for Flask session security.

### 🧪 Run locally with Gunicorn

```bash
pip install -r requirements.txt
gunicorn app:app
```

> Gunicorn will bind to the port in the `PORT` environment variable (Render sets this automatically).
