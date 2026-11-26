"""alwaysdata "Monitoring command": python healthcheck.py

Exit code 0 = healthy. Anything else makes alwaysdata restart the service.
The bot rewrites data/heartbeat every 30 seconds; if it is older than 3 minutes,
the bot is frozen or not running.
"""
import os
import sys
import time

HEARTBEAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "heartbeat")
MAX_AGE = 180

try:
    age = time.time() - int(open(HEARTBEAT).read().strip())
except (OSError, ValueError):
    print("no heartbeat yet")
    sys.exit(1)

print(f"heartbeat {age:.0f}s ago")
sys.exit(0 if age < MAX_AGE else 1)
