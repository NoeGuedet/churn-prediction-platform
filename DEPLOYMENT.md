# Deployment guide

Run the platform on your own server with Docker Compose. Only the web UI is exposed; the ML services stay on an internal Docker network.

## Prerequisites

- A Linux server (VM, homelab, VPS…) with Docker Engine 24+ and the Compose plugin (`docker compose version`)
- A reverse proxy of your choice (nginx, Caddy, Traefik…) able to forward HTTP traffic to the host on port 7860
- ~2 GB of free RAM for the four containers

## 1. Get the code

```bash
git clone https://github.com/NoeGuedet/churn-prediction-platform.git
cd churn-prediction-platform
```

## 2. Configure the environment

```bash
cp .env.example .env
```

The defaults work out of the box with Docker Compose (service names resolve on the compose network). Adjust `CHURN_THRESHOLD` or `WORKERS` only if you know why.

## 3. Build and start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The production override adds restart policies and per-service CPU/memory limits (mirroring the Kubernetes quota this project was designed under), and unpublishes every port except the web UI.

Check that everything is up:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f webui
```

## 4. Point your reverse proxy at the web UI

The web UI listens on host port **7860**. Configure your existing reverse proxy to forward your domain to `http://<this-host>:7860` (plain HTTP on the LAN; terminate TLS at your proxy as usual). No other port needs to be reachable from outside the host.

## 5. Firewall notes

- Allow inbound traffic only to your reverse proxy (typically 80/443).
- Port 7860 only needs to be reachable **from the reverse proxy** — if the proxy runs on another machine, restrict 7860 to its IP; if it runs on the same host, restrict it to localhost (e.g. publish `127.0.0.1:7860:7860` in the override instead of `7860:7860`).

## Security notes

- **The inference API is not exposed.** `preprocessing`, `inference` and `monitoring` publish no ports in the production setup; they are only reachable inside the compose network. The only public surface is the Gradio UI.
- No authentication is built into the UI. If you want to restrict access, do it at your reverse proxy (basic auth, IP allowlist, SSO forward-auth…).
- No secrets are required by the platform itself; `.env` only holds service URLs and tuning knobs.

## Updating

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## Resource limits

| Service | CPU limit | Memory limit |
|---|---|---|
| preprocessing | 0.4 | 288 MB |
| inference | 0.7 | 544 MB |
| monitoring | 0.2 | 128 MB |
| webui | 0.5 | 512 MB |

These mirror the Kubernetes `limits` in `k8s/` (see [ADR.md](ADR.md) for how they were measured). The whole stack fits comfortably in ~1.6 GB of RAM.
