import time
from datetime import datetime
import pytz
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# Country → Timezone map
COUNTRY_TIMEZONE_MAP = {
    "BELGIUM": "Europe/Brussels",
    "BRAZIL": "America/Sao_Paulo",
    "CHINA": "Asia/Shanghai",
    "CZECH REPUBLIC": "Europe/Prague",
    "ENGLAND": "Europe/London",
    "FRANCE": "Europe/Paris",
    "GERMANY": "Europe/Berlin",
    "ITALY": "Europe/Rome",
    "NORWAY": "Europe/Oslo",
    "PORTUGAL": "Europe/Lisbon",
    "ROMANIA": "Europe/Bucharest",
    "SCOTLAND": "Europe/London",
    "SPAIN": "Europe/Madrid",
    "SWEDEN": "Europe/Stockholm",
    "UNITED ARAB EMIRATES": "Asia/Dubai",
    "USA": "America/New_York",
    "UZBEKISTAN": "Asia/Tashkent",
}

# Timezones used globally
UTC = pytz.utc
IST = pytz.timezone("Asia/Kolkata")


# Add year to date — always evaluated in UTC (matches GitHub Actions server time)
def add_year_to_date(date):
    today = datetime.now(UTC)          # ← UTC, consistent on all servers
    day, month_ = date.split(".")[:2]

    if int(month_) < today.month:
        year = today.year + 1
    else:
        year = today.year

    date_object = datetime.strptime(f"{day}/{month_}/{year}", "%d/%m/%Y")
    return date_object.strftime("%d %B %Y")


# Strip "Round " prefix but keep the rest (e.g. "Round 3" → "3", "Final" → "Final")
def clean_round(value):
    if not value:
        return value
    stripped = value.strip()
    if stripped.upper().startswith("ROUND "):
        return stripped[6:].strip()  # Remove "Round " (6 chars)
    return stripped


# Strip "League - " prefix from Competition.
# If the cleaned value still matches the league name exactly, return "Regular Season".
def clean_competition(value, league=""):
    if not value:
        return value
    s = str(value).strip()
    if " - " in s:
        s = s.split(" - ", 1)[1].strip()
    # If what remains is identical to the league name, it carries no extra info
    if league and s.lower() == str(league).strip().lower():
        return "Regular Season"
    # If no split happened and the whole value equals the league name, same fix
    if not league and s == str(value).strip():
        return s
    return s


# Convert UTC (scraped) → Local + IST + UTC string
# Soccerway serves times in UTC when running on GitHub Actions (server is UTC).
# Returns (local_date, local_time, ist_str, utc_str)
def convert_utc_to_local(date_str, time_str, country):

    if not date_str or not time_str or time_str.upper() == "FULL TIME":
        return "", "", "", ""

    try:
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%d %B %Y %H:%M")

        # Treat scraped time as UTC
        dt_utc = UTC.localize(dt_naive)

        # → IST
        dt_ist = dt_utc.astimezone(IST)
        ist_str = dt_ist.strftime("%d-%b-%Y %H:%M")

        # → UTC string (same format as IST for consistency)
        utc_str = dt_utc.strftime("%d-%b-%Y %H:%M")

        # → Country local time
        tz_name = COUNTRY_TIMEZONE_MAP.get(country.upper())
        if not tz_name:
            return "", "", ist_str, utc_str

        local_tz = pytz.timezone(tz_name)
        dt_local = dt_utc.astimezone(local_tz)

        return (
            dt_local.strftime("%d %B %Y"),
            dt_local.strftime("%H:%M"),
            ist_str,
            utc_str,
        )

    except:
        return "", "", "", ""


def scrape_url(league_name, url):

    data = []
    driver = None

    try:

        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")          # required on GitHub Actions (no display)
        options.add_argument("--no-sandbox")            # required in container/CI environments
        options.add_argument("--disable-dev-shm-usage") # prevents crashes on low /dev/shm
        options.add_argument("--disable-gpu")           # not needed headless, avoids warnings
        options.add_argument("--window-size=1920,1080") # replaces --start-maximized in headless

        driver = webdriver.Chrome(service=service, options=options)

        driver.get(url)
        driver.implicitly_wait(10)

        # Accept cookies
        try:
            accept_button = driver.find_element(By.XPATH, "//button[contains(text(),'Accept')]")
            accept_button.click()
        except:
            pass

        # League and Country
        league = ""
        country = ""

        try:
            league = driver.find_element(
                By.CSS_SELECTOR,
                "div.heading__title > div.heading__name"
            ).text

            country = driver.find_element(
                By.CSS_SELECTOR,
                "h2.breadcrumb > a.breadcrumb__link:last-of-type"
            ).text

        except:
            pass

        # Click show more
        def click_all_show_more_buttons():
            while True:
                try:
                    show_more_buttons = driver.find_elements(
                        By.XPATH,
                        "//a[contains(@class,'event__more')]"
                        " | //a[.//span[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more')]]"
                    )
                    visible_buttons = [b for b in show_more_buttons if b.is_displayed()]
                    if not visible_buttons:
                        break
                    for button in visible_buttons:
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                            time.sleep(0.4)
                            try:
                                ActionChains(driver).move_to_element(button).pause(0.15).click(button).perform()
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", button)
                                except Exception:
                                    driver.execute_script("""
                                        Array.from(document.querySelectorAll('div.zone__inner, .overlay, .onetrust-banner-sdk, header, .sticky, .sticky-header')).forEach(el=>{
                                            el.style.pointerEvents='none';
                                            el.style.visibility='hidden';
                                        });
                                    """)
                                    time.sleep(0.3)
                                    driver.execute_script("arguments[0].click();", button)
                            time.sleep(1.0)
                        except ElementClickInterceptedException:
                            driver.execute_script("""
                                Array.from(document.querySelectorAll('div.zone__inner, .overlay, .onetrust-banner-sdk, header, .sticky, .sticky-header')).forEach(el=>{
                                    el.style.pointerEvents='none';
                                    el.style.visibility='hidden';
                                });
                            """)
                            time.sleep(0.4)
                            try:
                                driver.execute_script("arguments[0].click();", button)
                                time.sleep(0.8)
                            except Exception as final_e:
                                print(f"Retry click failed for {league_name}: {final_e}")
                        except StaleElementReferenceException:
                            continue
                        except Exception as e:
                            print(f"Error clicking a 'Show more' button for {league_name}: {e}")
                    time.sleep(0.8)
                except Exception as e:
                    print(f"An error occurred while clicking 'Show More' buttons for {league_name}: {e}")
                    break

        click_all_show_more_buttons()

        # -----------------------------
        # Build Round mapping
        # -----------------------------
        round_map = {}
        current_round = ""

        elements = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'event__round')] | //a[contains(@class,'eventRowLink')]"
        )

        for el in elements:
            classes = el.get_attribute("class")

            if "event__round" in classes:
                current_round = el.text.strip()
                continue

            if "eventRowLink" in classes:
                link = el.get_attribute("href")
                round_map[link] = current_round

        # -----------------------------
        # Build Competition mapping (STABLE FIX)
        # -----------------------------
        competition_map = {}
        current_competition = ""
        
        # Wait until at least one competition is present
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".headerLeague__title-text"))
            )
        except:
            print(f"{league_name}: Competition headers not found")
        
        # Get all competitions (safe)
        competition_elements = driver.find_elements(By.CSS_SELECTOR, ".headerLeague__title-text")
        competition_list = [el.text.strip() for el in competition_elements if el.text.strip()]
        
        # Get all matches
        fixture_links = driver.find_elements(By.CSS_SELECTOR, "a.eventRowLink")
        
        # DEBUG
        print(f"{league_name} → Competitions: {len(competition_list)}, Matches: {len(fixture_links)}")
        
        # SAFE assignment (no division, no index crash)
        if not competition_list:
            # fallback → empty
            for link in fixture_links:
                competition_map[link.get_attribute("href")] = ""
        
        elif len(competition_list) == 1:
            # one competition → assign to all
            for link in fixture_links:
                competition_map[link.get_attribute("href")] = competition_list[0]
        
        else:
            # multiple competitions → distribute sequentially
            comp_index = 0
            change_points = len(fixture_links) // len(competition_list) or 1
        
            for i, link in enumerate(fixture_links):
        
                if i != 0 and i % change_points == 0 and comp_index < len(competition_list) - 1:
                    comp_index += 1
        
                competition_map[link.get_attribute("href")] = competition_list[comp_index]

        # -----------------------------
        # Extract matches
        # -----------------------------

        dates = driver.find_elements(By.CLASS_NAME, "event__time")

        home_teams = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'event__homeParticipant') or contains(@class,'event__participant--home')]"
        )

        away_teams = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'event__awayParticipant') or contains(@class,'event__participant--away')]"
        )

        fixture_links = driver.find_elements(By.CSS_SELECTOR, "a.eventRowLink")

        for date_elem, home_elem, away_elem, link_elem in zip(dates, home_teams, away_teams, fixture_links):

            date_time = date_elem.text.split(" ")

            date = add_year_to_date(date_time[0])
            time_ = date_time[1] if len(date_time) > 1 else ""

            home_team = home_elem.text
            away_team = away_elem.text

            fixture_page = link_elem.get_attribute("href")

            data.append({
                "Country": country,
                "League": league,
                "Competition": clean_competition(competition_map.get(fixture_page, ""), league),
                "Round": clean_round(round_map.get(fixture_page, "")),  # cleaned round
                "Date": date,
                "Time": time_,
                "Home Team": home_team,
                "Away Team": away_team,
                "Fixture Page": fixture_page
            })

    finally:
        if driver:
            driver.quit()

    return data


urls = {
    'England-WSL': 'https://www.soccerway.com/england/wsl/fixtures/',
}

all_data = []

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {
        executor.submit(scrape_url, k, v): k
        for k, v in urls.items()
    }

    for future in futures:
        result = future.result()
        if result:
            all_data.extend(result)

df = pd.DataFrame(all_data)

if df.empty:
    print("No data scraped.")
else:

    df["Local Date"], df["Local Time"], df["IST Time"], df["UTC Time"] = zip(
        *df.apply(
            lambda row: convert_utc_to_local(
                row["Date"], row["Time"], row["Country"]
            ),
            axis=1
        )
    )

    df = df[
        [
            "Country",
            "League",
            "Competition",
            "Round",
            "Local Date",
            "Local Time",
            "IST Time",      # UTC + 5:30
            "Home Team",
            "Away Team",
            "Fixture Page",
            "UTC Time",      # raw scraped time (server is UTC)
        ]
    ]

    df["__sort_datetime"] = pd.to_datetime(
        df["Local Date"] + " " + df["Local Time"],
        format="%d %B %Y %H:%M",
        errors="coerce"
    )

    df = df.sort_values(by="__sort_datetime").drop(columns=["__sort_datetime"])

    csv_file = "football_fixtures.csv"
    df.to_csv(csv_file, index=False)
    print(f"Data saved to {csv_file}")
