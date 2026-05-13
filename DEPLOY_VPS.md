# Deploy to VPS — Run 24/7 on Vultr

By default the pipeline runs on your laptop. The moment you close it, the bot stops.

This guide deploys the bot to a cloud server (VPS) so it runs 24/7, even when your computer is off. You control it entirely from Telegram.

**Cost:** ~$6/month on [Vultr](https://www.vultr.com/)

---

## Step 1 — Create a Vultr account

1. Go to **https://www.vultr.com/** and sign up
2. Add a payment method (credit card or PayPal)

---

## Step 2 — Deploy a server

1. Click **Deploy** in the Vultr dashboard
2. Choose **Cloud Compute — Shared CPU**
3. Pick a **location** closest to you
4. Select **Ubuntu 22.04 LTS** as the OS
5. Choose the **$6/month plan** (1 vCPU, 1 GB RAM, 25 GB SSD)
6. Under **Server Hostname**, enter something like `ai-influencer-bot`
7. Click **Deploy Now** and wait ~2 minutes

Your server's IP address and root password will appear in the dashboard under **Server Details**.

---

## Step 3 — Connect to your server

Open your terminal (Mac: Terminal or iTerm, Windows: PowerShell):

```bash
ssh root@YOUR_SERVER_IP
```

Replace `YOUR_SERVER_IP` with the IP from your Vultr dashboard. Accept the fingerprint prompt. Enter the root password shown in Vultr.

---

## Step 4 — Install system dependencies

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip ffmpeg git curl libgl1
pip3 install higgsfield
```

---

## Step 5 — Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/ai-influencer-automation.git
cd ai-influencer-automation
bash setup.sh
```

---

## Step 6 — Fill in your config

```bash
nano config.py
```

Fill in these values (all required for bot mode):

```python
HIGGSFIELD_API_KEY = "your-key-here"
MIA_SOUL_ID        = "your-soul-id-uuid-here"
WAVESPEED_API_KEY  = "your-key-here"
TELEGRAM_BOT_TOKEN = "your-bot-token-here"
TELEGRAM_CHAT_ID   = "your-chat-id-here"
```

Save: `Ctrl+O` → `Enter` → `Ctrl+X`

---

## Step 7 — Log in to Higgsfield CLI

```bash
higgsfield auth login
```

This prints a URL. Copy it, open it in your browser on your laptop, and complete authentication. The CLI on the server will be logged in automatically.

---

## Step 8 — Start the bot

```bash
bash start_bot.sh
```

Check it's running:
```bash
tail -f watcher.log
```

Send a message to your Telegram bot — it should respond. You're live.

---

## Step 9 — Disconnect safely

```bash
exit
```

The bot keeps running. `start_bot.sh` uses `nohup` so the process survives when you close the SSH session.

---

## Managing the bot later

SSH back in anytime:
```bash
ssh root@YOUR_SERVER_IP
cd ai-influencer-automation
```

| Task | Command |
|------|---------|
| View live logs | `tail -f watcher.log` |
| Stop the bot | `bash stop_bot.sh` |
| Restart the bot | `bash stop_bot.sh && bash start_bot.sh` |
| Check if running | `ps aux | grep watcher.py` |
| Check disk space | `df -h` |
| Check memory | `free -h` |

---

## Notes

- The $6/month plan is sufficient — Higgsfield and Wavespeed do the heavy GPU work on their servers; this server just runs the orchestration scripts
- Your `config.py` contains secret API keys — never commit it or share it
- If you want the bot to restart automatically after a server reboot, ask Claude to set up a systemd service
