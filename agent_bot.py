#!/usr/bin/env python3
"""MiMo Agent"""

import json, logging, mimetypes, os, re, signal, subprocess, sys, time
import urllib.error, urllib.request
from datetime import datetime
from pathlib import Path

BOT_TOKEN=os.environ.get("BOT_TOKEN", "")
API_KEY=os.environ.get("API_KEY", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED = set(int(c) for c in os.environ.get("ALLOWED_CHATS", "").split(",") if c.strip()) if os.environ.get("ALLOWED_CHATS") else set()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent")
_shutdown = False

