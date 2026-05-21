import os
import time
import json
import base64
from datetime import datetime

import pytz
import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.action_chains import ActionChains
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

# ── CONFIG ────────────────────────────────────────────────────────────────────
# These are read from GitHub Actions secrets (set them in repo Settings → Secrets)
SPREADSHEET_ID   = os.environ["SPREADSHEET_ID"]       # your Google Sheet ID
WORKSHEET_NAME   = "Fixtures"
MAX_WORKERS      = 5

# Google credentials come in as a base64-encoded JSON secret
GOOGLE_CREDS_B64 = os.environ["GOOGLE_CREDENTIALS_B64"]

# ── TIMEZONE MAP ──────────────────────────────────────────────────────────────
COUNTRY_TIMEZONE_MAP = {
    "BELGIUM":              "Europe/Brussels",
    "BRAZIL":               "America/Sao_Paulo",
    "CHINA":                "Asia/Shanghai",
    "CZECH REPUBLIC":       "Europe/Prague",
    "ENGLAND":              "Europe/London",
    "FRANCE":               "Europe/Paris",
    "GERMANY":              "Europe/Berlin",
    "ITALY":                "Europe/Rome",
    "NORWAY":               "Europe/Oslo",
    "PORTUGAL":             "Europe/Lisbon",
    "ROMANIA":              "Europe/Bucharest",
    "SCOTLAND":             "Europe/London",
    "SPAIN":                "Europe/Madrid",
    "SWEDEN":               "Europe/Stockholm",
    "UNITED ARAB EMIRATES": "Asia/Dubai",
    "USA":                  "America/New_York",
    "UZBEKISTAN":           "Asia/Tashkent",
}

KEEP_UPPERCASE = {"USA", "UAE"}

# ── LEAGUES ───────────────────────────────────────────────────────────────────
URLS = {
    "Belgian Cup":                          "https://www.soccerway.com/belgium/belgian-cup/fixtures/",
    "First Division B":                     "https://www.soccerway.com/belgium/challenger-pro-league/fixtures/",
    "Jupiler Pro League":                   "https://www.soccerway.com/belgium/jupiler-pro-league/fixtures/",
    "Brasileiro Women":                     "https://www.soccerway.com/brazil/brasileiro-women/fixtures/",
    "Super League (China)":                 "https://www.soccerway.com/china/super-league/fixtures/",
    "Czech Cup":                            "https://www.soccerway.com/czech-republic/mol-cup/fixtures/",
    "Chance Liga":                          "https://www.soccerway.com/czech-republic/chance-liga/fixtures/",
    "EFL Cup":                              "https://www.soccerway.com/england/efl-cup/fixtures/",
    "FA Cup":                               "https://www.soccerway.com/england/fa-cup/fixtures/",
    "Premier League":                       "https://www.soccerway.com/england/premier-league/fixtures/",
    "Womens Champions League":              "https://www.soccerway.com/europe/champions-league-women/fixtures/",
    "Womens League Cup":                    "https://www.soccerway.com/england/women-s-league-cup/fixtures/",
    "WSL":                                  "https://www.soccerway.com/england/wsl/fixtures/",
    "Championship":                         "https://www.soccerway.com/england/championship/fixtures/",
    "League One":                           "https://www.soccerway.com/england/league-one/fixtures/",
    "League Two":                           "https://www.soccerway.com/england/league-two/fixtures/",
    "U18 Premier League":                   "https://www.soccerway.com/england/premier-league-u18/fixtures/",
    "Professional Development League":      "https://www.soccerway.com/england/professional-development-league/fixtures/",
    "Scottish Premiership":                 "https://www.soccerway.com/scotland/premiership/fixtures/",
    "Bundesliga":                           "https://www.soccerway.com/germany/bundesliga/fixtures/",
    "Serie A":                              "https://www.soccerway.com/italy/serie-a/fixtures/",
    "Serie B":                              "https://www.soccerway.com/italy/serie-b/fixtures/",
    "Serie C - Group A":                    "https://www.soccerway.com/italy/serie-c-group-a/fixtures/",
    "Serie C - Group B":                    "https://www.soccerway.com/italy/serie-c-group-b/fixtures/",
    "Serie C - Group C":                    "https://www.soccerway.com/italy/serie-c-group-c/fixtures/",
    "Serie C - Promotion Play Offs":        "https://www.soccerway.com/italy/serie-c-promotion-play-offs/fixtures/",
    "Serie C - Play Out":                   "https://www.soccerway.com/italy/serie-c-play-out/fixtures/",
    "1. Division Women (Norway)":           "https://www.soccerway.com/norway/division-1-women/fixtures/",
    "Eliteserien":                          "https://www.soccerway.com/norway/eliteserien/fixtures/",
    "NM Cupen":                             "https://www.soccerway.com/norway/nm-cup/fixtures/",
    "OBOS-ligaen":                          "https://www.soccerway.com/norway/obos-ligaen/fixtures/",
    "Toppserien Women":                     "https://www.soccerway.com/norway/toppserien-women/fixtures/",
    "Liga Portugal":                        "https://www.soccerway.com/portugal/liga-portugal/fixtures/",
    "LIGA I (Romania)":                     "https://www.soccerway.com/romania/superliga/fixtures/",
    "Liga F Women":                         "https://www.soccerway.com/spain/liga-f-women/fixtures/",
    "Damallsvenskan":                       "https://www.soccerway.com/sweden/allsvenskan-women/fixtures/",
    "Elitettan Women":                      "https://www.soccerway.com/sweden/elitettan-women/fixtures/",
    "UAE League":                           "https://www.soccerway.com/united-arab-emirates/uae-league/fixtures/",
    "MLS":                                  "https://www.soccerway.com/usa/mls/fixtures/",
    "Super League (Uzbekistan)":            "https://www.soccerway.com/uzbekistan/super-league/fixtures/",
}

SHEET_HEADERS = [
    "Country", "League", "Competition", "Round",
    "Local Date", "Local Time", "IST Time",
    "Home Team", "Away Team", "Fixture Page",
]

# ── HELPERS ───────────────────────────────────────────────────────────────────

def format_country(name):
    if not name:
        return name
    upper = name.strip().upper()
    if upper in KEEP_UPPERCASE:
        return upper
    return name.strip().title()


def add_year_to_date(date):
    today = datetime.now()
    day, month_ = date.split(".")[:2]
    year = today.year + 1 if int(month_) < today.month else today.year
    return datetime.strptime(f"{day}/{month_}/{year}", "%d/%m/%Y").strftime("%d %B %Y")


def clean_round(value):
    if not value:
        return value
    s = value.strip()
    return s[6:].strip() if s.upper().startswith("ROUND ") else s


def clean_competition(value, league=""):
    if not value:
        return value
    s = str(value).strip()
    if " - " in s:
        s = s.split(" - ", 1)[1].strip()
    if league and s.lower() == league.strip().lower():
        return "Regular Season"
    return s


def convert_ist_to_local(date_str, time_str, country):
    if not date_str or not time_str or time_str.upper() == "FULL TIME":
        return "", ""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%d %B %Y %H:%M")
        ist_tz = pytz.timezone("Asia/Kolkata")
        dt = ist_tz.localize(dt)
        tz_name = COUNTRY_TIMEZONE_MAP.get(country.strip().upper())
        if not tz_name:
            return "", ""
        local_tz = pytz.timezone(tz_name)
        dt_local = dt.astimezone(local_tz)
        return dt_local.strftime("%d %B %Y"), dt_local.strftime("%H:%M")
    except Exception:
        return "", ""


def format_ist_datetime(date_str, time_str):
    if not date_str or not time_str:
        return ""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%d %B %Y %H:%M")
        return dt.strftime("%d-%b-%Y %H:%M")
    except Exception:
        return ""


def make_driver():
    """Headless Chrome for GitHub Actions (or local)."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # GitHub Actions has Chrome pre-installed; chromedriver is on PATH
    # For local use, uncomment the next two lines and comment out the plain Service()
    # from webdriver_manager.chrome import ChromeDriverManager
    # return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return webdriver.Chrome(service=Service(), options=options)


def click_all_show_more(driver, league_name):
    while True:
        try:
            buttons = driver.find_elements(
                By.XPATH,
                "//a[contains(@class,'event__more')]"
                " | //a[.//span[contains(translate(normalize-space(.),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show more')]]",
            )
            visible = [b for b in buttons if b.is_displayed()]
            if not visible:
                break
            for btn in visible:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.4)
                    try:
                        ActionChains(driver).move_to_element(btn).pause(0.15).click(btn).perform()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1.0)
                except (ElementClickInterceptedException, StaleElementReferenceException):
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.8)
                    except Exception as e:
                        print(f"[{league_name}] show-more click failed: {e}")
                except Exception as e:
                    print(f"[{league_name}] button error: {e}")
            time.sleep(0.8)
        except Exception as e:
            print(f"[{league_name}] show-more loop error: {e}")
            break


# ── SCRAPER ───────────────────────────────────────────────────────────────────

def scrape_url(league_name, url):
    data   = []
    driver = None
    try:
        driver = make_driver()
        driver.get(url)
        driver.implicitly_wait(10)

        # Cookie banner
        try:
            driver.find_element(By.XPATH, "//button[contains(text(),'Accept')]").click()
            time.sleep(0.5)
        except Exception:
            pass

        # League + country
        league  = league_name
        country = ""
        try:
            league = driver.find_element(
                By.CSS_SELECTOR, "div.heading__title > div.heading__name"
            ).text.strip() or league_name
            raw_country = driver.find_element(
                By.CSS_SELECTOR, "h2.breadcrumb > a.breadcrumb__link:last-of-type"
            ).text
            country = format_country(raw_country)
        except Exception:
            pass

        click_all_show_more(driver, league_name)

        # Round mapping
        round_map     = {}
        current_round = ""
        for el in driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'event__round')] | //a[contains(@class,'eventRowLink')]",
        ):
            cls = el.get_attribute("class") or ""
            if "event__round" in cls:
                current_round = el.text.strip()
            elif "eventRowLink" in cls:
                href = el.get_attribute("href")
                if href:
                    round_map[href] = current_round

        # Competition mapping
        competition_map = {}
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".headerLeague__title-text"))
            )
        except Exception:
            print(f"{league_name}: competition headers not found")

        comp_list     = [el.text.strip() for el in driver.find_elements(By.CSS_SELECTOR, ".headerLeague__title-text") if el.text.strip()]
        fixture_links = driver.find_elements(By.CSS_SELECTOR, "a.eventRowLink")

        print(f"[{league_name}] competitions={len(comp_list)}, matches={len(fixture_links)}")

        if not comp_list:
            for lnk in fixture_links:
                competition_map[lnk.get_attribute("href")] = ""
        elif len(comp_list) == 1:
            for lnk in fixture_links:
                competition_map[lnk.get_attribute("href")] = comp_list[0]
        else:
            comp_idx     = 0
            change_every = max(1, len(fixture_links) // len(comp_list))
            for i, lnk in enumerate(fixture_links):
                if i != 0 and i % change_every == 0 and comp_idx < len(comp_list) - 1:
                    comp_idx += 1
                competition_map[lnk.get_attribute("href")] = comp_list[comp_idx]

        # Extract matches
        dates      = driver.find_elements(By.CLASS_NAME, "event__time")
        home_teams = driver.find_elements(By.XPATH, "//div[contains(@class,'event__homeParticipant') or contains(@class,'event__participant--home')]")
        away_teams = driver.find_elements(By.XPATH, "//div[contains(@class,'event__awayParticipant') or contains(@class,'event__participant--away')]")
        fixture_links = driver.find_elements(By.CSS_SELECTOR, "a.eventRowLink")

        for date_el, home_el, away_el, link_el in zip(dates, home_teams, away_teams, fixture_links):
            raw = date_el.text.split(" ")
            raw_date, raw_time = raw[0], (raw[1] if len(raw) > 1 else "")

            # Skip finished matches (time replaced by score string)
            import re
            if not re.match(r"^\d{1,2}:\d{2}$", raw_time):
                continue

            try:
                date_full = add_year_to_date(raw_date)
            except Exception:
                date_full = raw_date

            fixture_page = link_el.get_attribute("href") or ""
            competition  = clean_competition(competition_map.get(fixture_page, ""), league)
            round_label  = clean_round(round_map.get(fixture_page, ""))

            data.append({
                "Country":      country,
                "League":       league,
                "Competition":  competition,
                "Round":        round_label,
                "Date":         date_full,
                "Time":         raw_time,
                "Home Team":    home_el.text.strip(),
                "Away Team":    away_el.text.strip(),
                "Fixture Page": fixture_page,
            })

    except Exception as e:
        print(f"[{league_name}] Fatal: {e}")
    finally:
        if driver:
            driver.quit()

    return data


# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────

def parse_to_serial(date_str, time_str=""):
    """Convert 'DD Month YYYY' + 'HH:MM' to a Google Sheets date/time serial number."""
    from datetime import date as date_cls
    GS_EPOCH = date_cls(1899, 12, 30)
    try:
        d = datetime.strptime(date_str.strip(), "%d %B %Y")
        date_serial = (d.date() - GS_EPOCH).days
        time_serial = 0.0
        if time_str and time_str.strip():
            t = datetime.strptime(time_str.strip(), "%H:%M")
            time_serial = (t.hour * 3600 + t.minute * 60) / 86400.0
        return date_serial, time_serial, date_serial + time_serial
    except Exception:
        return None, None, None


def parse_ist_serial(ist_str):
    """Convert 'DD-Mon-YYYY HH:MM' to a Google Sheets datetime serial number."""
    from datetime import date as date_cls
    GS_EPOCH = date_cls(1899, 12, 30)
    try:
        dt = datetime.strptime(ist_str.strip(), "%d-%b-%Y %H:%M")
        date_serial = (dt.date() - GS_EPOCH).days
        time_serial = (dt.hour * 3600 + dt.minute * 60) / 86400.0
        return date_serial + time_serial
    except Exception:
        return None


def write_to_sheets(df):
    creds_json = json.loads(base64.b64decode(GOOGLE_CREDS_B64).decode("utf-8"))
    creds      = Credentials.from_service_account_info(
        creds_json,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    sh     = client.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=5000, cols=len(SHEET_HEADERS))

    ws.clear()

    # Build rows — E=Local Date, F=Local Time, G=IST Time written as numeric serials
    rows = [SHEET_HEADERS]
    for _, row in df.iterrows():
        r = [str(row.get(h, "") or "") for h in SHEET_HEADERS]

        date_serial, time_serial, _ = parse_to_serial(
            row.get("Local Date", ""), row.get("Local Time", "")
        )
        ist_serial = parse_ist_serial(row.get("IST Time", ""))

        # Col E (index 4) = Local Date
        r[4] = date_serial  if date_serial  is not None else r[4]
        # Col F (index 5) = Local Time
        r[5] = time_serial  if time_serial  is not None else r[5]
        # Col G (index 6) = IST Time
        r[6] = ist_serial   if ist_serial   is not None else r[6]

        rows.append(r)

    # Write using USER_ENTERED so Sheets interprets numeric serials as dates
    for i in range(0, len(rows), 500):
        chunk     = rows[i : i + 500]
        start_row = i + 1
        end_col   = chr(64 + len(SHEET_HEADERS))
        ws.update(
            f"A{start_row}:{end_col}{start_row + len(chunk) - 1}",
            chunk,
            value_input_option="USER_ENTERED",
        )
        time.sleep(1)

    total_rows = len(rows)

    # Apply date/time number formats to columns E, F, G
    ws.format(f"E2:E{total_rows}", {"numberFormat": {"type": "DATE",      "pattern": "dd mmm yyyy"}})
    ws.format(f"F2:F{total_rows}", {"numberFormat": {"type": "TIME",      "pattern": "hh:mm"}})
    ws.format(f"G2:G{total_rows}", {"numberFormat": {"type": "DATE_TIME", "pattern": "dd mmm yyyy hh:mm"}})

    # Bold blue header row
    ws.format("A1:J1", {
        "textFormat":      {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.08, "green": 0.40, "blue": 0.75},
    })

    print(f"\n✅ {len(df)} fixtures written to Google Sheets → '{WORKSHEET_NAME}' tab.")



# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    all_data = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scrape_url, k, v): k for k, v in URLS.items()}
        for future in futures:
            result = future.result()
            if result:
                all_data.extend(result)

    if not all_data:
        print("No fixtures scraped.")
        return

    df = pd.DataFrame(all_data)

    # Add IST Time and Local Date/Time columns
    df["Local Date"], df["Local Time"] = zip(
        *df.apply(lambda r: convert_ist_to_local(r["Date"], r["Time"], r["Country"]), axis=1)
    )
    df["IST Time"] = df.apply(lambda r: format_ist_datetime(r["Date"], r["Time"]), axis=1)

    df = df[SHEET_HEADERS]

    # Sort by local datetime
    df["__sort"] = pd.to_datetime(
        df["Local Date"] + " " + df["Local Time"], format="%d %B %Y %H:%M", errors="coerce"
    )
    df = df.sort_values("__sort").drop(columns=["__sort"])

    print(f"\n{len(df)} fixtures scraped across {len(URLS)} leagues.")
    write_to_sheets(df)


if __name__ == "__main__":
    main()
