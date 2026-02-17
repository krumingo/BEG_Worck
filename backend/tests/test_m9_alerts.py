"""
M9 Alerts Feature - Backend API Tests
Tests for Reminder and Notification endpoints
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAuth:
    """Authentication and login tests"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Login as admin and get token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        assert "token" in data
        return data["token"]
    
    @pytest.fixture(scope="class")
    def tech_token(self):
        """Login as technician and get token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "tech2@begwork.com",
            "password": "tech123"
        })
        if response.status_code != 200:
            pytest.skip("tech2@begwork.com user not found - skipping tech tests")
        data = response.json()
        return data["token"]
    
    def test_admin_login(self):
        """Test admin login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["email"] == "admin@begwork.com"
        assert data["user"]["role"] == "Admin"
        print(f"Admin login successful: {data['user']['email']}")
    
    def test_tech_login(self):
        """Test technician login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "tech2@begwork.com", 
            "password": "tech123"
        })
        # May not exist - that's OK
        if response.status_code == 401:
            pytest.skip("tech2@begwork.com not found")
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        print(f"Tech login successful: {data['user']['email']}")


class TestReminderPolicy:
    """Test reminder policy endpoint"""
    
    @pytest.fixture(scope="class") 
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_get_reminder_policy(self, admin_headers):
        """GET /api/reminders/policy - Get reminder policy settings"""
        response = requests.get(f"{BASE_URL}/api/reminders/policy", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "attendance_deadline" in data
        assert "work_report_deadline" in data
        assert "max_reminders_per_day" in data
        assert "escalation_after_days" in data
        assert "timezone" in data
        print(f"Reminder policy: {data}")


class TestMissingAttendance:
    """Test missing attendance endpoints"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_get_missing_attendance(self, admin_headers):
        """GET /api/reminders/missing-attendance - Get users with missing attendance"""
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.get(f"{BASE_URL}/api/reminders/missing-attendance?date={today}", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Missing attendance count: {len(data)}")
        if data:
            assert "user_id" in data[0]
            assert "user_name" in data[0]
            assert "user_email" in data[0]
    
    def test_missing_attendance_requires_manager(self):
        """Verify non-manager cannot access missing attendance"""
        # Try without auth
        response = requests.get(f"{BASE_URL}/api/reminders/missing-attendance")
        assert response.status_code == 403 or response.status_code == 401


class TestMissingWorkReports:
    """Test missing work reports endpoints"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_get_missing_work_reports(self, admin_headers):
        """GET /api/reminders/missing-work-reports - Get users with missing work reports"""
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.get(f"{BASE_URL}/api/reminders/missing-work-reports?date={today}", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Missing work reports count: {len(data)}")
        if data:
            assert "user_id" in data[0]
            assert "user_name" in data[0]
            assert "project_id" in data[0]


class TestReminderLogs:
    """Test reminder logs endpoint"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_get_reminder_logs(self, admin_headers):
        """GET /api/reminders/logs - Get reminder logs"""
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.get(f"{BASE_URL}/api/reminders/logs?date={today}", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Reminder logs count: {len(data)}")
        if data:
            assert "id" in data[0]
            assert "type" in data[0]
            assert "status" in data[0]


class TestSendReminders:
    """Test send reminder endpoint"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    @pytest.fixture(scope="class")
    def test_user_id(self, admin_headers):
        """Get a test user ID"""
        response = requests.get(f"{BASE_URL}/api/users", headers=admin_headers)
        if response.status_code == 200:
            users = response.json()
            # Find a non-admin user
            for user in users:
                if user.get("role") not in ["Admin", "Owner"]:
                    return user["id"]
        return None
    
    def test_send_reminder_missing_attendance(self, admin_headers, test_user_id):
        """POST /api/reminders/send - Send reminder for missing attendance"""
        if not test_user_id:
            pytest.skip("No non-admin user found to send reminder to")
        
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.post(f"{BASE_URL}/api/reminders/send", headers=admin_headers, json={
            "type": "MissingAttendance",
            "date": today,
            "user_ids": [test_user_id]
        })
        assert response.status_code == 200
        data = response.json()
        assert "sent" in data
        assert "total" in data
        print(f"Sent reminders: {data['sent']} of {data['total']}")
    
    def test_send_reminder_requires_manager(self):
        """Verify non-manager cannot send reminders"""
        response = requests.post(f"{BASE_URL}/api/reminders/send", json={
            "type": "MissingAttendance",
            "date": "2025-01-01",
            "user_ids": ["test-user"]
        })
        assert response.status_code == 403 or response.status_code == 401


class TestExcuseReminder:
    """Test excuse reminder endpoint"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    @pytest.fixture(scope="class")
    def test_user_id(self, admin_headers):
        """Get a test user ID"""
        response = requests.get(f"{BASE_URL}/api/users", headers=admin_headers)
        if response.status_code == 200:
            users = response.json()
            for user in users:
                if user.get("role") not in ["Admin", "Owner"]:
                    return user["id"]
        return None
    
    def test_excuse_reminder(self, admin_headers, test_user_id):
        """POST /api/reminders/excuse - Excuse a user from reminder"""
        if not test_user_id:
            pytest.skip("No non-admin user found")
        
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.post(f"{BASE_URL}/api/reminders/excuse", headers=admin_headers, json={
            "type": "MissingAttendance",
            "date": today,
            "user_id": test_user_id,
            "reason": "Test excuse - sick leave"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        print(f"Excused reminder for user: {test_user_id}")


class TestNotifications:
    """Test notification endpoints"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_get_my_notifications(self, admin_headers):
        """GET /api/notifications/my - Get user's notifications"""
        response = requests.get(f"{BASE_URL}/api/notifications/my", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "unread_count" in data
        assert isinstance(data["notifications"], list)
        assert isinstance(data["unread_count"], int)
        print(f"Notifications: {len(data['notifications'])}, Unread: {data['unread_count']}")
    
    def test_mark_notifications_read(self, admin_headers):
        """POST /api/notifications/mark-read - Mark all notifications as read"""
        response = requests.post(f"{BASE_URL}/api/notifications/mark-read", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        
        # Verify unread count is now 0
        response2 = requests.get(f"{BASE_URL}/api/notifications/my", headers=admin_headers)
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["unread_count"] == 0
        print("All notifications marked as read")


class TestDashboardStats:
    """Test dashboard stats include reminder info"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "admin123"
        })
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_dashboard_stats(self, admin_headers):
        """GET /api/dashboard/stats - Get dashboard stats"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "active_projects" in data
        assert "users_count" in data
        assert "today_present" in data
        print(f"Dashboard stats: {data}")


class TestInternalReminderJobs:
    """Test internal reminder job trigger"""
    
    def test_trigger_reminder_jobs(self):
        """POST /api/internal/run-reminder-jobs - Trigger reminder job"""
        response = requests.post(f"{BASE_URL}/api/internal/run-reminder-jobs")
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        assert "ran_at" in data
        print(f"Reminder jobs ran at: {data['ran_at']}")


class TestHealthEndpoint:
    """Test health endpoint"""
    
    def test_health(self):
        """GET /api/health - Health check"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
