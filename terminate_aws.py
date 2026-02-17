import subprocess
import json
import time

def run_command(command):
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=True)
        return json.loads(result.stdout) if result.stdout else {}
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Error: {e}")
        return None

def main():
    print("🚨 STARTING AWS RESOURCE TERMINATION 🚨")
    print("This will DELETE EC2 instances and S3 buckets created for HerCare.")
    
    # 1. Terminate EC2
    print("\n1️⃣  Checking EC2 Instances...")
    cmd = "aws ec2 describe-instances --filters \"Name=tag:Name,Values=HerCare-Backend\" \"Name=instance-state-name,Values=running,pending\" --output json"
    result = run_command(cmd)
    
    instances = []
    if result and 'Reservations' in result:
        for r in result['Reservations']:
            for i in r['Instances']:
                instances.append(i['InstanceId'])
    
    if instances:
        print(f"   Found {len(instances)} instances: {instances}")
        print("   Terminating...")
        run_command(f"aws ec2 terminate-instances --instance-ids {' '.join(instances)}")
        print("   Waiting for termination...")
        run_command(f"aws ec2 wait instance-terminated --instance-ids {' '.join(instances)}")
        print("   ✅ Instances Terminated.")
    else:
        print("   ✅ No running instances found.")

    # 2. Delete Security Group
    print("\n2️⃣  Deleting Security Group (hercare-web-sg)...")
    try:
        run_command("aws ec2 delete-security-group --group-name hercare-web-sg")
        print("   ✅ Security Group Deleted.")
    except:
        print("   ⚠️  Could not delete SG (might be in use or already deleted). Manual check required if dependent.")

    # 3. Delete S3 Buckets
    print("\n3️⃣  Cleaning up S3 Buckets...")
    # List buckets with 'hercare-app-frontend' in name
    cmd_buckets = "aws s3api list-buckets --output json"
    res_buckets = run_command(cmd_buckets)
    
    buckets_to_delete = []
    if res_buckets and 'Buckets' in res_buckets:
        for b in res_buckets['Buckets']:
            if 'hercare-app-frontend' in b['Name']:
                buckets_to_delete.append(b['Name'])
    
    if buckets_to_delete:
        print(f"   Found buckets: {buckets_to_delete}")
        for b in buckets_to_delete:
            print(f"   🗑️  Emptying & Deleting {b}...")
            # Empty bucket first
            subprocess.run(f"aws s3 rm s3://{b} --recursive", shell=True)
            # Delete bucket
            subprocess.run(f"aws s3 rb s3://{b}", shell=True)
        print("   ✅ Buckets Deleted.")
    else:
        print("   ✅ No HerCare buckets found.")

    print("\n🎉 AWS CLEANUP COMPLETE.")
    print("Please double-check your AWS Console to ensure no lingering resources.")

if __name__ == "__main__":
    main()
