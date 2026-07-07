# Deploying the panel onto the EXISTING GVPrime Lightsail box (production-safe)

> This server already runs production GVPrime services (support-ai, contact-form
> API, worker) behind nginx on 80/443, plus uvicorn apps on 8000 and 8001.
> The steps below add the panel WITHOUT touching any of that: panel listens on a
> free port (8020, localhost only) and the existing nginx proxies a new subdomain
> to it. Do NOT install Caddy on this box - it would clash with nginx.

Run all commands in your WSL / on the server. Server: ubuntu@54.163.82.23
Key: /home/prime/lightsail-key.pem-gvprime-ai.pem

## 0. DNS
Point a NEW subdomain at 54.163.82.23, e.g. panel.gvprime.ai (A record).
Confirm: `dig +short panel.gvprime.ai` -> 54.163.82.23. Do not reuse a subdomain
already served by the existing nginx.

## 1. Copy the app up (does not touch existing services)
```bash
KEY=/home/prime/lightsail-key.pem-gvprime-ai.pem
scp -i "$KEY" -r ./fb-autoposter ubuntu@54.163.82.23:/home/ubuntu/
ssh -i "$KEY" ubuntu@54.163.82.23
```

## 2. Install deps + service (panel on 127.0.0.1:8020)
```bash
pip3 install -r /home/ubuntu/fb-autoposter/requirements.txt
sudo cp /home/ubuntu/fb-autoposter/fb-autoposter-panel.service /etc/systemd/system/
sudo nano /etc/systemd/system/fb-autoposter-panel.service   # set PANEL_PASSWORD + real keys
sudo chmod 600 /etc/systemd/system/fb-autoposter-panel.service
sudo systemctl daemon-reload
sudo systemctl enable --now fb-autoposter-panel
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8020/   # expect 200 (login page)
```
Confirm you did NOT disturb 8000/8001: `sudo ss -ltnp | grep -E '8000|8001|8020'`
should still show the two gvprime uvicorns AND the new panel on 8020.

## 3. Add nginx site (reuses existing nginx - no restart of the app services)
```bash
sudo cp /home/ubuntu/fb-autoposter/nginx-panel.conf /etc/nginx/sites-available/fb-autoposter-panel
sudo nano /etc/nginx/sites-available/fb-autoposter-panel   # set your real subdomain
sudo ln -s /etc/nginx/sites-available/fb-autoposter-panel /etc/nginx/sites-enabled/
sudo nginx -t          # MUST say "syntax is ok / test is successful" before proceeding
sudo systemctl reload nginx     # reload, not restart - existing sites stay up
```

## 4. TLS for the new subdomain (certbot + nginx)
```bash
sudo snap install --classic certbot 2>/dev/null || sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d panel.gvprime.ai     # your subdomain; adds the 443 block automatically
```

## 5. Verify
Open https://panel.gvprime.ai -> login over HTTPS (padlock). Sign in, edit, dry-run.
Keep dry_run: true until you've confirmed a test post.

## Rollback (if anything looks off)
```bash
sudo rm /etc/nginx/sites-enabled/fb-autoposter-panel && sudo systemctl reload nginx
sudo systemctl disable --now fb-autoposter-panel
```
This fully removes the panel and leaves the existing GVPrime stack untouched.
