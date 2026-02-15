#!/bin/bash
dnf update -y
dnf install -y docker git
service docker start
usermod -a -G docker ec2-user

# Clone App
git clone https://github.com/nilay866/hercare-backend.git /app
cd /app

# Build Docker Image
docker build -t hercare-backend .

# Run Container
# Using the RDS Endpoint and Password from previous steps
docker run -d -p 80:8000 \
  -e DATABASE_URL='postgresql://postgres:XeSHMfBOkK0cM4js@hercare-db.cnwui00o4gn8.ap-south-1.rds.amazonaws.com:5432/postgres' \
  -e SECRET_KEY='hercare-production-secret-key-change-me' \
  -e WORKERS=4 \
  --restart always \
  hercare-backend
