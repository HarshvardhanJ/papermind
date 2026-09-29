# Self-host PaperMind with Docker Compose

This setup runs the Chainlit UI, private API, one ingestion worker, a Chroma server, and two PostgreSQL databases. Uploaded PDFs, Chroma vectors, parsed-file cache, model weights, and exports live under `./data`; PostgreSQL uses Docker-managed persistent volumes. Keep the VM and its disk between restarts/upgrades.

## 1. Prepare a Linux VM

In the OCI Console, create a VM.Standard.A1.Flex instance with Ubuntu 24.04 ARM and up to 2 OCPUs / 12 GB RAM if you want to stay within the published Always Free A1 allowance. Oracle documents this shape as Always Free eligible, but capacity can be unavailable in some regions; check the current [OCI Free Tier limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm) and [instance creation guide](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm). Allocate enough boot/block storage for the OS, Docker images, repository, and paper collection.

Install Docker Engine and its Compose plugin using Docker's official [Ubuntu installation guide](https://docs.docker.com/engine/install/ubuntu/). Clone this repository onto the VM. In the OCI VCN/security list, allow SSH from your own IP; this Compose file binds both the UI and API to loopback, so it does not require an inbound app port.

The Compose stack uses amd64/arm64-compatible base images, but Python ML/PDF dependencies may be slower to install or have platform-specific constraints on ARM. Build and test the image on the target VM before moving a large collection.

## 2. Configure secrets

From the project directory on the VM:

```sh
cp .env.example .env
```

Generate three distinct secrets, then paste them into `.env` for `POSTGRES_PASSWORD`, `PAPERMIND_ADMIN_PASSWORD`, and `CHAINLIT_AUTH_SECRET`:

```sh
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Set a private `PAPERMIND_ADMIN_USERNAME`, and add your Groq API key to `GROQ_API_KEY` if you want answer synthesis/metadata extraction. Without it, retrieval can still work but LLM-generated answers and extraction will be unavailable. Do not commit `.env` or share it. The generated hex database password avoids URL-escaping problems.

The configured admin account is the only login; there is no default credential and no public sign-up. Rotate its password and `CHAINLIT_AUTH_SECRET` if they are exposed. The API has no authentication, so Compose binds it to `127.0.0.1` and does not publish either database. Do not change that binding or expose port 8000 directly to the internet.

## 3. Start and check the services

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f chainlit
```

The UI is bound to the VM's loopback interface. To smoke-test it from your computer, open an SSH tunnel and visit localhost:

```sh
ssh -L 8001:127.0.0.1:8001 ubuntu@VM_PUBLIC_IP
```

Then open `http://127.0.0.1:8001` and sign in with the configured admin. For a public HTTPS URL without opening app ports, create a named Cloudflare Tunnel and configure its public hostname to route to `http://chainlit:8001` (the service name on the Compose network). Put its tunnel token in `CLOUDFLARE_TUNNEL_TOKEN`, then start the optional connector:

```sh
docker compose --profile tunnel up -d cloudflared
```

Keep SSH restricted to your IP; there is no need to allow inbound ports 8001, 8000, 5432, 5433, or 443 when using the tunnel. The API is available only from the VM at `http://127.0.0.1:8000` by default. The tunnel keeps the token in `.env`; do not commit it.

Wait for the Postgres services to pass their health checks before the app starts. The first image build downloads Python dependencies; first PDF ingestion also downloads Docling/embedding model files and may take a while.

Useful operations:

```sh
docker compose logs -f api worker chainlit chroma
docker compose build --pull
docker compose up -d
docker compose down                 # keeps databases and ./data
```

Avoid `docker compose down -v`: it deletes the PostgreSQL volumes.

## 4. Back up and restore

Back up both databases and the `data/` directory together. The SQL metadata and Chroma vector index must correspond to one another; restoring only one can leave search inconsistent.

Example database dumps (run from the project directory):

```sh
mkdir -p backups
docker compose exec -T db pg_dump -U postgres -d papermind > backups/papermind.sql
docker compose exec -T chat-db pg_dump -U postgres -d chat_history > backups/chat_history.sql
```

Also copy `data/` to protected storage, preferably while app services and Chroma are stopped for a consistent snapshot:

```sh
docker compose stop api worker chainlit
docker compose stop chroma
tar -czf backups/papermind-data.tar.gz data
docker compose start chroma api worker chainlit
```

Protect backups as sensitive data: they contain uploaded papers and chats. To restore, stop the stack, restore `data/`, then pipe each dump into its corresponding database with `docker compose exec -T db psql -U postgres -d papermind` and `docker compose exec -T chat-db psql -U postgres -d chat_history`. Change `postgres` if `POSTGRES_USER` was customized.

## Deployment checklist

- [ ] Strong, distinct admin password, database password, and Chainlit secret set in `.env`.
- [ ] `.env` is not committed or copied into a public location.
- [ ] HTTPS is enabled for remote login; plain HTTP is used only for a private smoke test.
- [ ] VM firewall does not expose PostgreSQL or the API.
- [ ] Persistent disk has room for uploaded PDFs, Chroma, caches, and database volumes.
- [ ] Backups of both PostgreSQL databases and `data/` are automated and tested.
