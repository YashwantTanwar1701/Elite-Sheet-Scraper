import os
import time
import json
import base64
import re
from datetime import datetime, date as date_cls

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
SPREADSHEET_ID   = os.environ["SPREADSHEET_ID"]
WORKSHEET_NAME   = "Fixtures"
MAX_WORKERS      = 5
GOOGLE_CREDS_B64 = os.environ["GOOGLE_CREDENTIALS_B64"]

# ── TIMEZONES ─────────────────────────────────────────────────────────────────
UTC = pytz.utc
IST = pytz.timezone("Asia/Kolkata")

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

    'Brazil-Brasileiro Women': 'https://www.soccerway.com/brazil/brasileiro-women/fixtures/',
    'China-Super League': 'https://www.soccerway.com/china/super-league/fixtures/',
    'CZECH REPUBLIC-Chance Liga': 'https://www.soccerway.com/czech-republic/chance-liga/fixtures/',
    'England-EFL Cup': 'https://www.soccerway.com/england/efl-cup/fixtures/',
    'England-FA Cup': 'https://www.soccerway.com/england/fa-cup/fixtures/',
    'England-Premier League': 'https://www.soccerway.com/england/premier-league/fixtures/',
    'England-Womens League Cup': 'https://www.soccerway.com/england/women-s-league-cup/fixtures/',
    'England-WSL': 'https://www.soccerway.com/england/wsl/fixtures/',
    'England-Championship': 'https://www.soccerway.com/england/championship/fixtures/',
    'England-League One': 'https://www.soccerway.com/england/league-one/fixtures/',
    'England-League Two': 'https://www.soccerway.com/england/league-two/fixtures/',
    'England-Premier League U18': 'https://www.soccerway.com/england/premier-league-u18/fixtures/',
    'England-U23s Professional Development League': 'https://www.soccerway.com/england/professional-development-league/fixtures/',
    'Scotland-Premiership': 'https://www.soccerway.com/scotland/premiership/fixtures/',
    'Germany-Bundesliga': 'https://www.soccerway.com/germany/bundesliga/fixtures/',
    'Italy-Serie A': 'https://www.soccerway.com/italy/serie-a/fixtures/',
    'Italy-Serie B': 'https://www.soccerway.com/italy/serie-b/fixtures/',
    'Italy-Serie C - Group A': 'https://www.soccerway.com/italy/serie-c-group-a/fixtures/',
    'Italy-Serie C - Group B': 'https://www.soccerway.com/italy/serie-c-group-b/fixtures/',
    'Italy-Serie C - Group C': 'https://www.soccerway.com/italy/serie-c-group-c/fixtures/',
    'Italy-Serie C - Promotion - Play Offs': 'https://www.soccerway.com/italy/serie-c-promotion-play-offs/fixtures/#/Eu1PLKgD/draw/',
    'Italy-Serie C - Play Out': 'https://www.soccerway.com/italy/serie-c-play-out/fixtures/',
    'Norway-Division 1 Women': 'https://www.soccerway.com/norway/division-1-women/fixtures/',
    'Norway-Eliteserien': 'https://www.soccerway.com/norway/eliteserien/fixtures/',
    'Norway-NM Cupen': 'https://www.soccerway.com/norway/nm-cup/fixtures/',
    'Norway-OBOS-ligaen': 'https://www.soccerway.com/norway/obos-ligaen/fixtures/',
    'Norway-Toppserien Women': 'https://www.soccerway.com/norway/toppserien-women/fixtures/',
    'Portugal-Liga Portugal': 'https://www.soccerway.com/portugal/liga-portugal/fixtures/',
    'Romania-Superliga': 'https://www.soccerway.com/romania/superliga/fixtures/',
    'Spain-Liga F Women': 'https://www.soccerway.com/spain/liga-f-women/fixtures/',
    'Sweden-Allsvenskan Women': 'https://www.soccerway.com/sweden/allsvenskan-women/fixtures/',
    'Sweden-Elitettan Women': 'https://www.soccerway.com/sweden/elitettan-women/fixtures/',
    'UNITED ARAB EMIRATES-UAE League': 'https://www.soccerway.com/united-arab-emirates/uae-league/fixtures/',
    'USA-MLS': 'https://www.soccerway.com/usa/mls/fixtures/',
    'Uzbekistan-Super League': 'https://www.soccerway.com/uzbekistan/super-league/fixtures/'

}

# Columns written to the sheet — UTC Time added at end
SHEET_HEADERS = [
    "Country", "League", "Competition", "Round",
    "Local Date", "Local Time", "IST Time",
    "Home Team", "Away Team", "Fixture Page",
    "UTC Time",
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
    # Always use UTC so behaviour is identical locally and on GitHub Actions
    today = datetime.now(UTC)
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


def convert_utc_to_local_ist(date_str, time_str, country):
    """
    Soccerway serves times in UTC when running on a UTC server (GitHub Actions).
    Treats scraped time as UTC, derives:
      - Local Date / Local Time  (country timezone)
      - IST Time                 (UTC + 5:30), formatted dd-MMM-YYYY HH:MM
      - UTC Time                 (raw scraped), formatted dd-MMM-YYYY HH:MM
    Returns (local_date, local_time, ist_str, utc_str)
    """
    if not date_str or not time_str or time_str.upper() == "FULL TIME":
        return "", "", "", ""
    try:
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%d %B %Y %H:%M")
        dt_utc   = UTC.localize(dt_naive)

        # → IST
        ist_str  = dt_utc.astimezone(IST).strftime("%d-%b-%Y %H:%M")

        # → UTC string (same format)
        utc_str  = dt_utc.strftime("%d-%b-%Y %H:%M")

        # → Country local
        tz_name  = COUNTRY_TIMEZONE_MAP.get(country.strip().upper())
        if not tz_name:
            return "", "", ist_str, utc_str

        dt_local = dt_utc.astimezone(pytz.timezone(tz_name))
        return (
            dt_local.strftime("%d %B %Y"),
            dt_local.strftime("%H:%M"),
            ist_str,
            utc_str,
        )
    except Exception:
        return "", "", "", ""


def make_driver():
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

        try:
            driver.find_element(By.XPATH, "//button[contains(text(),'Accept')]").click()
            time.sleep(0.5)
        except Exception:
            pass

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
            print(f"[{league_name}] competition headers not found")

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
        dates         = driver.find_elements(By.CLASS_NAME, "event__time")
        home_teams    = driver.find_elements(By.XPATH, "//div[contains(@class,'event__homeParticipant') or contains(@class,'event__participant--home')]")
        away_teams    = driver.find_elements(By.XPATH, "//div[contains(@class,'event__awayParticipant') or contains(@class,'event__participant--away')]")
        fixture_links = driver.find_elements(By.CSS_SELECTOR, "a.eventRowLink")

        for date_el, home_el, away_el, link_el in zip(dates, home_teams, away_teams, fixture_links):
            raw      = date_el.text.split(" ")
            raw_date = raw[0]
            raw_time = raw[1] if len(raw) > 1 else ""

            if not re.match(r"^\d{1,2}:\d{2}$", raw_time):
                continue

            try:
                date_full = add_year_to_date(raw_date)
            except Exception:
                date_full = raw_date

            fixture_page = link_el.get_attribute("href") or ""

            data.append({
                "Country":      country,
                "League":       league,
                "Competition":  clean_competition(competition_map.get(fixture_page, ""), league),
                "Round":        clean_round(round_map.get(fixture_page, "")),
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

GS_EPOCH = date_cls(1899, 12, 30)


def to_date_serial(date_str):
    """'DD Month YYYY' → Google Sheets date serial."""
    try:
        d = datetime.strptime(date_str.strip(), "%d %B %Y")
        return (d.date() - GS_EPOCH).days
    except Exception:
        return None


def to_time_serial(time_str):
    """'HH:MM' → Google Sheets time serial (fraction of a day)."""
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M")
        return (t.hour * 3600 + t.minute * 60) / 86400.0
    except Exception:
        return None


def to_datetime_serial(dt_str):
    """'DD-Mon-YYYY HH:MM' → Google Sheets datetime serial."""
    try:
        dt = datetime.strptime(dt_str.strip(), "%d-%b-%Y %H:%M")
        return (dt.date() - GS_EPOCH).days + (dt.hour * 3600 + dt.minute * 60) / 86400.0
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

    # Column index reference (0-based within SHEET_HEADERS):
    #   4 = Local Date, 5 = Local Time, 6 = IST Time, 10 = UTC Time
    rows = [SHEET_HEADERS]
    for _, row in df.iterrows():
        r = [str(row.get(h, "") or "") for h in SHEET_HEADERS]

        local_date_serial = to_date_serial(row.get("Local Date", ""))
        local_time_serial = to_time_serial(row.get("Local Time", ""))
        ist_serial        = to_datetime_serial(row.get("IST Time", ""))
        utc_serial        = to_datetime_serial(row.get("UTC Time", ""))

        r[4]  = local_date_serial if local_date_serial is not None else r[4]   # Local Date
        r[5]  = local_time_serial if local_time_serial is not None else r[5]   # Local Time
        r[6]  = ist_serial        if ist_serial        is not None else r[6]   # IST Time
        r[10] = utc_serial        if utc_serial        is not None else r[10]  # UTC Time

        rows.append(r)

    end_col = chr(64 + len(SHEET_HEADERS))   # 'K' for 11 columns
    for i in range(0, len(rows), 500):
        chunk     = rows[i : i + 500]
        start_row = i + 1
        ws.update(
            f"A{start_row}:{end_col}{start_row + len(chunk) - 1}",
            chunk,
            value_input_option="USER_ENTERED",
        )
        time.sleep(1)

    total_rows = len(rows)

    # Number formats
    ws.format(f"E2:E{total_rows}", {"numberFormat": {"type": "DATE",      "pattern": "dd mmm yyyy"}})
    ws.format(f"F2:F{total_rows}", {"numberFormat": {"type": "TIME",      "pattern": "hh:mm"}})
    ws.format(f"G2:G{total_rows}", {"numberFormat": {"type": "DATE_TIME", "pattern": "dd mmm yyyy hh:mm"}})
    ws.format(f"K2:K{total_rows}", {"numberFormat": {"type": "DATE_TIME", "pattern": "dd mmm yyyy hh:mm"}})

    # Bold blue header
    ws.format(f"A1:{end_col}1", {
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

    # Convert UTC scraped times → Local, IST, UTC columns
    df["Local Date"], df["Local Time"], df["IST Time"], df["UTC Time"] = zip(
        *df.apply(
            lambda r: convert_utc_to_local_ist(r["Date"], r["Time"], r["Country"]),
            axis=1,
        )
    )

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
