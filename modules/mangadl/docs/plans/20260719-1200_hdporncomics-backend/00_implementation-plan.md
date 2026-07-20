# HDPornComics Backend

Add the dedicated external downloader as an automatic mangadl backend. Route
only normalized `hdporncomics.com` / `www.hdporncomics.com` `/manhwa/` URLs,
preserve normal gallery-dl handling elsewhere, and retain normal persisted job,
retry, worker-concurrency, logging, and URL-file behavior.

The worker invokes `hdporncomics --directory <destination> --threads <n>
--force --manhwa <url>` exactly once per job. It validates image output without
deleting existing files. A dedicated command checks or explicitly reapplies the
known installed-package Windows path patch after upstream updates.
