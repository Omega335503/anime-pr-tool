#!/bin/bash
# templates/index.html → public/index.html にコピーしてタイムスタンプを埋め込む
TIMESTAMP=$(TZ=Asia/Tokyo date '+%Y/%m/%d %H:%M')
sed "s/__DEPLOY_TIMESTAMP__/${TIMESTAMP}/g" templates/index.html > public/index.html
echo "Deployed with timestamp: ${TIMESTAMP}"
