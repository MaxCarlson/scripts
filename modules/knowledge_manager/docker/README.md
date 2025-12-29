# Knowledge Manager - PostgreSQL Docker Setup

This directory contains Docker configuration for running PostgreSQL as the backend database for Knowledge Manager.

## Quick Start (WSL Ubuntu)

### 1. Switch to WSL and navigate to this directory

```bash
# From Windows (Git Bash/PowerShell):
wsl

# Inside WSL:
cd src/scripts/modules/knowledge_manager/docker
```

### 2. Create environment file

```bash
cp .env.example .env

# Edit .env and change the default password!
nano .env  # or vim, code, etc.
```

### 3. Start PostgreSQL

```bash
docker compose up -d
```

### 4. Verify it's running

```bash
docker compose ps
docker compose logs postgres
```

### 5. Test connection

```bash
# Install PostgreSQL client if needed
sudo apt-get update && sudo apt-get install -y postgresql-client

# Connect to database
psql -h localhost -U km_user -d knowledge_manager
# Password: (from your .env file)
```

## Migration from SQLite

### Install pgloader (in WSL)

```bash
sudo apt-get update
sudo apt-get install -y pgloader
```

### Run migration

```bash
# Copy your SQLite database to a known location
cp ~/.local/share/knowledge_manager_data/knowledge_manager.db ./sqlite_backup.db

# Or use the Windows path directly (pgloader can access /mnt/c/)
# Run migration
pgloader migrate.load

# Check results
docker compose exec postgres psql -U km_user -d knowledge_manager -c "SELECT 'projects' as table, COUNT(*) FROM projects UNION ALL SELECT 'tasks', COUNT(*) FROM tasks;"
```

## Configuration

### Environment Variables

Edit `.env` file to customize:

- `POSTGRES_USER`: Database user (default: km_user)
- `POSTGRES_PASSWORD`: **CHANGE THIS!** (default: km_secure_pass_change_me)
- `POSTGRES_DB`: Database name (default: knowledge_manager)
- `POSTGRES_PORT`: Port to expose (default: 5432)

### Connection String

After setup, use this connection string in your applications:

```
postgresql://km_user:your_password@localhost:5432/knowledge_manager
```

Set environment variable:

```bash
export KM_DB_TYPE=postgresql
export KM_POSTGRES_URL="postgresql://km_user:your_password@localhost:5432/knowledge_manager"
```

## Optional: pgAdmin Web UI

To start the pgAdmin web interface for database management:

```bash
docker compose --profile admin up -d
```

Access at: http://localhost:5050

- Email: admin@km.local (or from .env)
- Password: admin (or from .env)

## LAN Access (Other Devices)

### Enable WSL2 Port Forwarding (PowerShell as Admin)

```powershell
# Get WSL IP
$wsl_ip = (wsl hostname -I).Trim().Split()[0]

# Forward port 5432
netsh interface portproxy add v4tov4 listenport=5432 listenaddress=0.0.0.0 connectport=5432 connectaddress=$wsl_ip

# Add firewall rule
New-NetFireWallRule -DisplayName 'PostgreSQL-KM' -Direction Inbound -LocalPort 5432 -Action Allow -Protocol TCP

# Verify
netsh interface portproxy show v4tov4
```

### Or use .wslconfig mirrored networking (Windows 11 22H2+)

Create/edit `C:\Users\<username>\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored

[experimental]
hostAddressLoopback=true
dnsTunneling=true
```

Then restart WSL:

```powershell
wsl --shutdown
wsl
```

### Connect from other devices

From Termux (Android) or other Linux devices:

```bash
# Install PostgreSQL client
pkg install postgresql  # Termux
# or
sudo apt install postgresql-client  # Ubuntu/Debian

# Connect (replace with your Windows machine IP)
psql -h 192.168.1.100 -U km_user -d knowledge_manager
```

## Useful Commands

### Start/Stop containers

```bash
docker compose up -d           # Start in background
docker compose down            # Stop containers
docker compose restart         # Restart containers
docker compose logs -f         # View logs (follow)
```

### Database operations

```bash
# Backup database
docker compose exec -T postgres pg_dump -U km_user knowledge_manager > backup.sql

# Restore database
docker compose exec -T postgres psql -U km_user -d knowledge_manager < backup.sql

# Connect to PostgreSQL shell
docker compose exec postgres psql -U km_user -d knowledge_manager

# Run SQL file
docker compose exec -T postgres psql -U km_user -d knowledge_manager < script.sql
```

### Inspect container

```bash
docker compose exec postgres bash
# Inside container:
psql -U km_user -d knowledge_manager
```

## Troubleshooting

### Port already in use

```bash
# Check what's using port 5432
sudo lsof -i :5432
# or
sudo netstat -tulpn | grep 5432

# Kill process or change POSTGRES_PORT in .env
```

### Permission denied on volumes

```bash
# Reset volume permissions
docker compose down -v
docker volume rm km_postgres_data
docker compose up -d
```

### Can't connect from Windows to WSL container

1. Check WSL IP: `wsl hostname -I`
2. Use that IP instead of `localhost` from Windows
3. Or set up port forwarding (see LAN Access section)

### Migration failed

```bash
# Check pgloader logs
cat ~/.local/share/pgloader/pgloader.log

# Verify source database
sqlite3 sqlite_backup.db ".schema"

# Check PostgreSQL is accepting connections
docker compose exec postgres pg_isready -U km_user
```

## Performance Tuning

The `docker-compose.yml` includes PostgreSQL configuration optimized for:
- Modern NVMe SSD storage
- Up to 100 concurrent connections
- 8GB+ system RAM

For different hardware, edit the `command` section in `docker-compose.yml`.

## Security Notes

1. **Change the default password** in `.env`
2. Don't commit `.env` to version control (it's in .gitignore)
3. For production use, consider:
   - Using Docker secrets instead of environment variables
   - Enabling SSL/TLS connections
   - Restricting network access with firewall rules

## Next Steps

After PostgreSQL is running:

1. Run migration from SQLite (see Migration section)
2. Update `knowledge_manager` Python code to use PostgreSQL
3. Test TUI with PostgreSQL backend
4. Set up LISTEN/NOTIFY for real-time updates

## References

- [PostgreSQL Docker Image](https://hub.docker.com/_/postgres)
- [pgloader Documentation](https://pgloader.readthedocs.io/)
- [asyncpg Python Library](https://github.com/MagicStack/asyncpg)
