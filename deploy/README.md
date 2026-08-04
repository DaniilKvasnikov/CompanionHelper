# Autostart on Windows (elevated)

Scripts to make the CompanionHelper server start automatically **with
administrator rights** on the target machine — the one that runs Bitfocus
Companion and PDQ Deploy. PDQ deploys require the server to be elevated
(see the main README), which is why the scheduled task uses highest privileges.

These are meant for the **deployment machine**, not your dev box.

## Install (run once, as administrator)

1. Copy the whole project onto the target machine and make sure it runs:
   `python main.py` from the project root.
2. If you use a virtualenv, edit `PYTHON` at the top of
   `start-companionhelper.bat` to point at its `python.exe`.
3. Right-click **`install-autostart.bat` → Run as administrator**
   (or run it from an elevated command prompt).

It registers a Task Scheduler task named **CompanionHelper** that runs
`start-companionhelper.bat` **elevated at logon**. A console window stays open
showing the server log — that is expected on a dedicated deck machine.

Start it immediately, without logging off:

```
schtasks /Run /TN "CompanionHelper"
```

## Remove

Run **`uninstall-autostart.bat` as administrator** (deletes the task).

## Notes

- **Logon vs. boot.** The task triggers at *logon* because Companion is a GUI
  app in the user session on the same machine; the server should come up in that
  same session. If you instead need it to run before anyone logs in, recreate
  the task under the `SYSTEM` account (`/SC ONSTART /RU SYSTEM` instead of
  `/SC ONLOGON`) — but verify PDQ deploys still authenticate under SYSTEM.
- **Which user.** The task runs as whoever is logged on and must be a local
  administrator, so `/RL HIGHEST` can elevate without a UAC prompt.
- **Restarts.** The in-app *Develop → Pull & Restart* button replaces the
  process in place (`os.execv`); the scheduled task is only about cold start at
  logon.
