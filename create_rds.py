import subprocess
import json
import secrets
import string

def run_command(command):
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {command}")
        print(e.stderr)
        return None

def main():
    vpc_id = "vpc-0764f2d5c3275ce84"
    
    # 1. Create Security Group
    print("Creating Security Group...")
    sg_cmd = f"aws ec2 create-security-group --group-name hercare-db-sg --description 'Allow PostgreSQL access' --vpc-id {vpc_id} --output json"
    sg_result = run_command(sg_cmd)
    
    if not sg_result:
        # Check if it already exists
        print("Security group might already exist. Retrieving...")
        get_sg_cmd = f"aws ec2 describe-security-groups --filters Name=group-name,Values=hercare-db-sg --output json"
        sg_list = run_command(get_sg_cmd)
        if sg_list and sg_list['SecurityGroups']:
            sg_id = sg_list['SecurityGroups'][0]['GroupId']
            print(f"Found existing Security Group: {sg_id}")
        else:
            print("Failed to find or create SG.")
            return
    else:
        sg_id = sg_result['GroupId']
        print(f"Created Security Group: {sg_id}")
        
        # 2. Add Ingress Rule
        print("Adding Ingress Rule...")
        ingress_cmd = f"aws ec2 authorize-security-group-ingress --group-id {sg_id} --protocol tcp --port 5432 --cidr 0.0.0.0/0"
        subprocess.run(ingress_cmd, shell=True, check=False) # Might fail if rule exists, safe to ignore

    # 3. Generate Password
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(16))
    
    # 4. Create RDS Instance
    print("Creating RDS Instance (this triggers the process, it will take ~10 mins to complete)...")
    create_db_cmd = (
        f"aws rds create-db-instance "
        f"--db-instance-identifier hercare-db "
        f"--db-instance-class db.t3.micro "
        f"--engine postgres "
        f"--master-username postgres "
        f"--master-user-password {password} "
        f"--allocated-storage 20 "
        f"--vpc-security-group-ids {sg_id} "
        f"--publicly-accessible "  # Making it public for App Runner (without VPC connector) and user convenience
        f"--backup-retention-period 0 " # Fix for free tier error
        f"--no-multi-az " # Free tier / lower cost
        f"--output json"
    )
    
    db_result = run_command(create_db_cmd)
    
    if db_result:
        print("\nSUCCESS! RDS Creation Initialized.")
        print(f"DB Instance Identifier: hercare-db")
        print(f"Master Username: postgres")
        print(f"Master Password: {password}")
        print("IMPORTANT: Save this password! It will not be shown again.")
        print("Status: Creating (Wait for 'Available' status in AWS Console)")
    else:
        print("Failed to create RDS instance (it might already exist).")

if __name__ == "__main__":
    main()
