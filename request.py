"""
Automated job application bot for ETS job postings.
Uses Discord for notifications and OpenAI's GPT-5-nano for job fit analysis.
"""

import json
import os
import subprocess
import textwrap
from time import sleep

import discord
import pandas as pd
import pyperclip
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

intents = discord.Intents.default()
intents.members = True


gpt_client = OpenAI()
discord_client: discord.Client = discord.Client(intents=intents)


class Buttons(discord.ui.View):
    """
    Discord UI View with a button to apply to a job posting.
    """

    def __init__(self, guid_string, *, timeout=180):
        super().__init__(timeout=timeout)
        self.guid_string = guid_string

    @discord.ui.button(style=discord.ButtonStyle.primary, label="Postuler")
    async def button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Event handler for when the apply button is clicked.
        Changes the button state to "Applied!" and disables it.
        """
        button.style = discord.ButtonStyle.green
        button.label = "Applied!"
        button.disabled = True
        await interaction.response.edit_message(view=self)

        apply(self.guid_string)


URL = "https://see.etsmtl.ca/Postes/Rechercher"

payload = {}
headers = {"Cookie": os.environ["COOKIE"]}


@discord_client.event
async def on_ready():
    """
    Event handler for when the Discord client is ready.
    Periodically fetches new job postings and sends them to a specified Discord channel.
    """
    await discord_client.wait_until_ready()
    channel = discord_client.get_channel(os.environ["DISCORD_CHANNEL_ID"])
    while True:
        for poste in fetch_postes():
            print(f"Found new poste:")
            if not poste:
                continue
            await channel.send(
                f"# New offer\n## {poste["Titpost"]}\n\n### Description\n{poste["summary"]}\n\n### Analysis\n{poste["analysis"]}"
                # textwrap.dedent(
                #     f"""# New offer
                # ## {poste["Titpost"]}
                # ### Description
                # {poste["summary"]}
                # ### Analysis
                # {poste["analysis"]}"""
                ,
                view=Buttons(guid_string=poste["GuidString"]),
            )
        print("Done checking for new postes.")
        sleep(60 * 10)  # Wait 10 minutes before checking again


def fetch_postes():
    """
    Fetch job postings from the ETS job board.
    Returns a list of new job postings that have not been seen before.
    Each posting is reviewed for fit using GPT-5-nano.
    """
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
            refresh_cookie()
            return fetch_postes()
    except requests.Timeout:
        print("Request timed out")
        return None

    postes = json.loads(request.text)["ListePostesAffichees"]

    # get known guids
    try:
        df_known = pd.read_csv("postes.csv")
        known_guids = set(df_known["GuidString"].tolist())
    except (FileNotFoundError, pd.errors.EmptyDataError):
        known_guids = set()
    # filter out known guids
    new_postes = [poste for poste in postes if poste["GuidString"] not in known_guids]

    # Add only new postes guids to CSV
    if new_postes:
        df_new = pd.DataFrame(new_postes)
        if known_guids:
            df_known = pd.read_csv("postes.csv")
            df_combined = pd.concat([df_known, df_new], ignore_index=True)
        else:
            df_combined = df_new
        df_combined.to_csv("postes.csv", index=False)

    return [review(poste) for poste in new_postes[:1]]


def apply(guid: str):
    """Apply to a job posting given its GUID."""
    print(f"Applying to job with GUID: {guid}")
    # try:
    #     request = requests.post(
    #         "https://see.etsmtl.ca/Postulation/Postuler",
    #         headers=headers,
    #         payload={"Postulant.Poste.Guid": guid, "password": os.environ["PASSWORD"]},
    #         timeout=10,
    #         accept_redirects=False,
    #     )
    #     if request.status_code == 403:
    #         print("ALREADY APPLIED OR EXTERNAL SITE")
    #     elif request.status_code != 200:
    #         print("COOKIE EXPIRED")
    #         refresh_cookie()
    #         return apply(guid)
    # except requests.Timeout:
    #     print("Request timed out")


def refresh_cookie():
    """
    Refresh the COOKIE environment variable.
    To avoid CAPTCHAs, this function uses ydotool to automate browser interactions.
    """
    subprocess.Popen(
        [
            "ydotoold",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.Popen(
        [
            "firefox",
            "--private-window",
            "--kiosk",
            "https://see.etsmtl.ca/Postes/Rechercher",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    sleep(5)  # Wait for the browser to open

    # Move the mouse to a safe location inside the screen (center-top)
    subprocess.check_call(["ydotool", "mousemove", "--absolute", "-x", "0", "-y", "0"])

    subprocess.check_call(
        ["ydotool", "type", os.environ["EMAIL"], "-d", "0", "-H", "0"]
    )

    subprocess.check_call(
        ["ydotool", "key", "15:1", "15:0"]  # Tab key press and release
    )

    subprocess.check_call(
        ["ydotool", "type", os.environ["PASSWORD"], "-d", "0", "-H", "0"]
    )

    subprocess.check_call(
        ["ydotool", "key", "28:1", "28:0"]  # Enter key press and release
    )

    sleep(5)

    subprocess.check_call(
        [
            "ydotool",
            "key",
            "15:1",
            "15:0",
            "15:1",
            "15:0",
            "15:1",
            "15:0",
            "15:1",
            "15:0",
        ]  # Tab key press and release
    )
    subprocess.check_call(
        ["ydotool", "key", "28:1", "28:0"]  # Enter key press and release
    )

    # Get code by using ykman oath accounts code ets

    sleep(5)

    subprocess.check_call(
        [
            "ydotool",
            "type",
            subprocess.run(
                ["ykman", "oath", "accounts", "code", "ets", "-s"],
                capture_output=True,
                check=True,
            )
            .stdout.decode("utf-8")
            .strip(),
            "-d",
            "0",
            "-H",
            "0",
        ]
    )

    subprocess.check_call(
        ["ydotool", "key", "28:1", "28:0"]  # Enter key press and release
    )

    sleep(5)

    # Shift+F9

    subprocess.check_call(
        [
            "ydotool",
            "key",
            "42:1",
            "67:1",
            "67:0",
            "42:0",
        ]
    )

    sleep(2)
    subprocess.check_call(["ydotool", "mousemove", "-x", "400", "-y", "687"])
    subprocess.check_call(["ydotool", "click", "0xC0", "-r", "2"])  # Left click

    # CTRL+C
    sleep(1)
    subprocess.check_call(
        [
            "ydotool",
            "key",
            "29:1",
            "30:1",
            "30:0",
            "46:1",
            "46:0",
            "29:0",
        ]
    )
    subprocess.run(
        ["ykman", "oath", "accounts", "code", "ets", "-s"],
        capture_output=True,
        check=True,
    )
    while not pyperclip.paste():
        subprocess.check_call("code")  # Dummy command to refresh clipboard
        sleep(3)

    new_cookie = pyperclip.paste()

    os.environ["COOKIE"] = ".ASPXAUTH=" + new_cookie

    headers["Cookie"] = os.environ["COOKIE"]

    with open(".env", "r+", encoding="UTF-8") as f:
        lines = f.readlines()
        f.seek(0)
        for line in lines:
            if line.startswith("COOKIE="):
                f.write(f"COOKIE='.ASPXAUTH={new_cookie}'\n")
            else:
                f.write(line)
        f.truncate()

    sleep(2)

    # ALT+F4 the code tab
    subprocess.check_call(
        [
            "ydotool",
            "key",
            "56:1",
            "62:1",
            "62:0",
            "56:0",
        ]
    )

    sleep(1)

    # ALT+F4 the browser
    subprocess.check_call(
        [
            "ydotool",
            "key",
            "56:1",
            "62:1",
            "62:0",
            "56:0",
        ]
    )

    sleep(2)


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

    # Send to GPT to determine fit
    gpt_response = json.loads(
        gpt_client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {
                    "role": "system",
                    "content": 'You are an automated job application assistant for ETS job postings. Remember the CV provided for future applications. You will be given internship offers that were scraped online, using the JSON resume provided later determine if the student would be a good fit for an entry level intern, Answer with 1 if yes and 0 if no and then a brief explanation in the following format:{"fit": 1,"analysis": "The student is a good fit because..."} If they are not at least 85% competent they will be injustly taking someone else\'s place since there is a limited amount of applicant spots so be very strict',  # pylint: disable=line-too-long
                },
                {
                    "role": "user",
                    "content": (
                        "Here is the CV to remember for future job applications:\n\n"
                        + os.environ["CV_JSON"]
                        + "\n\n"
                        + "Note that the applicant can only travel as far as these cities and their environs: Montreal, Laval, Quebec City, Trois-Rivières Terrebonne, Mirabel, Repentigny, Mascouche, St-Eustache."  # pylint: disable=line-too-long
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

    if gpt_response["fit"]:
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
                            "Summarize the following job posting in 4-5 concise sentences highlighting the key responsibilities and requirements:\n\n"  # pylint: disable=line-too-long
                            + description_div.get_text(separator="\n")
                        ),
                    },
                ],
            )
            .choices[0]
            .message.content
        )

        return {
            "Titpost": poste["Titpost"],
            "GuidString": poste["GuidString"],
            "analysis": gpt_response["analysis"],
            "summary": summary,
        }
    return None


if __name__ == "__main__":
    discord_client.run(
        os.environ["DISCORD_BOT_TOKEN"],
        log_handler=None,
    )
