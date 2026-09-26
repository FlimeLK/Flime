# Deploy Admin Web

## 1) Install dependencies
- `python3 -m venv venv`
- `source venv/bin/activate`
- `pip install -r requirements.txt`

## 2) Configure environment
- Copy `.env.example` to `.env`
- Fill `BOT_TOKEN`, `DB_*`, `ADMIN_SESSION_SECRET`, `ADMIN_TELEGRAM_IDS`
- Set `ADMIN_TELEGRAM_BOT_USERNAME`

## 3) Install systemd units
- Copy `deploy/systemd/mafia-bot.service` to `/etc/systemd/system/`
- Copy `deploy/systemd/mafia-admin-web.service` to `/etc/systemd/system/`
- Adjust `WorkingDirectory`, `User`, `Group` and paths if needed
- Allow panel user to control bot service:
  - copy `deploy/systemd/mafia-admin-sudoers` to `/etc/sudoers.d/mafia-admin`
  - validate with `visudo -cf /etc/sudoers.d/mafia-admin`

## 4) Enable services
- `sudo systemctl daemon-reload`
- `sudo systemctl enable --now mafia-bot.service`
- `sudo systemctl enable --now mafia-admin-web.service`

## 5) Nginx + HTTPS
- Copy `deploy/nginx/mafia-admin.conf` to `/etc/nginx/sites-available/`
- Replace `admin.example.com` with your domain
- Ensure `limit_req_zone` exists in nginx `http` block, for example:
  - `limit_req_zone $binary_remote_addr zone=admin_limit:10m rate=30r/m;`
- Enable site and reload nginx
- Issue cert: `sudo certbot --nginx -d admin.example.com`

## 6) Verify
- Open `https://admin.example.com`
- Login with Telegram account from `ADMIN_TELEGRAM_IDS`
- Check dashboard, logs, and bot control buttons

