"""
Automated job application bot for ETS job postings.
Uses Discord for notifications and OpenAI's GPT-5-nano for job fit analysis.
"""

import json
import os
import subprocess
from datetime import datetime
import asyncio
import time

import discord
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait, TimeoutException
from selenium.webdriver import Keys, ActionChains
from selenium.webdriver.chrome.service import Service
import aiohttp

intents = discord.Intents.default()
intents.members = True


gpt_client = OpenAI()
discord_client: discord.Client = discord.Client(intents=intents)


options = webdriver.ChromeOptions()
options.binary_location = "/usr/bin/chromium"  # Debian/Ubuntu chromium path
options.add_argument("--headless=new")  # more reliable in recent Chrome
options.add_argument("--no-sandbox")  # required in most containers
options.add_argument("--disable-dev-shm-usage")  # avoid /dev/shm issues
options.add_argument("--disable-gpu")  # harmless on Linux/headless
options.add_argument("--disable-software-rasterizer")
options.add_argument("--incognito")

# If chromium-driver is installed by apt, it’s usually here:
service = Service(executable_path="/usr/bin/chromedriver")


class Buttons(discord.ui.View):
    """
    Discord UI View with a button to apply to a job posting.
    """

    def __init__(self, guid_string, *, timeout=None):
        super().__init__(timeout=timeout)
        self.guid_string = guid_string

    @discord.ui.button(style=discord.ButtonStyle.primary, label="Postuler")
    async def button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Event handler for when the apply button is clicked.
        Changes the button state to "Applied!" and disables it.
        """
        # call async apply directly (network won't block event loop)
        response = await apply(self.guid_string)
        print("Apply response:", response)
        if response is None:
            button.style = discord.ButtonStyle.green
            button.label = "Applied!"
            button.disabled = True
        else:
            button.style = discord.ButtonStyle.red
            button.label = response
            button.disabled = response == "ALREADY APPLIED OR EXTERNAL SITE"
            if button.disabled:
                # send the offer url for manual application
                await interaction.user.send(
                    f"Please apply manually to the offer here: https://see.etsmtl.ca/Poste/{self.guid_string}"
                )
        await interaction.response.edit_message(view=self)


URL = "https://see.etsmtl.ca/Postes/Rechercher"

payload = {}
headers = {"Cookie": os.environ["COOKIE"]}
POSTES_PATH = os.getenv("POSTES_PATH", "postes.csv")

COOKIE_REFRESHED = False
COOKIE_INVALID_AT = 0.0
COOKIE_LAST_REFRESH = 0.0
COOKIE_LIFETIME = 5 * 3600  # 5 hours
REFRESH_COOLDOWN = 60 * 2  # don't retry refresh more than once every 2 minutes
MIN_INTERVAL = os.environ.get("DELAY", 60 * 10)  # default to 10 minutes
MAX_BACKOFF = 6


@discord_client.event
async def on_ready():
    """
    Event handler for when the Discord client is ready.
    Periodically fetches new job postings and sends them to a specified Discord channel.
    """
    await discord_client.wait_until_ready()
    channel = discord_client.get_channel(int(os.environ["DISCORD_CHANNEL_ID"]))
    await channel.send(
        f"Hello world, i have seen {len(pd.read_csv(POSTES_PATH)) if os.path.exists(POSTES_PATH) else 0} offers so far"
    )
    lock = asyncio.Lock()

    async def background_checker():
        while True:
            try:
                # initial fetch (run blocking work in a thread)
                async with lock:
                    postes = await asyncio.to_thread(fetch_postes)

                # send any new posts
                for poste in postes or []:
                    if not poste:
                        continue
                    await channel.send(
                        f'{f"<@&{int(os.environ["DISCORD_ROLE_ID"])}>" if os.environ.get("DISCORD_ROLE_ID") else ""}\n# New offer\n## {poste["Titpost"]}#\n\n## Description\n{poste["summary"]}\n\n{f"### Analysis\n{poste["analysis"]}" if os.environ.get("CV_JSON") else f"https://see.etsmtl.ca/Poste/{poste["GuidString"]}"}',
                        view=(
                            Buttons(guid_string=poste["GuidString"])
                            if os.environ.get("CV_JSON")
                            else None
                        ),
                    )

                sleep_time = MIN_INTERVAL

                # If a cookie refresh was triggered, ensure we haven't refreshed too recently,
                # run the heavy UI automation in a thread, and immediately re-run fetch_postes.
                if globals().get("COOKIE_REFRESHED"):
                    now = time.time()
                    last = globals().get("COOKIE_LAST_REFRESH", 0.0)
                    if now - last > REFRESH_COOLDOWN:
                        try:
                            # mark refresh-in-progress to avoid duplicate concurrent refreshes
                            globals()["COOKIE_REFRESHED"] = False
                            globals()["COOKIE_LAST_REFRESH"] = now

                            # do the UI automation in a background thread
                            await asyncio.to_thread(refresh_cookie)
                            globals()["COOKIE_LAST_REFRESH"] = time.time()

                            # immediately re-fetch under lock so we don't delay processing
                            async with lock:
                                postes_after = await asyncio.to_thread(fetch_postes)

                            for poste in postes_after or []:
                                if not poste:
                                    continue
                                await channel.send(
                                    f'{f"<@&{int(os.environ["DISCORD_ROLE_ID"])}>" if os.environ.get("DISCORD_ROLE_ID") else ""}\n# New offer\n## {poste["Titpost"]}#\n\n## Description\n{poste["summary"]}\n\n{f"### Analysis\n{poste["analysis"]}" if os.environ.get("CV_JSON") else f"https://see.etsmtl.ca/Poste/{poste["GuidString"]}"}',
                                    view=(
                                        Buttons(guid_string=poste["GuidString"])
                                        if os.environ.get("CV_JSON")
                                        else None
                                    ),
                                )

                            sleep_time = MIN_INTERVAL
                        except Exception as e:
                            print("refresh_cookie failed:", e)
                            # if refresh failed, keep COOKIE_REFRESHED True so we can retry later
                            globals()["COOKIE_REFRESHED"] = True
                            sleep_time = MIN_INTERVAL
                    else:
                        # Too soon to attempt another refresh; wait normally
                        sleep_time = MIN_INTERVAL

            except Exception as e:
                print("Error in background_checker:", e)
                sleep_time = MIN_INTERVAL

            print("waiting for delay")
            await asyncio.sleep(sleep_time)

    asyncio.create_task(background_checker())


def fetch_postes():
    """
    Fetch job postings from the ETS job board.
    Returns a list of new job postings that have not been seen before.
    Each posting is reviewed for fit using GPT-5-nano.
    """
    print(f"{datetime.now()} Fetching job postings...")
    try:
        request = requests.request(
            "GET",
            URL,
            headers=headers,
            data=payload,
            timeout=10,
            allow_redirects=False,
        )
        if request.status_code != 200:
            print("COOKIE EXPIRED")
            # signal that a cookie refresh is needed, avoid doing UI automation on the event loop
            globals()["COOKIE_REFRESHED"] = True
            globals()["COOKIE_INVALID_AT"] = time.time()
            return None
    except requests.Timeout:
        print("Request timed out")
        return None

    postes = json.loads(request.text)["ListePostesAffichees"]

    # get known guids
    try:
        df_known = pd.read_csv(POSTES_PATH)
        known_guids = set(df_known["GuidString"].tolist())
    except (FileNotFoundError, pd.errors.EmptyDataError):
        known_guids = set()
    # filter out known guids
    new_postes = [poste for poste in postes if poste["GuidString"] not in known_guids]

    # Add only new postes guids to CSV
    if new_postes:
        df_new = pd.DataFrame(new_postes)
        if known_guids:
            df_known = pd.read_csv(POSTES_PATH)
            df_combined = pd.concat([df_known, df_new], ignore_index=True)
        else:
            df_combined = df_new
        df_combined.to_csv(POSTES_PATH, index=False)
    return [review(poste) for poste in new_postes]


async def apply(guid: str):
    """Async apply using aiohttp. If cookie looks expired, run refresh_cookie() in a thread and retry once."""
    print(f"Applying to job with GUID: {guid}")
    url = "https://see.etsmtl.ca/Postulation/Postuler"
    data = {"Postulant.Poste.Guid": guid, "password": os.environ["PASSWORD"]}

    # One session per call is OK; you can hoist a ClientSession if you prefer reuse.
    async with aiohttp.ClientSession(headers=headers) as session:
        attempts = 0
        while attempts < 2:
            attempts += 1
            try:
                async with session.post(
                    url, data=data, timeout=30, allow_redirects=False
                ) as resp:
                    print(resp.status)
                    if resp.status == 403:
                        print("ALREADY APPLIED OR EXTERNAL SITE")
                        return "ALREADY APPLIED OR EXTERNAL SITE"
                    if resp.status != 200:
                        print("COOKIE EXPIRED")
                        # signal that a cookie refresh is needed, avoid doing UI automation on the event loop
                        globals()["COOKIE_REFRESHED"] = True
                        globals()["COOKIE_INVALID_AT"] = time.time()
                        continue
                    else:
                        print(f"Applied to offer {guid}")
                        return
            except asyncio.TimeoutError:
                print("Request timed out")
                return "Please try again later"
    print("Failed to apply after retry")
    return "Please try again later"


def refresh_cookie():
    """
    Refresh the COOKIE environment variable.
    To avoid CAPTCHAs, this function uses ydotool to automate browser interactions.
    """

    # Open the browser to the api url
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(5)
    driver.get("https://see.etsmtl.ca/Postes/Rechercher")

    # # Enter the email and passwords from environment
    ActionChains(
        driver,
    ).send_keys(
        os.environ["EMAIL"]
    ).send_keys(Keys.TAB).send_keys(
        os.environ["PASSWORD"]
    ).send_keys(Keys.ENTER).perform()

    wait = WebDriverWait(driver, timeout=10)
    wait.until(lambda _: driver.find_element(By.ID, "linksDiv").is_displayed())

    # navigate to "Use verification code from mobile app or hardware token" option
    ActionChains(driver).send_keys(Keys.TAB * 4).send_keys(Keys.ENTER).perform()

    # Get 2FA code
    yk_code = (
        subprocess.run(
            ["ykman", "oath", "accounts", "code", os.environ.get("ACCOUNT","ets"), "-s"],
            capture_output=True,
            check=True,
        )
        .stdout.decode("utf-8")
        .strip()
    )

    wait = WebDriverWait(driver, timeout=10)
    wait.until(
        lambda _: driver.find_element(By.ID, "verificationCodeInput").is_displayed()
    )

    ActionChains(driver).send_keys(yk_code).send_keys(Keys.ENTER).perform()

    try:
        # wait until the request has resolved (in chromium browsers this implies the precense of a <pre> tag)
        wait = WebDriverWait(driver, timeout=20)
        wait.until(lambda _: driver.find_element(By.TAG_NAME, "pre").is_displayed())
    except TimeoutException:
        driver.close()
        return

    # Retrieve ".ASPXAUTH" Cookie\

    new_cookie = driver.get_cookie(".ASPXAUTH")["value"]
    print(new_cookie)

    os.environ["COOKIE"] = ".ASPXAUTH=" + new_cookie

    headers["Cookie"] = os.environ["COOKIE"]

    driver.quit()


def review(poste: dict):
    """
    Review a job posting to determine if it is a good fit for the applicant.
    1. Fetch the full job description.
    2. Send the description and the applicant's CV to GPT-5-nano for analysis.
    """

    print(f"Reviewing job: {poste['Titpost']}")

    url = f"https://see.etsmtl.ca/Poste/{poste['GuidString']}"
    poste_page = requests.get(url, headers=headers, timeout=10).text
    soup = BeautifulSoup(poste_page, "html.parser")
    description_div = soup.find("div", id="etsMCContent")

    if os.environ.get("CV_JSON"):
        # Send to GPT to determine fit
        gpt_response = json.loads(
            gpt_client.chat.completions.create(
                model="gpt-5-nano",
                messages=[
                    {
                        "role": "system",
                        "content": 'You are an automated job application assistant for ETS job postings. Remember the CV provided for future applications. You will be given internship offers that were scraped online, using the JSON resume provided later determine if the student would be a good fit for an entry level intern, Answer with 1 if yes and 0 if no and then a brief explanation (<400 char) in the following format:{"fit": 1,"analysis": "The student is a good fit because..."} If they are not at least 60% competent they will be injustly taking someone else\'s place since there is a limited amount of applicant spots so be very strict',  # pylint: disable=line-too-long
                    },
                    {
                        "role": "user",
                        "content": (
                            "Here is the CV to remember for future job applications:\n\n"
                            + os.environ["CV_JSON"]
                            + "\n\n"
                            + "Note that the applicant can only travel as far as these cities and their environs: Montreal, Laval, Quebec City, Trois-Rivières Terrebonne, Mirabel, Repentigny, Mascouche, St-Eustache. He does not have means of travel to the rive-sud of quebec so cities like boucherville arre out of his reach."  # pylint: disable=line-too-long
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Here is a new job posting description:\n\n"
                            + description_div.get_text(separator="\n")
                            + "\n\nBased on the CV I provided you earlier, determine if the student would be a good fit for this position."  # pylint: disable=line-too-long
                        ),
                    },
                ],
            )
            .choices[0]
            .message.content
        )

        print(
            f"{'Good fit' if gpt_response['fit'] else 'Not a good fit'} for job: {poste['Titpost']}"
        )

    # Summary of offer to send to discord for final review
    summary = (
        gpt_client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {
                    "role": "system",
                    "content": "You are an automated assistant that summarizes job postings for easy review.",  # pylint: disable=line-too-long
                },
                {
                    "role": "user",
                    "content": (
                        "Summarize the following job posting in 3-4 concise sentences (<600 char) highlighting the key responsibilities and requirements:\n\n"  # pylint: disable=line-too-long
                        + description_div.get_text(separator="\n")
                    ),
                },
            ],
        )
        .choices[0]
        .message.content
    )

    return (
        {
            "Titpost": poste["Titpost"],
            "GuidString": poste["GuidString"],
            "analysis": gpt_response["analysis"],
            "summary": summary,
        }
        if os.environ.get("CV_JSON")
        else {
            "Titpost": poste["Titpost"],
            "GuidString": poste["GuidString"],
            "summary": summary,
        }
    )


if __name__ == "__main__":
    discord_client.run(
        os.environ["DISCORD_BOT_TOKEN"],
        log_handler=None,
    )
