# CNU Computer & Artificial Intelligence Department Notice Notifier

This project automatically checks 4 notice boards from the Chungnam National University (CNU) Computer & Artificial Intelligence Department website every day and sends new notices to Telegram.

Since it runs using GitHub Actions free cron jobs, notifications will still arrive even if your personal PC is turned off.

---

# Initial Setup

## Step 1: Create a Telegram Bot

1. Search for `@BotFather` in Telegram and start a chat
2. Send `/newbot`
3. Enter your bot name (example: `CNU Notice Notifier`)
4. Enter a bot username (example: `cnu_notice_dmsak_bot`)

   * It must end with `bot`
5. Copy the token provided by BotFather. It looks like this:

```plaintext id="zjlwmq"
7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Step 2: Find Your chat_id

1. Open a chat with the bot you just created and send `/start`
2. Open the following URL in your browser
   (replace `<BOT_TOKEN>` with the token from Step 1):

```plaintext id="fwznho"
https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
```

3. In the JSON response, find:

```json id="wx81eh"
"chat":{"id":123456789,...}
```

The number is your `chat_id`.

Example:

```plaintext id="6mn1h6"
123456789
```

If `result` is empty:

* send `/start` to the bot again
* refresh the page

---

## Step 3: Create a GitHub Repository

1. Sign up at [GitHub](https://github.com?utm_source=chatgpt.com) if you do not already have an account

2. Create a new repository at [Create New Repository](https://github.com/new?utm_source=chatgpt.com)

   * Repository name: `cnu-notice-bot` (any name is fine)
   * `Private` recommended
   * Uncheck `"Add a README file"`

3. Initialize git and push from this folder:

```powershell id="n64jsr"
cd C:\Users\dmsak\cnu-notice-bot
git init
git add .
git commit -m "init: cnu notice bot"
git branch -M main
git remote add origin https://github.com/<USERNAME>/cnu-notice-bot.git
git push -u origin main
```

Replace `<USERNAME>` with your GitHub username.

---

## Step 4: Add GitHub Secrets

1. Open your repository page
2. Go to:

   * `Settings`
   * `Secrets and variables`
   * `Actions`
3. Click `New repository secret` and add these two secrets:

| Name                 | Value                   |
| -------------------- | ----------------------- |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID`   | Your chat_id            |

---

## Step 5: First Test Run

1. Open the repository page
2. Go to the `Actions` tab
3. Select the `CNU Notice Notifier` workflow
4. Click:

   * `Run workflow`
   * then `Run workflow` again
5. Wait 1–2 minutes

The first run only initializes `seen.json` to prevent spam, so Telegram messages will not be sent yet.

Starting from the next run, new notices will automatically arrive on Telegram.

---

# How It Works

* **Schedule**: Runs every day at UTC 00:00 (= 9 AM Korea time)
* **Boards monitored**:

  * Academic Notices
  * General Campus News
  * External Activities / Internship / Jobs
  * Project & Center Notices
* **Detection method**:

  * Compares the latest `articleNo` with values stored in `seen.json`
* **State persistence**:

  * `seen.json` is automatically committed and pushed after each run
* **Message format**:

  * Grouped by board with title + date + link

---

# Local Testing

To test only the scraping logic:

```powershell id="h43trn"
cd C:\Users\dmsak\cnu-notice-bot
py -m pip install -r requirements.txt
$env:DRY_RUN="1"
py notify.py
```

With `DRY_RUN=1`, Telegram messages are skipped and output is printed to the console only.

To test actual Telegram delivery:

```powershell id="oktl8d"
$env:TELEGRAM_BOT_TOKEN="YOUR_TOKEN"
$env:TELEGRAM_CHAT_ID="YOUR_CHAT_ID"
py notify.py
```

---

# Changing the Schedule

Modify the cron value inside:

```plaintext id="ob4xgj"
.github/workflows/notify.yml
```

Cron uses UTC time.

Examples:

| Korea Time          | Cron          |
| ------------------- | ------------- |
| 8 AM                | `0 23 * * *`  |
| 12 PM               | `0 3 * * *`   |
| 9 AM and 6 PM daily | `0 0,9 * * *` |

After editing:

* commit
* push

The new schedule will apply automatically.

---

# Troubleshooting

## Workflow Failed (Red X in Actions)

Open the workflow logs and inspect the failed step.

The most common issue is an incorrect Telegram token.

---

## Telegram Messages Not Arriving

Check:

* Did you send `/start` to the bot?
* Is the `chat_id` correct?
* Is it your personal chat_id?

---

## Website Structure Changed

If the website HTML changes, you may need to update selectors inside `notify.py`.

Current selectors:

```plaintext id="lf9xvq"
table tbody tr
a[href*='articleNo=']
```

---

# Project Structure

```plaintext id="zz8k2m"
cnu-notice-bot/
├── notify.py                    Scraping + Telegram notification logic
├── requirements.txt             Python dependencies
├── seen.json                    Last seen articleNo for each board
├── .env.example                 Environment variable template for local testing
├── .gitignore
├── README.md                    This file
└── .github/
    └── workflows/
        └── notify.yml           GitHub Actions cron workflow
```
