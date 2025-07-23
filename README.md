# MEGA Monitor 🤖

<p align="center">
  <img src="assets/logo.png" alt="MEGA Monitor Logo" width="200"/>
</p>

A lightweight bot that monitors public MEGA.nz folders and sends updates to a Discord webhook. It tracks all updates in a Mega folder and includes a detailed report with each notification.

---

## ✨ Features

- Detects all changes in MEGA folders
- Sends update reports via Discord webhook
- Supports multiple MEGA links
- Easy to run via Docker or manually with Python

---

## 📦 Docker Deployment

1. Create a folder and inside it, add a `docker-compose.yml`:

```yaml
services:
  mega-monitor:
    container_name: mega-monitor
    image: ghcr.io/xmacj/mega-monitor:latest
    environment:
      - MEGA_LINK_DEMO1=https://mega.nz/folder/albums # The link to the Mega folder
      - MEGA_LINK_DEMO2=https://mega.nz/folder/movies # Optional additional links
      - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy # Your discord webhook url
      - MENTION_USER_IDS=123456789012345678,987654321098765432 # Optional users to tag in the webhook message
      - CHECK_INTERVAL_SECONDS=600 # How often to check the Mega folders in seconds (Default: 10 min)
      - LOG_LEVEL=INFO
      - TIMEZONE=America/New_York
    volumes:
      - ./data:/app/data # The data folder where changes are stored
    restart: unless-stopped
```
> ℹ️ Each `MEGA_LINK_<NAME>` should be unique.

---

## 👨‍💻 Manual Python Usage

1. Clone the repo and install dependencies:

```bash
git clone https://github.com/xmacj/mega-monitor.git
cd mega-monitor
pip install -r requirements.txt

```

2. Create a `.env` file in the root directory:

```env
MEGA_LINK_DEMO1=https://mega.nz/folder/songs
MEGA_LINK_DEMO2=https://mega.nz/folder/movies
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
MENTION_USER_IDS=123456789012345678,987654321098765432
CHECK_INTERVAL_SECONDS=600
LOG_LEVEL=INFO
TIMEZONE=America/New_York
```

3. Run the script:

```bash
python -m mega_monitor
```