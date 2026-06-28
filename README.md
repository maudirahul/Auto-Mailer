# 📧 HR Email Campaign Web Dashboard

A beautiful, premium web-based control panel to execute and monitor automated HR email campaigns. It uses **FastAPI** for the backend server and vanilla **HTML5/CSS3/JavaScript** for the web interface.

---

## 🎨 Features
* **Drag-and-Drop Dropzones**: Easy file uploading for both HR contacts PDF and resume PDF.
* **Smart Template Editor**: Write custom body templates and inject `{hr_name}` or `{company_name}` with simple click chips.
* **MIME/Mixed Package Builder**: Correctly nests HTML, fallback Plain Text, and PDF attachments.
* **Live Neon Dashboard**: Monitor current speed delays, status counts (sent/failed), and overall percentage progress.
* **Retro-Terminal Output**: View a live EventStream feed of console actions (such as SMTP login, delay updates, and delivery status).
* **Safe Restart Protection**: Remembers already sent contacts in `sent_emails.txt` so it never double-sends even if paused and restarted.
* **Dry-Run Mode**: Test your templates and parsing logic virtually without hitting Gmail servers or SMTP.

---

## 🚀 Getting Started

### 1. Install Dependencies
Make sure you are in the `Email sending script ui` directory, then run:
```bash
pip install -r requirements.txt
```

### 2. Run the Dashboard Web Server
Start the local server by running:
```bash
python app.py
```

### 3. Open the UI Dashboard
Open your web browser and navigate to:
```
http://localhost:8000
```

---

## 📂 Project Structure
```
Email sending script ui/
├── app.py                  # Main backend, API endpoints & campaign runner
├── requirements.txt        # Python dependency packages
├── sent_emails.txt         # State file generated automatically on first send
├── templates/
│   └── index.html          # Web dashboard layout page
└── static/
    ├── style.css           # Custom Glassmorphism styles
    └── app.js              # Client-side form handlers and EventSource logger
```
