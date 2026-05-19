# ⚽ Football Fixtures Scraper → Google Sheets (GitHub Actions)

Scrapes upcoming fixtures from Soccerway for 41 leagues and writes them
to a Google Sheet automatically every day at 06:00 IST.

---

## Files

```
scraper.py                        ← main script
requirements.txt                  ← Python dependencies
.github/workflows/scraper.yml     ← GitHub Actions schedule
```

---

## One-time setup (15 minutes)

### Step 1 — Google Sheets API credentials

1. Go to **https://console.cloud.google.com/**
2. Create a project (or pick an existing one)
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
   - Give it any name, finish the wizard
5. Click the service account → **Keys → Add Key → Create new key → JSON**
6. A `.json` file downloads — keep it safe, you'll need it in Step 3

### Step 2 — Share your Google Sheet

1. Create a new Google Sheet (or use an existing one)
2. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/<<THIS_IS_YOUR_ID>>/edit
   ```
3. Open the downloaded JSON from Step 1, find `"client_email"` — it looks like:
   ```
   something@your-project.iam.gserviceaccount.com
   ```
4. In your Google Sheet → **Share** → paste that email → give **Editor** access

### Step 3 — Add GitHub Secrets

In your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these two secrets:

**Secret 1: `SPREADSHEET_ID`**
```
Value: your Sheet ID from Step 2
```

**Secret 2: `GOOGLE_CREDENTIALS_B64`**

This is your credentials JSON encoded as base64. Run this in a terminal:

```bash
# Mac / Linux
base64 -i your-credentials-file.json | tr -d '\n'

# Windows PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("your-credentials-file.json"))
```

Paste the output as the secret value.

### Step 4 — Push to GitHub

```bash
git init
git add .
git commit -m "Add fixtures scraper"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Step 5 — Test it

Go to **Actions tab** in your repo → **Football Fixtures Scraper** → **Run workflow** → click the green button.

Watch the logs. After ~10–20 minutes your Google Sheet will be populated.

---

## Schedule

The workflow runs automatically at **06:00 IST every day** (00:30 UTC).

To change the time, edit `.github/workflows/scraper.yml`:
```yaml
- cron: "30 0 * * *"   # UTC time — 00:30 UTC = 06:00 IST
```
Use https://crontab.guru to build your cron expression.

---

## Running locally

To run on your own machine instead of GitHub Actions:

```bash
pip install -r requirements.txt

# Edit scraper.py → make_driver() → uncomment the webdriver_manager lines
# and comment out the plain Service() line

# Set env vars (Windows: use $env:VAR="value" in PowerShell)
export SPREADSHEET_ID="your-sheet-id"
export GOOGLE_CREDENTIALS_B64="$(base64 -i credentials.json | tr -d '\n')"

python scraper.py
```

---

## Google Sheets output columns

| Column       | Example                    |
|--------------|----------------------------|
| Country      | Romania                    |
| League       | Liga I                     |
| Competition  | Regular Season             |
| Round        | 8                          |
| Local Date   | 25 May 2026                |
| Local Time   | 20:00                      |
| IST Time     | 25-May-2026 22:30          |
| Home Team    | FCSB                       |
| Away Team    | CFR Cluj                   |
| Fixture Page | https://www.soccerway.com/...|
