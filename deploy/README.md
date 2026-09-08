# Autostart on Windows (elevated)

Scripts to make the CompanionHelper server start automatically **with
administrator rights** on the target machine — the one that runs Bitfocus
Companion and PDQ Deploy. PDQ deploys require the server to be elevated
(see the main README), which is why the scheduled task uses highest privileges.

These are meant for the **deployment machine**, not your dev box.

## Install (run once, as administrator)

1. Copy the whole project onto the target machine and make sure it runs:
   `python main.py` from the project root.
2. (Recommended) Create a project-local virtualenv — `start-companionhelper.bat`
   picks it up automatically, no file edits needed:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
   Without a `.venv`, the wrapper falls back to `python` from `PATH`.
3. Per-machine configuration (`config.local.json`, `pc_aliases.txt`) — see the
   "Machine-local configuration" section of the main README. These files are
   git-ignored, so `git pull` on other machines never conflicts over them.
4. Right-click **`install-autostart.bat` → Run as administrator**
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

## Verifying it actually runs as administrator

PDQ deploys need an elevated server, so confirm the whole chain:

1. **Task level.** `schtasks /Query /TN "CompanionHelper" /V /FO LIST` must show
   `Run Level: Highest` and `Task To Run` pointing at
   `start-companionhelper.bat`. If the level is not Highest, re-run
   `install-autostart.bat` from an elevated prompt.
2. **The wrapper never runs unelevated.** `start-companionhelper.bat` checks its
   process integrity level on every start and, when not elevated (started by
   hand without "Run as administrator", or a misconfigured task), relaunches
   itself as administrator (one UAC prompt) before starting the server.
3. **Evidence log.** Each start appends to
   `%LOCALAPPDATA%\CompanionHelper\startup.log`, ending with an `Elevated: OK`
   line (or a line saying it relaunched). If you see no `Elevated: OK`, the
   process is running without admin rights.
4. **Live check** in the server console:
   ```
   whoami /groups | findstr S-1-16-12288
   ```
   prints `High Mandatory Level` when the process is elevated.

Note: the logon user must be a **local administrator** — `/RL HIGHEST` can only
elevate within that user's rights, and UAC self-elevation needs an admin
account too.

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
