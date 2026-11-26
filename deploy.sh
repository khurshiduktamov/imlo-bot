#!/usr/bin/env bash
# Deploy the bot to alwaysdata:   ./deploy.sh
#
# 1. checks the code locally   2. backs up the server code   3. uploads + installs
# 4. verifies on the server     5. restarts the bot and waits until it is polling again
set -euo pipefail

HOST="khurshid@ssh-khurshid.alwaysdata.net"
FILES=(main.py common.py db.py fileproc.py checkWords.py alphabetCheck.py translitarate.py uzwords.py
       premium.py admin.py inline.py ops.py healthcheck.py requirements.txt)

cd "$(dirname "$0")"

if [ -n "$(git status --porcelain)" ]; then
  echo "❌ Uncommitted changes. Commit them first, so the server always matches a commit."; exit 1
fi
branch=$(git branch --show-current)
if [ "$branch" != "master" ]; then
  read -r -p "You are on '$branch', not master. Deploy anyway? [y/N] " answer
  [ "$answer" = "y" ] || exit 1
fi

echo "1/5 Checking the code locally..."
.venv/bin/python -c "import main" >/dev/null

echo "2/5 Backing up the server code..."
ssh "$HOST" 'cd ~ && mkdir -p deploy_backups admin/tmp/up \
  && tar czf "deploy_backups/before_$(date +%Y%m%d_%H%M%S).tar.gz" *.py requirements.txt \
  && ls -t deploy_backups/*.tar.gz | tail -n +11 | xargs -r rm --'   # keep the last 10

echo "3/5 Uploading..."
scp -q "${FILES[@]}" "$HOST:admin/tmp/up/"
ssh "$HOST" "cd ~ && python - ${FILES[*]}" <<'PY'
import os, shutil, sys
for name in sys.argv[1:]:
    data = open(os.path.join("admin/tmp/up", name), "rb").read()
    if os.path.exists(name):
        # the files belong to the service user: update them in place (replacing is not allowed here)
        with open(name, "r+b") as f:
            f.write(data)
            f.truncate()
    else:
        with open(name, "wb") as f:
            f.write(data)
        os.chmod(name, 0o664)
shutil.rmtree("admin/tmp/up")
PY
ssh "$HOST" 'cd ~ && python -m pip install --user -q --no-cache-dir -r requirements.txt 2>&1 | grep -v -i notice || true'

echo "4/5 Verifying on the server..."
ssh "$HOST" 'cd ~ && python -c "import main"' >/dev/null
local_sums=$(shasum -a 256 "${FILES[@]}" | awk '{print $1}')
remote_sums=$(ssh "$HOST" "cd ~ && sha256sum ${FILES[*]}" | awk '{print $1}')
if [ "$local_sums" != "$remote_sums" ]; then
  echo "❌ Server files differ from local files after upload."; exit 1
fi

echo "5/5 Restarting the bot..."
before=$(ssh "$HOST" 'grep -c "Start polling" ~/bot.log || true')
ssh "$HOST" 'touch ~/.restart_request'
for _ in $(seq 1 12); do
  sleep 5
  now=$(ssh "$HOST" 'grep -c "Start polling" ~/bot.log || true')
  if [ "$now" -gt "$before" ]; then
    echo "✅ Deployed $(git rev-parse --short HEAD) ($branch); the bot restarted and is polling."
    ssh "$HOST" 'tail -n 3 ~/bot.log'
    exit 0
  fi
done
echo "⚠️  Code is deployed, but the bot did not restart within 60 s."
echo "    Restart it in the alwaysdata panel: Advanced → Services → restart."
exit 1
