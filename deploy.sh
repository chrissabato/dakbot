#!/bin/bash
# deploy.sh — Push the server/ folder (PHP API + devices dashboard) to the webserver.
#
# Usage:
#   ./deploy.sh                # deploy with defaults below
#   REMOTE_HOST=x ./deploy.sh  # override any variable via env

REMOTE_USER=${REMOTE_USER:-chrissabato}
REMOTE_HOST=${REMOTE_HOST:-stats.chrissabato.com}
REMOTE_PATH=${REMOTE_PATH:-~/www/stats.chrissabato.com/html}
SSH_KEY=${SSH_KEY:-~/.ssh/dakbot_deploy}

echo "Deploying server/ contents to $REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH ..."

# No --delete here: REMOTE_PATH is the site's document root, which holds
# other files we don't want to touch — this only adds/updates our files.
rsync -avz \
    -e "ssh -i $SSH_KEY" \
    --exclude 'config.php' \
    server/ "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"

if [ $? -ne 0 ]; then
    echo "ERROR: rsync failed"
    exit 1
fi

echo "Done. (config.php on the remote was left untouched — update it manually if credentials changed.)"
