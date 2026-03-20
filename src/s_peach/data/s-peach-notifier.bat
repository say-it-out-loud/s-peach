@echo off
REM s-peach-notifier.bat — Claude Code hook. Delegates to s-peach notify.
REM MUST always exit 0 (fire-and-forget) to avoid blocking Claude Code.
s-peach notify --quiet %* 2>nul
exit /b 0
