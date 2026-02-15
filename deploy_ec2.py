import subprocess
import json
import time
import os

def run_command(command):
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {command}")
        print(e.stderr)
        return None

def main():
    print("🚀 Starting Free Tier Deployment to EC2...")

    # 1. Create Key Pair
    print("1. Checking Key Pair...")
    check_key = "aws ec2 describe-key-pairs --key-names hercare-key --output json"
    try:
        subprocess.run(check_key, shell=True, check=True, capture_output=True)
        print("   Key pair 'hercare-key' already exists.")
    except subprocess.CalledProcessError:
        print("   Creating 'hercare-key'...")
        create_key = "aws ec2 create-key-pair --key-name hercare-key --query 'KeyMaterial' --output text > hercare-key.pem"
        subprocess.run(create_key, shell=True)
        os.chmod("hercare-key.pem", 0o400)
    
    # 2. Create Security Group for Web
    print("2. Creating Web Security Group...")
    vpc_id = "vpc-0764f2d5c3275ce84" # From previous step
    
    sg_cmd = f"aws ec2 create-security-group --group-name hercare-web-sg --description 'Allow HTTP/SSH' --vpc-id {vpc_id} --output json"
    try:
        sg_result = run_command(sg_cmd)
        web_sg_id = sg_result['GroupId']
        print(f"   Created SG: {web_sg_id}")
        
        # Add Rules
        subprocess.run(f"aws ec2 authorize-security-group-ingress --group-id {web_sg_id} --protocol tcp --port 80 --cidr 0.0.0.0/0", shell=True)
        subprocess.run(f"aws ec2 authorize-security-group-ingress --group-id {web_sg_id} --protocol tcp --port 22 --cidr 0.0.0.0/0", shell=True)
    except:
        # Get existing if failed
        get_sg = "aws ec2 describe-security-groups --filters Name=group-name,Values=hercare-web-sg --output json"
        web_sg_id = run_command(get_sg)['SecurityGroups'][0]['GroupId']
        print(f"   Using existing SG: {web_sg_id}")

    # 3. Launch Instance
    print("3. Launching EC2 Instance (t2.micro)...")
    
    # User Data Script to Auto-Deploy
    user_data = '''#!/bin/bash
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
docker run -d -p 80:8000 \\
  -e DATABASE_URL='postgresql://postgres:XeSHMfBOkK0cM4js@hercare-db.cnwui00o4gn8.ap-south-1.rds.amazonaws.com:5432/postgres' \\
  -e SECRET_KEY='hercare-production-secret-key-change-me' \\
  -e WORKERS=4 \\
  --restart always \\
  hercare-backend
'''
    
    # Encode user data base64 if needed, but AWS CLI handles text file
    with open("user_data.sh", "w") as f:
        f.write(user_data)

    run_instances = (
        f"aws ec2 run-instances "
        f"--image-id resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 "
        f"--count 1 "
        f"--instance-type t3.micro " # t3.micro is free tier in ap-south-1
        f"--key-name hercare-key "
        f"--security-group-ids {web_sg_id} "
        f"--user-data file://user_data.sh "
        f"--tag-specifications 'ResourceType=instance,Tags=[{{Key=Name,Value=HerCare-Backend}}]' "
        f"--output json"
    )
    
    instance_result = run_command(run_instances)
    instance_id = instance_result['Instances'][0]['InstanceId']
    print(f"   Instance Launched: {instance_id}")
    
    print("4. Waiting for Instance to be Running...")
    subprocess.run(f"aws ec2 wait instance-running --instance-ids {instance_id}", shell=True)
    
    # Get Public IP
    get_ip = f"aws ec2 describe-instances --instance-ids {instance_id} --query 'Reservations[0].Instances[0].PublicDnsName' --output text"
    public_dns = subprocess.run(get_ip, shell=True, capture_output=True, text=True).stdout.strip()
    
    print("\n✅ DEPLOYMENT COMPLETE!")
    print(f"Instance ID: {instance_id}")
    print(f"Public DNS: http://{public_dns}")
    print("NOTE: It may take 3-5 minutes for the startup script to finish installing Docker and starting the app.")
    print("You can verify by visiting the URL in your browser shortly.")

if __name__ == "__main__":
    main()
