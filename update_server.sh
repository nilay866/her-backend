#!/bin/bash
set -e

echo "🚀 Updating HerCare Backend..."

# 1. Update Code
cd /app
echo "⬇️ Pulling latest code..."
sudo git pull origin main

# 2. Rebuild Container
echo "🔨 Building Docker image..."
sudo docker build -t hercare-backend .

# 3. Stop Old Container
echo "🛑 Stopping ALL old containers..."
# Stop any container using Port 80
sudo docker stop $(sudo docker ps -q) || true
sudo docker rm $(sudo docker ps -a -q) || true

# 4. Run New Container
echo "▶️ Starting new container..."
sudo docker run -d -p 80:8000 \
  -e DATABASE_URL='postgresql://postgres.rbmlnrwjuocuhmnsrvrc:wohfuN-wekhuv-9xaksi@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres' \
  -e SECRET_KEY='hercare-production-secret-key-change-me' \
  -e WORKERS=4 \
  --restart always \
  hercare-backend

echo "✅ Backend Updated Successfully!"
