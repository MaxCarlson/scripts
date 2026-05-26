<!-- version: 0.1.0 -->
# Jellyfin Doctor

`jellyfin-doctor` is a Windows-oriented Jellyfin recovery and monitoring CLI.
It can inspect logs, monitor process health, create backups, and perform
reversible state resets by renaming Jellyfin state folders instead of deleting
them.

Media folders are never touched by reset commands.

```powershell
jellyfin-doctor -h
jellyfin-doctor monitor scan -h
jellyfin-doctor backup create -h
jellyfin-doctor reset full -h
jellyfin-doctor diagnose logs -h
```

The shorter alias `jfdoctor` is also installed.

