#!/usr/bin/env bash
# s-peach-notifier.sh — Claude Code hook. Delegates to s-peach notify.
# MUST always exit 0 (fire-and-forget) to avoid blocking Claude Code.
s-peach notify --quiet "$@" 2>/dev/null || true
exit 0
