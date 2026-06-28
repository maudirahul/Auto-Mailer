import os
import sys
import time
import random
import asyncio
import smtplib
import logging
import queue
import threading
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import pdfplumber
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="HR Email Campaign Dashboard")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# App folders
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Handle resource paths when packaged with PyInstaller (static/templates inside temp _MEIPASS)
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(BASE_DIR), relative_path)

# Handle persistent storage paths (database/logs beside the actual .exe file, not in temp folder)
def get_storage_path(relative_path):
    if hasattr(sys, 'frozen'):
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, relative_path)
    return os.path.join(os.path.abspath(BASE_DIR), relative_path)

TEMPLATES_DIR = get_resource_path("templates")
STATIC_DIR = get_resource_path("static")
UPLOAD_DIR = get_storage_path("uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# State manager class
class CampaignManager:
    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.log_queue = queue.Queue()
        self.progress_percent = 0
        self.total_contacts = 0
        self.sent_count = 0
        self.failed_count = 0
        self.sent_emails_file = get_storage_path("sent_emails.txt")
        self.logs_file = get_storage_path("campaign_logs.txt")
        
        # Configure logging to write to campaign_logs.txt
        self.logger = logging.getLogger("campaign")
        self.logger.setLevel(logging.INFO)
        # Clear existing handlers
        if self.logger.handlers:
            self.logger.handlers.clear()
            
        fh = logging.FileHandler(self.logs_file, mode="a", encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def add_log(self, message: str, level: str = "INFO"):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        self.log_queue.put(log_line)
        if level == "ERROR":
            self.logger.error(message)
        elif level == "WARNING":
            self.logger.warning(message)
        else:
            self.logger.info(message)

    def load_sent_emails(self) -> set[str]:
        if not os.path.exists(self.sent_emails_file):
            return set()
        try:
            with open(self.sent_emails_file, "r", encoding="utf-8") as f:
                return {line.strip().lower() for line in f if line.strip()}
        except Exception as e:
            self.add_log(f"Error loading sent list: {e}", "ERROR")
            return set()

    def mark_email_as_sent(self, email: str):
        try:
            with open(self.sent_emails_file, "a", encoding="utf-8") as f:
                f.write(email.strip().lower() + "\n")
        except Exception as e:
            self.add_log(f"Error saving to sent list: {e}", "ERROR")

    def parse_contacts(self, pdf_path: str) -> list[dict]:
        contacts = []
        seen_emails = set()
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            if not table or len(table) < 1:
                                continue
                            header = [str(c).lower().strip() if c else "" for c in table[0]]
                            email_idx, name_idx, company_idx = -1, -1, -1
                            
                            for idx, col_name in enumerate(header):
                                if "email" in col_name:
                                    email_idx = idx
                                elif "name" in col_name or "hr" in col_name:
                                    if name_idx == -1:
                                        name_idx = idx
                                elif "company" in col_name or "organization" in col_name or "firm" in col_name:
                                    company_idx = idx
                                    
                            if email_idx == -1 or name_idx == -1 or company_idx == -1:
                                num_cols = len(table[0])
                                if num_cols >= 5:
                                    name_idx, email_idx, company_idx = 1, 2, 4
                                elif num_cols >= 3:
                                    name_idx, company_idx, email_idx = 0, 1, 2
                                else:
                                    continue
                                    
                            for row_idx, row in enumerate(table):
                                if row_idx == 0 and any(h in "".join(header) for h in ["name", "email", "company", "hr", "sno"]):
                                    continue
                                row = [cell.strip() if cell else "" for cell in row]
                                if len(row) > max(email_idx, name_idx, company_idx):
                                    name = row[name_idx]
                                    email = row[email_idx]
                                    company = row[company_idx]
                                    email_clean = email.strip()
                                    if "@" in email_clean and email_clean not in seen_emails:
                                        contacts.append({
                                            "name": name.strip(),
                                            "company": company.strip(),
                                            "email": email_clean
                                        })
                                        seen_emails.add(email_clean)
                        continue
                        
                    # Text fallback
                    text = page.extract_text()
                    if not text:
                        continue
                    for line in text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        for sep in [",", "|", ";", "\t"]:
                            parts = [p.strip() for p in line.split(sep)]
                            if len(parts) >= 3 and "@" in parts[2]:
                                name, company, email = parts[0], parts[1], parts[2]
                                if email not in seen_emails:
                                    contacts.append({"name": name, "company": company, "email": email})
                                    seen_emails.add(email)
                                break
                            elif len(parts) >= 3 and "@" in parts[1]:
                                name, email, company = parts[0], parts[1], parts[2]
                                if email not in seen_emails:
                                    contacts.append({"name": name, "company": company, "email": email})
                                    seen_emails.add(email)
                                break
        except Exception as e:
            self.add_log(f"PDF Parsing error: {e}", "ERROR")
        return contacts

campaign = CampaignManager()

def build_message(sender_email: str, to_email: str, hr_name: str, company_name: str, subject: str, body_template: str, resume_path: Optional[str]) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject

    # Personalize text
    personalized_body = body_template.replace("{hr_name}", hr_name).replace("{company_name}", company_name)
    
    # We can automatically construct a clean HTML fallback by converting line breaks to <p>
    html_content = personalized_body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; font-size: 15px; color: #222; line-height: 1.7;">
  <p>{html_content}</p>
</body>
</html>"""

    body_alt = MIMEMultipart("alternative")
    part_plain = MIMEText(personalized_body, "plain", "utf-8")
    part_html = MIMEText(html_body, "html", "utf-8")
    body_alt.attach(part_plain)
    body_alt.attach(part_html)
    msg.attach(body_alt)

    # Attach resume
    if resume_path and os.path.exists(resume_path):
        with open(resume_path, "rb") as f:
            attachment = MIMEBase("application", "octet-stream")
            attachment.set_payload(f.read())
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(resume_path)}"',
        )
        msg.attach(attachment)
    return msg

# Campaign worker thread target
def run_campaign_worker(
    sender_email: str,
    app_password: str,
    pdf_path: str,
    resume_path: Optional[str],
    subject: str,
    body_template: str,
    delay_min: int,
    delay_max: int,
    dry_run: bool = False
):
    sender_email = sender_email.strip()
    app_password = app_password.strip()
    
    campaign.is_running = True
    campaign.should_stop = False
    campaign.progress_percent = 0
    campaign.sent_count = 0
    campaign.failed_count = 0
    
    campaign.add_log("Starting campaign initialization...")
    contacts = campaign.parse_contacts(pdf_path)
    campaign.total_contacts = len(contacts)
    
    if campaign.total_contacts == 0:
        campaign.add_log("No contacts parsed from PDF contacts file.", "ERROR")
        campaign.is_running = False
        return
        
    sent_emails_db = campaign.load_sent_emails()
    pending = [c for c in contacts if c["email"].lower() not in sent_emails_db]
    
    campaign.add_log(f"Parsed {campaign.total_contacts} contacts from PDF. Already sent: {len(sent_emails_db)}. Pending: {len(pending)}")
    
    if not pending:
        campaign.add_log("All contacts in the list have already received this email.", "WARNING")
        campaign.progress_percent = 100
        campaign.is_running = False
        return

    # Setup connection
    smtp = None
    if not dry_run:
        try:
            campaign.add_log("Establishing secure SMTP connection to smtp.gmail.com...")
            smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
            smtp.login(sender_email, app_password)
            campaign.add_log("Logged into Gmail SMTP successfully!")
        except Exception as e:
            campaign.add_log(f"SMTP Connection/Auth failed: {e}", "ERROR")
            campaign.is_running = False
            return

    for idx, contact in enumerate(pending):
        if campaign.should_stop:
            campaign.add_log("Campaign paused/stopped by user.", "WARNING")
            break
            
        hr_name = contact["name"]
        company = contact["company"]
        email = contact["email"]
        
        campaign.add_log(f"[{idx+1}/{len(pending)}] Sending email to {hr_name} | {company} | {email}...")
        
        if dry_run:
            time.sleep(1) # mock delay
            campaign.sent_count += 1
            campaign.mark_email_as_sent(email)
            campaign.add_log(f"[DRY-RUN OK] Mock sent to {hr_name} <{email}>")
        else:
            try:
                msg = build_message(sender_email, email, hr_name, company, subject, body_template, resume_path)
                smtp.sendmail(sender_email, email, msg.as_string())
                campaign.sent_count += 1
                campaign.mark_email_as_sent(email)
                campaign.add_log(f"[OK] Sent successfully to {hr_name} <{email}>")
            except Exception as e:
                campaign.failed_count += 1
                campaign.add_log(f"[FAIL] Could not send to {email}: {e}", "ERROR")
                
        # Calculate progress
        campaign.progress_percent = int(((idx + 1) / len(pending)) * 100)
        
        # Delay (skip on last item)
        if idx < len(pending) - 1 and not campaign.should_stop:
            delay = random.randint(delay_min, delay_max)
            campaign.add_log(f"Waiting {delay} seconds before next delivery...")
            
            # Sub-divided sleep to allow immediate pause/stop response
            for _ in range(delay):
                if campaign.should_stop:
                    break
                time.sleep(1)

    if smtp:
        try:
            smtp.quit()
        except:
            pass
            
    campaign.add_log(f"Campaign ended. Successfully sent: {campaign.sent_count} | Failed: {campaign.failed_count}")
    campaign.is_running = False

# API endpoints
@app.post("/api/upload")
async def upload_files(
    hr_list: Optional[UploadFile] = File(None),
    resume: Optional[UploadFile] = File(None)
):
    try:
        result = {"success": True}
        
        # Save HR List PDF if provided
        if hr_list:
            hr_path = os.path.join(UPLOAD_DIR, "hr_contacts.pdf")
            with open(hr_path, "wb") as buffer:
                buffer.write(await hr_list.read())
            # Parse to validate and return count
            contacts = campaign.parse_contacts(hr_path)
            result["contacts_found"] = len(contacts)
            result["hr_list_filename"] = hr_list.filename
            
        # Save Resume PDF if provided
        if resume:
            resume_path = os.path.join(UPLOAD_DIR, "resume.pdf")
            with open(resume_path, "wb") as buffer:
                buffer.write(await resume.read())
            result["resume_filename"] = resume.filename
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/start")
async def start_campaign(
    sender_email: str = Form(...),
    app_password: str = Form(...),
    subject: str = Form(...),
    body_template: str = Form(...),
    delay_min: int = Form(45),
    delay_max: int = Form(90),
    dry_run: bool = Form(False)
):
    if campaign.is_running:
        raise HTTPException(status_code=400, detail="Campaign is already running")
        
    hr_path = os.path.join(UPLOAD_DIR, "hr_contacts.pdf")
    resume_path = os.path.join(UPLOAD_DIR, "resume.pdf")
    if not os.path.exists(resume_path):
        resume_path = None
        
    if not os.path.exists(hr_path):
        raise HTTPException(status_code=400, detail="Please upload contacts list PDF first")
        
    # Start thread
    thread = threading.Thread(
        target=run_campaign_worker,
        args=(
            sender_email,
            app_password,
            hr_path,
            resume_path,
            subject,
            body_template,
            delay_min,
            delay_max,
            dry_run
        ),
        daemon=True
    )
    thread.start()
    return {"success": True, "message": "Campaign started"}

@app.post("/api/stop")
async def stop_campaign():
    if not campaign.is_running:
        return {"success": False, "message": "No campaign running"}
    campaign.should_stop = True
    return {"success": True, "message": "Stop signal sent to campaign runner"}

@app.get("/api/logs")
async def get_logs_stream():
    def log_event_generator():
        # Clear log queue at connection startup to only stream new items
        while not campaign.log_queue.empty():
            try:
                campaign.log_queue.get_nowait()
            except queue.Empty:
                break
                
        # Send initial status
        yield f"data: STATUS:{campaign.progress_percent},{campaign.sent_count},{campaign.failed_count},{campaign.is_running}\n\n"
        
        while True:
            # Check for new logs
            try:
                log_line = campaign.log_queue.get(timeout=1.0)
                # Escape newlines
                log_line_escaped = log_line.replace("\n", " ")
                yield f"data: LOG:{log_line_escaped}\n\n"
                # Push status updates with every log
                yield f"data: STATUS:{campaign.progress_percent},{campaign.sent_count},{campaign.failed_count},{campaign.is_running}\n\n"
            except queue.Empty:
                # Keep alive status beat
                yield f"data: STATUS:{campaign.progress_percent},{campaign.sent_count},{campaign.failed_count},{campaign.is_running}\n\n"
                
    return StreamingResponse(log_event_generator(), media_type="text/event-stream")

# Serve UI
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Error: index.html template file not found!</h3>"

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def open_browser():
    time.sleep(1.5)
    import webbrowser
    webbrowser.open("http://localhost:8000")

if __name__ == "__main__":
    import uvicorn
    # Create required directory structure if missing
    os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
    
    print("Dashboard server starting...")
    print("Opening http://localhost:8000 in your browser...")
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="localhost", port=8000, log_level="info")
