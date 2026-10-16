# Internship Automation MVP

Local-first React + Vite + Tailwind dashboard, FastAPI + SQLite backend, and a visible Playwright browser-preparation agent.

## Requirements
Windows 10/11, Python 3.11+ (3.12 recommended), Node.js 20+.

## Backend (PowerShell terminal 1)
```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
API docs: http://127.0.0.1:8000/docs

## Frontend (PowerShell terminal 2)
```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:5173

## Use
Add a job URL, title, company, description, location and verified pay status. The dashboard scores jobs and tracks status. Click Prepare to open a visible browser and attempt conservative autofill from `backend/profile.json`. Inspect every field and submit manually.

## Safety / limitations
This MVP does not scrape job boards or bypass login, CAPTCHA, access controls, or platform limits. Use saved searches, alerts, approved feeds/integrations, or manual job links. Browser autofill is heuristic and can be wrong; review everything. It never submits applications automatically. Keep personal data and resumes out of public Git repositories.
