# Job Alert System 🚀

> **Automated job aggregation** — scrapes 12+ company career pages every hour, deduplicates across runs, and delivers rich Telegram notifications to your private group.

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Automated-2088FF?logo=github-actions&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Telegram](https://img.shields.io/badge/Notifications-Telegram-26A5E4?logo=telegram&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

| Feature | Detail |
|---|---|
| 🔄 **Automated** | Runs every hour via GitHub Actions — zero infrastructure cost |
| 🏗️ **Multi-platform** | Greenhouse, Lever, Ashby, and custom career pages |
| 🧹 **Smart deduplication** | SQLite-backed; same company + role + location → skipped |
| 📱 **Rich Telegram cards** | Company logo, role, salary, experience, work mode, apply link |
| 💾 **Persistent storage** | SQLite committed back to the repo on every change |
| 🔇 **No noise** | Only genuinely new jobs trigger notifications |
| 🪵 **Daily log rotation** | Logs compressed and retained for 30 days |
| 🛡️ **Fault-tolerant** | One failing company never aborts the pipeline |

---

## 🏛️ Architecture

```
job-alert-system/
├── main.py                  ← Pipeline orchestrator
│
├── scraper/
│   ├── base.py              ← Abstract BaseScraper + Job dataclass
│   ├── greenhouse.py        ← Greenhouse JSON API scraper
│   ├── lever.py             ← Lever JSON API scraper
│   ├── ashby.py             ← Ashby JSON API scraper
│   └── custom.py            ← Playwright-powered generic scraper
│
├── database/
│   └── db.py                ← SQLite DAL (init, insert, dedup check)
│
├── telegram/
│   └── bot.py               ← Telegram Bot API sender
│
├── utils/
│   ├── logger.py            ← Loguru daily-rotating logger
│   └── helpers.py           ← HTTP, work-mode, experience, logo utils
│
├── config/
│   └── companies.json       ← Company list (name, url, type)
│
├── logs/                    ← Daily log files (auto-created)
│
├── .env.example             ← Environment variable template
├── requirements.txt
└── .github/workflows/jobs.yml  ← Hourly GitHub Actions workflow
```

### Data Flow

```
companies.json
      │
      ▼
  BaseScraper (Greenhouse / Lever / Ashby / Custom)
      │
      ▼
  [Job dataclass]
      │
      ▼
  Duplicate check (SQLite dedup_key)
      │
      ├── Duplicate → skip
      │
      └── New → insert → Telegram notification
```

---

## 📦 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| HTTP | `requests` with retry adapter |
| HTML parsing | `BeautifulSoup4` + `lxml` |
| JS rendering | `Playwright` (Chromium headless) |
| Storage | `SQLite` via stdlib `sqlite3` |
| Logging | `loguru` (daily rotation, compression) |
| Config | `python-dotenv` + JSON |
| Automation | GitHub Actions |
| Notifications | Telegram Bot API |

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/job-alert-system.git
cd job-alert-system
```

### 2. Create a virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Then edit .env with your actual credentials
```

### 5. Run locally

```bash
python main.py
```

---

## ⚙️ Configuration

### `.env` file

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | ✅ | Numeric ID of your private group/channel |
| `DB_PATH` | ❌ | SQLite file path (default: `database/jobs.db`) |
| `COMPANIES_PATH` | ❌ | JSON config path (default: `config/companies.json`) |
| `INTER_REQUEST_DELAY` | ❌ | Delay between companies in seconds (default: `1.0`) |
| `SEND_SUMMARY` | ❌ | Send a run summary to Telegram (default: `true`) |

### `config/companies.json`

Add or remove companies without touching any Python code:

```json
[
  {
    "name": "Stripe",
    "url": "https://boards.greenhouse.io/stripe",
    "type": "greenhouse"
  },
  {
    "name": "Netflix",
    "url": "https://jobs.lever.co/netflix",
    "type": "lever"
  },
  {
    "name": "OpenAI",
    "url": "https://jobs.ashbyhq.com/openai",
    "type": "ashby"
  },
  {
    "name": "My Company",
    "url": "https://mycompany.com/careers",
    "type": "custom"
  }
]
```

**Supported types:** `greenhouse` · `lever` · `ashby` · `custom`

---

## 📱 Telegram Setup

### Step 1 — Create a bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **API token** → set as `TELEGRAM_BOT_TOKEN`

### Step 2 — Create a private group / channel

1. Create a new private group or channel in Telegram
2. Add your bot as an **administrator** (must have "Post Messages" permission)
3. Obtain the **chat ID**:
   - For groups: forward a message from the group to [@userinfobot](https://t.me/userinfobot)
   - For channels: use `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending a message
4. Set the numeric ID (including the leading `-100`) as `TELEGRAM_CHAT_ID`

### Job Card Preview

```
[Company Logo]

🏢 Company: Atlassian
💼 Role: Software Engineer I
📍 Location: Bengaluru
💰 Salary: Not Mentioned
🦾 Experience: 0–2 Years
🏠 Work Mode: Hybrid
📅 Posted: 2024-06-01

🔗 Apply: Click Here
```

---

## 🤖 GitHub Actions Setup

### Step 1 — Push to GitHub

```bash
git remote add origin https://github.com/YOUR_USERNAME/job-alert-system.git
git push -u origin main
```

### Step 2 — Add secrets

Navigate to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token |
| `TELEGRAM_CHAT_ID` | Your group/channel chat ID |

### Step 3 — Enable Actions

Go to the **Actions** tab in your repository and enable workflows if prompted.

The workflow will now run **every hour automatically**.  
You can also trigger it manually from **Actions → Job Alert — Hourly Scraper → Run workflow**.

---

## 📊 Screenshots

> _Coming soon — add screenshots of your Telegram notifications here._

---

## 🗺️ Future Improvements

- [ ] **Keyword filtering** — only alert on jobs matching specific keywords (e.g. "Python", "remote")
- [ ] **Location filtering** — restrict to specific cities or countries
- [ ] **Salary range filter** — skip jobs without disclosed salary
- [ ] **Email digest** — daily HTML email summarising all new jobs
- [ ] **Web dashboard** — simple Flask/FastAPI UI to browse jobs
- [ ] **More ATS platforms** — Workday, iCIMS, SmartRecruiters, Rippling
- [ ] **Slack notifications** — dual-channel support alongside Telegram
- [ ] **Job scoring** — ML-based relevance scoring per user profile

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Commit your changes: `git commit -m 'feat: add my feature'`
4. Push to the branch: `git push origin feat/my-feature`
5. Open a Pull Request

---

## 📄 License

MIT © 2024 — feel free to use this in your own projects.
