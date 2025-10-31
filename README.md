# Stage Alert Async

## Overview
Stage Alert Async is an automated job application bot designed to interact with job postings from the ETS job board. It utilizes asynchronous programming to ensure efficient and non-blocking operations, providing timely notifications and application capabilities through Discord.

## Features
- **Asynchronous Job Fetching**: Efficiently fetches job postings without blocking the main application flow.
- **Discord Integration**: Sends notifications and job postings directly to a specified Discord channel.
- **GPT Integration**: Analyzes job postings against the applicant's CV using OpenAI's GPT model to determine fit.
- **Cookie Management**: Automates the refreshing of session cookies to maintain authentication with the job board.

## Project Structure
```
stage_alert
├── request.py
├── .env.example
├── Pipfile
├── Pipfile.lock
├── .gitignore
└── README.md
```

## Installation
1. Clone the repository:
   ```
   git clone <repository-url>
   cd stage_alert
   ```

2. Create a virtual environment and activate it:
   ```
   pipenv lock
   pipenv sync
   ```

3. Set up your environment variables by copying `.env.example` to `.env` and filling in the required values.

## Usage
Ensure you have ydotool installed and the daemon is running
```
sudo apt install ydotool
ydotoold
```

To run the bot, execute the following command:
```
pipenv run python bot.py
```