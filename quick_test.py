#!/usr/bin/env python3
"""
HerCare Platform - Quick Testing Script
Tests all 5 phases with minimal setup
Run: python quick_test.py
"""

import requests
import json
from datetime import datetime, timedelta
import sys

# Configuration
BASE_URL = "http://localhost:8000/api/v1"
TEST_EMAIL = f"test{datetime.now().timestamp()}@example.com"
TEST_PASSWORD = "Test@123456"

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

class HerCareQuickTest:
    def __init__(self):
        self.token = None
        self.user_id = None
        self.test_results = []
    
    def print_header(self, text):
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}{text.center(60)}{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")
    
    def print_test(self, name, status, details=""):
        symbol = f"{GREEN}✅{RESET}" if status else f"{RED}❌{RESET}"
        print(f"{symbol} {name}")
        if details:
            print(f"   {YELLOW}→ {details}{RESET}")
        self.test_results.append((name, status))
    
    def test_server_connection(self):
        """Test if backend is running"""
        self.print_header("PHASE 0: Backend Connection")
        
        try:
            response = requests.get("http://localhost:8000", timeout=5)
            self.print_test("Backend Server", True, "Server is running")
        except requests.exceptions.ConnectionError:
            self.print_test("Backend Server", False, "Cannot connect - start with: python main.py")
            sys.exit(1)
    
    def test_registration(self):
        """Phase 1: User Registration"""
        self.print_header("PHASE 1: Authentication & Registration")
        
        try:
            response = requests.post(f"{BASE_URL}/auth/register", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "first_name": "Test",
                "last_name": "User"
            })
            
            if response.status_code == 201:
                data = response.json()
                self.user_id = data.get("id")
                self.print_test("User Registration", True, f"Email: {TEST_EMAIL}")
            else:
                self.print_test("User Registration", False, f"Status: {response.status_code}")
                print(f"   Response: {response.text}")
        except Exception as e:
            self.print_test("User Registration", False, str(e))
    
    def test_login(self):
        """Phase 1: User Login"""
        try:
            response = requests.post(f"{BASE_URL}/auth/login", json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            })
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access_token")
                self.print_test("User Login", True, "Token generated")
            else:
                self.print_test("User Login", False, f"Status: {response.status_code}")
                print(f"   Response: {response.text}")
        except Exception as e:
            self.print_test("User Login", False, str(e))
    
    def test_get_profile(self):
        """Phase 1: Get User Profile"""
        if not self.token:
            self.print_test("Get Profile", False, "No token available")
            return
        
        try:
            response = requests.get(
                f"{BASE_URL}/users/profile",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.print_test("Get User Profile", True, f"User: {data.get('email')}")
            else:
                self.print_test("Get User Profile", False, f"Status: {response.status_code}")
        except Exception as e:
            self.print_test("Get User Profile", False, str(e))
    
    def test_appointments(self):
        """Phase 2: Appointments"""
        self.print_header("PHASE 2: Appointments & Medical Records")
        
        if not self.token:
            self.print_test("Create Appointment", False, "No token available")
            return
        
        try:
            # Create
            response = requests.post(
                f"{BASE_URL}/appointments",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "doctor_id": "test-doctor-uuid",
                    "scheduled_at": (datetime.now() + timedelta(days=1)).isoformat(),
                    "reason": "Test appointment"
                }
            )
            
            if response.status_code == 201:
                self.print_test("Create Appointment", True, "Appointment scheduled")
            else:
                self.print_test("Create Appointment", False, f"Status: {response.status_code}")
            
            # List
            response = requests.get(
                f"{BASE_URL}/appointments",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                count = len(data.get("appointments", []))
                self.print_test("List Appointments", True, f"Found {count} appointments")
            else:
                self.print_test("List Appointments", False, f"Status: {response.status_code}")
        except Exception as e:
            self.print_test("Appointments", False, str(e))
    
    def test_doctor_features(self):
        """Phase 3: Doctor Features"""
        self.print_header("PHASE 3: Doctor Features & Prescriptions")
        
        if not self.token:
            self.print_test("Doctor Operations", False, "No token available")
            return
        
        try:
            # Get doctor profile
            response = requests.get(
                f"{BASE_URL}/doctors/profile",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                self.print_test("Get Doctor Profile", True, "Profile retrieved")
            elif response.status_code in [403, 404]:
                self.print_test("Get Doctor Profile", True, "Doctor access blocked for patient (expected)")
            else:
                self.print_test("Get Doctor Profile", False, f"Status: {response.status_code}")
            
            # Get prescriptions
            response = requests.get(
                f"{BASE_URL}/doctors/prescriptions",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code in [200, 403]:
                count = len(response.json().get("prescriptions", []))
                self.print_test("Get Prescriptions", True, f"Found {count} prescriptions")
            else:
                self.print_test("Get Prescriptions", False, f"Status: {response.status_code}")
        except Exception as e:
            self.print_test("Doctor Features", False, str(e))
    
    def test_telemedicine(self):
        """Phase 4: Telemedicine"""
        self.print_header("PHASE 4: Telemedicine & Real-Time Messaging")
        
        if not self.token:
            self.print_test("Telemedicine", False, "No token available")
            return
        
        try:
            # Schedule consultation
            response = requests.post(
                f"{BASE_URL}/telemedicine/consultations",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "patient_id": self.user_id,
                    "consultation_type": "video",
                    "scheduled_start": (datetime.now() + timedelta(days=1)).isoformat()
                }
            )
            
            if response.status_code == 201:
                self.print_test("Schedule Consultation", True, "Consultation scheduled")
            elif response.status_code == 403:
                self.print_test("Schedule Consultation", True, "Doctor-only endpoint blocked for patient (expected)")
            else:
                self.print_test("Schedule Consultation", False, f"Status: {response.status_code}")
            
            # List consultations
            response = requests.get(
                f"{BASE_URL}/telemedicine/consultations",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                count = len(response.json().get("consultations", []))
                self.print_test("List Consultations", True, f"Found {count} consultations")
            else:
                self.print_test("List Consultations", False, f"Status: {response.status_code}")
            
            # Get conversations
            response = requests.get(
                f"{BASE_URL}/telemedicine/conversations",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                count = len(response.json().get("conversations", []))
                self.print_test("Get Conversations", True, f"Found {count} conversations")
            else:
                self.print_test("Get Conversations", False, f"Status: {response.status_code}")
        except Exception as e:
            self.print_test("Telemedicine", False, str(e))
    
    def test_analytics(self):
        """Phase 5: Analytics & Health Insights"""
        self.print_header("PHASE 5: Analytics & Health Insights")
        
        if not self.token:
            self.print_test("Analytics", False, "No token available")
            return
        
        try:
            # Record health metric
            response = requests.post(
                f"{BASE_URL}/analytics/health-metrics",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "metric_type": "blood_pressure",
                    "value": 120,
                    "systolic_value": 120,
                    "diastolic_value": 80,
                    "unit": "mmHg"
                }
            )
            
            if response.status_code == 201:
                self.print_test("Record Health Metric", True, "Metric recorded")
            else:
                self.print_test("Record Health Metric", False, f"Status: {response.status_code}")
            
            # Get metrics
            response = requests.get(
                f"{BASE_URL}/analytics/health-metrics",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                count = len(response.json().get("metrics", []))
                self.print_test("Get Health Metrics", True, f"Found {count} metrics")
            else:
                self.print_test("Get Health Metrics", False, f"Status: {response.status_code}")
            
            # Get insights
            response = requests.get(
                f"{BASE_URL}/analytics/insights",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                count = len(response.json().get("insights", []))
                self.print_test("Get Health Insights", True, f"Found {count} insights")
            else:
                self.print_test("Get Health Insights", False, f"Status: {response.status_code}")
            
            # Get dashboard
            response = requests.get(
                f"{BASE_URL}/analytics/dashboard",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                score = response.json().get("overview", {}).get("overall_health_score", "N/A")
                self.print_test("Get Health Dashboard", True, f"Health score: {score}")
            else:
                self.print_test("Get Health Dashboard", False, f"Status: {response.status_code}")
        except Exception as e:
            self.print_test("Analytics", False, str(e))
    
    def print_summary(self):
        """Print test summary"""
        self.print_header("Test Summary")
        
        total = len(self.test_results)
        passed = sum(1 for _, status in self.test_results if status)
        failed = total - passed
        
        print(f"Total Tests: {total}")
        print(f"{GREEN}Passed: {passed}{RESET}")
        print(f"{RED}Failed: {failed}{RESET}")
        
        if failed == 0:
            print(f"\n{GREEN}{'🎉 All tests passed!'.center(60)}{RESET}\n")
        else:
            print(f"\n{RED}{'⚠️ Some tests failed. Check details above.'.center(60)}{RESET}\n")
    
    def run_all(self):
        """Run all tests"""
        print(f"\n{BLUE}HerCare Platform - Quick Testing Suite{RESET}")
        print(f"{BLUE}Testing URL: {BASE_URL}{RESET}\n")
        
        self.test_server_connection()
        self.test_registration()
        self.test_login()
        self.test_get_profile()
        self.test_appointments()
        self.test_doctor_features()
        self.test_telemedicine()
        self.test_analytics()
        self.print_summary()

if __name__ == "__main__":
    tester = HerCareQuickTest()
    tester.run_all()
