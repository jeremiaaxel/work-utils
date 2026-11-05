# Deploying on a VPS

Runs the app behind [Caddy](https://caddyserver.com) on a single machine.

```
phone / laptop ──HTTPS──▶ Caddy (host, :80/:443) ──HTTP──▶ web (Docker, 127.0.0.1:8000)
                                                               │
                                                               ├──▶ redis (Docker)
                                                               └──▶ worker (Docker) ──▶ redis
```

Caddy terminates TLS and proxies to the app. The app itself is bound to
`127.0.0.1` and is not reachable from the internet — only Caddy talks to it.

## Requirements

| | |
|---|---|
| RAM | 4 GB (the worker peaks at ~1.5 GB; 2 GB is too tight) |
| vCPU | 2 (one page takes ~13 s on two cores, ~27 s on one) |
| Disk | 20 GB is enough — the images total ~3 GB |
| Swap | 2 GB, see below |

## 1. Prepare the machine

### Swap

PaddleOCR's inference allocates ~1.5 GB in one go. Swap keeps the OOM killer
away when a page is read while something else is also running.

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### Firewall

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

Allow SSH **before** enabling, or you will lock yourself out.

### Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and back in for this to take effect
```

## 2. Deploy the app

```bash
sudo git clone <your-repo-url> /opt/work-utils
cd /opt/work-utils
cp .env.example .env
```

Edit `.env`:

```ini
# The password the phone and laptop type in. Required for uploads and
# saving phrases — reads are public.
APP_PASSWORD=<make this long and random>

# Where the page records live, and how long they are kept.
JR_MAX_IMAGES=50
JR_TTL_DAYS=90
JR_MAX_DIM=2000
JR_TARGET_LANG=en

# Translation providers: google | deepl | lingva | mymemory. The primary
# answers first; the fallback takes over when it refuses. DeepL needs
# TRANSLATION_DEEPL_API_KEY, Lingva needs TRANSLATION_LINGVA_URL.
TRANSLATION_PRIMARY=google
TRANSLATION_FALLBACK=mymemory

# Only Caddy may reach the app.
APP_BIND=127.0.0.1
APP_PORT=8000

APP_TEMP_DIR=/tmp/worktools
APP_MAX_UPLOAD_MB=50
```

Then build and start:

```bash
docker compose --profile production up -d --build
docker compose --profile production ps
```

The first build downloads the OCR models (~130 MB) and takes a while on a slow
link; afterwards the models are cached in the `paddlex-models` volume and
rebuilds are quick.

Check it is up:

```bash
curl -s localhost:8000/api/jp-reader/records
```

## 3. Caddy

Install from Caddy's own repository (Ubuntu/Debian):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

### With a domain

Point an A record at the server, then write `/etc/caddy/Caddyfile`:

```caddyfile
{
    email you@example.com
}

jp.example.com {
    reverse_proxy 127.0.0.1:8000 {
        # Flush immediately — the progress page is a server-sent event stream.
        flush_interval -1
    }
}
```

### Without a domain

Let's Encrypt has issued certificates for bare IP addresses since January 2026.
They are short-lived (about six days) and Caddy renews them on its own — this
needs Caddy 2.11 or newer:

```caddyfile
{
    email you@example.com
}

203.0.113.5 {
    tls {
        issuer acme {
            profile shortlived
        }
    }
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

Start it:

```bash
sudo systemctl reload caddy
sudo systemctl status caddy
```

Caddy asks Let's Encrypt for a certificate on the first request, so open the
site in a browser once if it does not come up straight away.

> **Do not add `encode` (compression) to the Caddyfile as-is.** Caddy detects
> `text/event-stream` and flushes it unbuffered, but the compression module
> buffers compressed output and the progress bar stops updating live. If you
> want compression for the rest of the site, exclude the event paths:
>
> ```caddyfile
> encode {
>     gzip
>     zstd
>     match not path /api/*/events*
> }
> ```

## 4. Use it

Open `https://your-host/jp-reader/` on the phone. Photograph a page, and the
URL that appears afterwards is shareable — open it on the laptop to watch the
same progress, then the same page.

## Day-to-day

```bash
cd /opt/work-utils

# Roll out a new build: rebuild the images, then restart the containers
# with them.
./scripts/deploy.sh

docker compose --profile production logs -f worker   # OCR progress and errors
docker compose --profile production ps
docker compose --profile production restart worker    # after changing worker code

# Update:
git pull
./scripts/deploy.sh
```

---

## Continuous deployment

A push to `main` runs the tests, builds the images and deploys them:

```
push to main
  └─ GitHub Actions
       ├─ test:   pytest + ruff + pyright      (~2 min, no OCR stack needed)
       ├─ build:  both images, in parallel      (~2-4 min, cached between runs)
       │          → pushed to ghcr.io
       └─ deploy: ssh → the server              (~30 s)
                       git pull --ff-only
                       docker compose pull     ← only the changed layers
                       docker compose up -d
                       health check
```

**The server never builds and never downloads the dependencies.** The images
are built on GitHub's runners and the server only pulls the layers that
changed — about a megabyte for a code change, because the 2 GB dependency
layer and the OCR weights are already in the registry. The running app keeps
serving while the pull happens; only the final `up -d` restarts the
containers, which is a second or two.

The heavy layers are cached between CI runs, so a build only redoes what
actually changed.

### One-time setup on the VPS

**1. The deploy command**

The SSH key is restricted to running this one script, so it has to exist before
the first deploy:

```bash
cd /opt/work-utils
sudo install -m 0755 scripts/server-deploy.sh /usr/local/bin/deploy-workutils
```

Without it, the deploy fails with
`/usr/local/bin/deploy-workutils: No such file or directory` — the key works,
there is just nothing for it to run.

**2. Let the server pull the images**

The repository is private, so the server needs a read-only token:

```bash
# a classic token with read:packages, on github.com/settings/tokens
echo "$GHCR_TOKEN" | docker login ghcr.io -u <your-github-username> --password-stdin
```

**3. A key for the CI to use**

The VPS password is only used to get in the first time — the CI never sees
it, and it is not a GitHub secret. Generate the key **on the server**, so
the public half lands in `authorized_keys` without any copying:

```bash
# on the VPS, as the deploy user
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "github-actions-workutils" -f ~/.ssh/workutils_deploy
cat ~/.ssh/workutils_deploy.pub
```

Add that public key to `authorized_keys`, restricted to the one command:

```bash
echo 'command="/usr/local/bin/deploy-workutils",restrict ssh-ed25519 AAAA... github-actions-workutils' \
    >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

`command=` means the key can only run that script, and `restrict` disables
port forwarding, agent forwarding and PTY allocation. A leaked key can
deploy and nothing else.

The **private** half is what goes into the GitHub secret:

```bash
cat ~/.ssh/workutils_deploy     # copy this into the VPS_SSH_KEY secret
```

(Generating the pair on your laptop instead works just as well — the only
difference is that the private key then never sits on the server.)

**4. A way for the server to pull the code** — a read-only deploy key:

```bash
# on the VPS
ssh-keygen -t ed25519 -C "workutils-server" -f ~/.ssh/workutils_server
cat ~/.ssh/workutils_server.pub
```

Add that public key to the repository under
**Settings → Deploy keys → Add deploy key** (read-only), then on the VPS:

```bash
cat ~/.ssh/workutils_server.pub >> ~/.ssh/authorized_keys
```

**5. The checkout and the environment**

```bash
sudo git clone git@github.com:jeremiaaxel/work-utils.git /opt/work-utils
cd /opt/work-utils
sudo cp .env.example .env && sudoedit .env     # APP_PASSWORD and the rest
sudo docker compose --profile production up -d  # so the volumes exist
```

### Secrets in GitHub

**Settings → Secrets and variables → Actions**:

| Secret | What it is |
|---|---|
| `VPS_HOST` | The server's IPv4 address |
| `VPS_USER` | The user the key belongs to |
| `VPS_SSH_KEY` | The **private** key from step 3 — the file *without* the `.pub` ending |
| `VPS_KNOWN_HOSTS` | The server's host key, pinned (see below) |

#### What `known_hosts` is for

Every SSH server has an identity — a host key, like a fingerprint. The first
time you connect, your computer asks "is this really the server?" and, once
you say yes, it remembers the answer in `~/.ssh/known_hosts`. That is what
stops someone else pretending to be your server.

On a CI runner there is nobody to answer that question, so the answer has to
come from somewhere: the `VPS_KNOWN_HOSTS` secret. It is the same list, and
if the server's key ever changes the deploy stops and says so, rather than
quietly trusting whoever answers the port.

```bash
# once, from your laptop
ssh-keyscan -H 203.0.113.10
```

or on the server: `cat /etc/ssh/ssh_host_ed25519_key.pub`.

#### If the deploy says "Permission denied (publickey,password)"

That is the *key* being refused, not the host key (a host key problem says
"Host key verification failed" instead). Work through this list:

```bash
# 1. on the server — is the public key there, with the right permissions?
ls -ld ~/.ssh ~/.ssh/authorized_keys     # .ssh 700, authorized_keys 600
cat ~/.ssh/authorized_keys                # one line per key

# 2. on the server — does the deploy command exist and run?
ls -l /usr/local/bin/deploy-workutils
sudo -u "$USER" /usr/local/bin/deploy-workutils --help

# 3. from your laptop — does the key work at all?
ssh -i ~/.ssh/workutils_deploy user@203.0.113.10 /usr/local/bin/deploy-workutils
```

The third one is the quickest test: it runs the same command the CI runs, so
if it works from your laptop the CI's problem is the secret's contents.

The most common mistake is putting the **public** key (the one ending in
`.pub`) in the `VPS_SSH_KEY` secret. The secret needs the private key — the
file that starts with `-----BEGIN OPENSSH PRIVATE KEY-----`.

Pushing the images uses the workflow's own `GITHUB_TOKEN` — no extra
secret, and the packages stay private to the repository.

### Rolling back

The build runs **before** the containers are replaced, so a build that fails
leaves the running app alone. If the new containers do not come up, the
previous image is still in the server's Docker cache:

```bash
cd /opt/work-utils
git log --oneline -3                  # find the last good commit
git checkout <sha>
docker compose --profile production up -d --remove-orphans   # no rebuild needed
```

### Keeping the disk tidy

Old images used to be the main disk eater: every deploy pulls a pair tagged
with the new commit, and nothing removed the old ones. Now the deploy script
prunes them itself — after a healthy deploy, images no container has used
for over a week are removed (`scripts/server-deploy.sh`). The running web,
worker and redis images are in use and survive; a tag from the last few days
stays around for a rollback. Volumes — the redis data and the OCR models —
and the build cache are never touched by it.

If the disk still runs low, these are safe to run by hand:

```bash
docker image prune -af --filter "until=168h"   # unused images older than a week
docker container prune -f                      # stopped containers
```

Do **not** run `docker system prune -a --volumes` — that last word deletes
the redis data and the OCR model cache. `docker builder prune` is pointless
on the server: it never builds, so it has no build cache to prune.

The images are built on GitHub's runners, whose layer cache lives in the
GitHub Actions cache (10 GB per repository, evicted least-recently-used) —
that one prunes itself.


### What is worth backing up

The saved phrases and the scanned pages live in Redis, in the `redis-data`
volume. The OCR models are re-downloadable and the images are rebuilt from
source, so Redis is the only thing worth keeping.

```bash
docker compose --profile production exec redis redis-cli BGSAVE
docker run --rm -v work-utils_redis-data:/data -v "$PWD":/backup alpine \
    tar czf /backup/redis-$(date +%F).tar.gz -C /data .
```

### If the worker gets OOM-killed

```bash
dmesg -T | grep -i "killed process"     # confirm it was the OOM killer
docker compose --profile production logs worker | tail -50
```

Add swap (step 1) and check `docker stats` — the worker should sit around
1.5 GB while reading a page.
