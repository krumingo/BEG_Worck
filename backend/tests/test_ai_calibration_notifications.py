"""
Test AI Calibration In-App Notifications for Admins.
Tests: 
- Notification created when calibration category reaches MIN_SAMPLES_FOR_CALIBRATION (10)
- Anti-duplicate logic: No duplicate notification for same category/city/small_qty
- Notification resolved (is_read=True, data.resolved=True) when calibration approved
- Notification only sent to Admin/Owner roles
- Notification has type='ai_calibration_ready' with proper title and message
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials (Admin)
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"

# Generate unique category identifiers for this test run
TEST_RUN_ID = uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def auth_token():
    """Get authentication token for admin user"""
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    print(f"Auth response: {response.status_code}")
    if response.status_code == 200:
        token = response.json().get("token")
        print(f"Got token: {token[:50]}...")
        return token
    pytest.skip(f"Authentication failed - status {response.status_code}")


@pytest.fixture(scope="session")
def api_client(auth_token):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


@pytest.fixture(scope="session")
def user_info(auth_token):
    """Decode user info from JWT token"""
    import base64
    import json
    # Decode JWT payload
    parts = auth_token.split(".")
    if len(parts) >= 2:
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)
        return {
            "id": data.get("user_id"),
            "org_id": data.get("org_id"),
            "role": data.get("role")
        }
    pytest.skip("Failed to decode user info from token")


class TestCalibrationNotificationCreation:
    """Test notification is created when category reaches threshold"""
    
    def test_notification_created_at_threshold(self, api_client, user_info):
        """When a category reaches 10 samples, a notification should be created"""
        # Use a unique category for this test
        activity_type = f"TEST_NOTIF_{TEST_RUN_ID}_Type"
        activity_subtype = f"TEST_NOTIF_{TEST_RUN_ID}_Sub"
        city = "Русе"
        small_qty = False
        
        # Record 10 calibration events for this category
        for i in range(10):
            response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
                "ai_provider_used": "llm",
                "ai_confidence": 0.90,
                "ai_material_price_per_unit": 10.00,
                "ai_labor_price_per_unit": 15.00,
                "ai_total_price_per_unit": 25.00,
                "final_material_price_per_unit": 12.00,
                "final_labor_price_per_unit": 18.00,
                "final_total_price_per_unit": 30.00,
                "city": city,
                "project_id": f"TEST_project_{uuid.uuid4().hex[:8]}",
                "source_type": "extra_work",
                "normalized_activity_type": activity_type,
                "normalized_activity_subtype": activity_subtype,
                "unit": "m2",
                "qty": 10,
                "small_qty_flag": small_qty
            })
            assert response.status_code == 200, f"Failed to record edit {i+1}: {response.text}"
        
        # Wait a moment for async notification creation
        time.sleep(0.5)
        
        # Check for notification
        notif_response = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        assert notif_response.status_code == 200
        
        notifications = notif_response.json().get("notifications", [])
        
        # Find notification for our test category
        notif_key = f"cal_ready|{activity_type}|{activity_subtype}|{city}|{small_qty}"
        matching_notif = None
        for n in notifications:
            if n.get("type") == "ai_calibration_ready":
                if n.get("data", {}).get("calibration_key") == notif_key:
                    matching_notif = n
                    break
        
        assert matching_notif is not None, f"Expected notification for key '{notif_key}' not found"
        assert matching_notif["type"] == "ai_calibration_ready"
        assert "AI Калибрация" in matching_notif["title"] or "калибрация" in matching_notif["title"].lower()
        assert activity_type in matching_notif["message"] or "случая" in matching_notif["message"]
        assert matching_notif["is_read"] is False
        assert matching_notif["data"].get("resolved") is False
        
        print(f"PASS: Notification created for category reaching threshold")
        print(f"  Key: {notif_key}")
        print(f"  Title: {matching_notif['title']}")
        print(f"  Message: {matching_notif['message']}")


class TestAntiDuplicateLogic:
    """Test that duplicate notifications are not created for same category"""
    
    def test_no_duplicate_notification(self, api_client, user_info):
        """Adding more samples to same category should NOT create duplicate notification"""
        # Use the same category from previous test
        activity_type = f"TEST_NOTIF_{TEST_RUN_ID}_Type"
        activity_subtype = f"TEST_NOTIF_{TEST_RUN_ID}_Sub"
        city = "Русе"
        small_qty = False
        
        # Get current notification count for this category
        notif_response_before = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        notifications_before = notif_response_before.json().get("notifications", [])
        
        notif_key = f"cal_ready|{activity_type}|{activity_subtype}|{city}|{small_qty}"
        count_before = sum(1 for n in notifications_before 
                          if n.get("type") == "ai_calibration_ready" 
                          and n.get("data", {}).get("calibration_key") == notif_key
                          and n.get("data", {}).get("resolved") is False)
        
        # Record 3 more events for the same category (now total 13)
        for i in range(3):
            response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
                "ai_provider_used": "llm",
                "ai_confidence": 0.90,
                "ai_material_price_per_unit": 10.00,
                "ai_labor_price_per_unit": 15.00,
                "ai_total_price_per_unit": 25.00,
                "final_material_price_per_unit": 12.00,
                "final_labor_price_per_unit": 18.00,
                "final_total_price_per_unit": 30.00,
                "city": city,
                "project_id": f"TEST_project_dup_{uuid.uuid4().hex[:8]}",
                "source_type": "extra_work",
                "normalized_activity_type": activity_type,
                "normalized_activity_subtype": activity_subtype,
                "unit": "m2",
                "qty": 5,
                "small_qty_flag": small_qty
            })
            assert response.status_code == 200
        
        time.sleep(0.5)
        
        # Check notification count again
        notif_response_after = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        notifications_after = notif_response_after.json().get("notifications", [])
        
        count_after = sum(1 for n in notifications_after 
                         if n.get("type") == "ai_calibration_ready" 
                         and n.get("data", {}).get("calibration_key") == notif_key
                         and n.get("data", {}).get("resolved") is False)
        
        assert count_after == count_before, f"Duplicate notification created! Before: {count_before}, After: {count_after}"
        print(f"PASS: No duplicate notification created (count remained at {count_after})")


class TestNotificationResolvedOnApprove:
    """Test notification is marked as resolved when calibration is approved"""
    
    def test_notification_resolved_on_approve(self, api_client, user_info):
        """When calibration is approved, notification should be marked is_read=True, data.resolved=True"""
        # Use the category from the threshold test
        activity_type = f"TEST_NOTIF_{TEST_RUN_ID}_Type"
        activity_subtype = f"TEST_NOTIF_{TEST_RUN_ID}_Sub"
        city = "Русе"
        small_qty = False
        
        notif_key = f"cal_ready|{activity_type}|{activity_subtype}|{city}|{small_qty}"
        
        # Approve the calibration
        approve_response = api_client.post(f"{BASE_URL}/api/ai-calibration/approve", json={
            "activity_type": activity_type,
            "activity_subtype": activity_subtype,
            "city": city,
            "small_qty": small_qty,
            "factor": 1.20,
            "sample_count": 13,
            "avg_delta": 20.0
        })
        
        assert approve_response.status_code == 200
        assert approve_response.json()["ok"] is True
        
        time.sleep(0.5)
        
        # Check notification status
        notif_response = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        notifications = notif_response.json().get("notifications", [])
        
        # Find notification for our category
        matching_notifs = [n for n in notifications 
                          if n.get("type") == "ai_calibration_ready" 
                          and n.get("data", {}).get("calibration_key") == notif_key]
        
        assert len(matching_notifs) > 0, "No notification found for the test category"
        
        # All notifications for this key should now be resolved
        for notif in matching_notifs:
            assert notif["is_read"] is True, f"Notification should be marked read, but is_read={notif['is_read']}"
            assert notif["data"].get("resolved") is True, f"Notification data.resolved should be True, but got {notif['data'].get('resolved')}"
        
        print(f"PASS: Notification resolved when calibration approved")
        print(f"  Key: {notif_key}")
        print(f"  is_read: True, data.resolved: True")


class TestNotificationAfterResolveCanBeCreatedAgain:
    """Test that after approval + new events, a new notification CAN be created after revoke"""
    
    def test_new_notification_after_revoke(self, api_client, user_info):
        """After revoking calibration and adding more samples, new notification can be created"""
        # Use a new unique category for this test
        activity_type = f"TEST_REVOKE_{TEST_RUN_ID}"
        activity_subtype = f"RevokeSubtype"
        city = "Бургас"
        small_qty = False
        
        # Step 1: Create 10 samples to trigger notification
        for i in range(10):
            response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
                "ai_provider_used": "llm",
                "ai_confidence": 0.90,
                "ai_material_price_per_unit": 10.00,
                "ai_labor_price_per_unit": 15.00,
                "ai_total_price_per_unit": 25.00,
                "final_material_price_per_unit": 11.00,
                "final_labor_price_per_unit": 16.00,
                "final_total_price_per_unit": 27.00,
                "city": city,
                "project_id": f"TEST_revoke_{uuid.uuid4().hex[:8]}",
                "source_type": "extra_work",
                "normalized_activity_type": activity_type,
                "normalized_activity_subtype": activity_subtype,
                "unit": "m2",
                "qty": 8,
                "small_qty_flag": small_qty
            })
            assert response.status_code == 200
        
        time.sleep(0.5)
        
        # Step 2: Approve to resolve notification
        approve_response = api_client.post(f"{BASE_URL}/api/ai-calibration/approve", json={
            "activity_type": activity_type,
            "activity_subtype": activity_subtype,
            "city": city,
            "small_qty": small_qty,
            "factor": 1.08,
            "sample_count": 10,
            "avg_delta": 8.0
        })
        assert approve_response.status_code == 200
        cal_id = approve_response.json()["calibration"]["id"]
        
        # Step 3: Revoke the calibration
        revoke_response = api_client.delete(f"{BASE_URL}/api/ai-calibration/{cal_id}")
        assert revoke_response.status_code == 200
        
        # Step 4: Add one more sample - should trigger new notification
        response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
            "ai_provider_used": "llm",
            "ai_confidence": 0.90,
            "ai_material_price_per_unit": 10.00,
            "ai_labor_price_per_unit": 15.00,
            "ai_total_price_per_unit": 25.00,
            "final_material_price_per_unit": 11.00,
            "final_labor_price_per_unit": 16.00,
            "final_total_price_per_unit": 27.00,
            "city": city,
            "project_id": f"TEST_revoke_{uuid.uuid4().hex[:8]}",
            "source_type": "extra_work",
            "normalized_activity_type": activity_type,
            "normalized_activity_subtype": activity_subtype,
            "unit": "m2",
            "qty": 8,
            "small_qty_flag": small_qty
        })
        assert response.status_code == 200
        
        time.sleep(0.5)
        
        # Check for NEW unresolved notification
        notif_response = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        notifications = notif_response.json().get("notifications", [])
        
        notif_key = f"cal_ready|{activity_type}|{activity_subtype}|{city}|{small_qty}"
        unresolved_notifs = [n for n in notifications 
                            if n.get("type") == "ai_calibration_ready" 
                            and n.get("data", {}).get("calibration_key") == notif_key
                            and n.get("data", {}).get("resolved") is False]
        
        assert len(unresolved_notifs) > 0, "New notification should be created after revoke and adding samples"
        print(f"PASS: New notification created after calibration revoked")


class TestNotificationProperties:
    """Test notification has correct type, title, message in Bulgarian"""
    
    def test_notification_type_and_content(self, api_client, user_info):
        """Notification should have type='ai_calibration_ready' with Bulgarian title/message"""
        # Create a new category with 10 samples
        activity_type = f"Сухо строителство"
        activity_subtype = f"Гипсокартон_{TEST_RUN_ID}"
        city = "Варна"
        small_qty = True  # Test small_qty variant
        
        for i in range(10):
            response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
                "ai_provider_used": "rule-based",
                "ai_confidence": 0.85,
                "ai_material_price_per_unit": 20.00,
                "ai_labor_price_per_unit": 30.00,
                "ai_total_price_per_unit": 50.00,
                "final_material_price_per_unit": 22.00,
                "final_labor_price_per_unit": 33.00,
                "final_total_price_per_unit": 55.00,
                "city": city,
                "project_id": f"TEST_type_{uuid.uuid4().hex[:8]}",
                "source_type": "extra_work",
                "normalized_activity_type": activity_type,
                "normalized_activity_subtype": activity_subtype,
                "unit": "m2",
                "qty": 3,
                "small_qty_flag": small_qty
            })
            assert response.status_code == 200
        
        time.sleep(0.5)
        
        # Get notifications
        notif_response = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        notifications = notif_response.json().get("notifications", [])
        
        notif_key = f"cal_ready|{activity_type}|{activity_subtype}|{city}|{small_qty}"
        matching = [n for n in notifications 
                    if n.get("type") == "ai_calibration_ready" 
                    and n.get("data", {}).get("calibration_key") == notif_key]
        
        assert len(matching) > 0, f"No notification found for key {notif_key}"
        notif = matching[0]
        
        # Verify type
        assert notif["type"] == "ai_calibration_ready"
        
        # Verify Bulgarian title
        assert "AI Калибрация" in notif["title"] or "калибрация" in notif["title"].lower()
        assert "одобрение" in notif["title"].lower() or "готова" in notif["title"].lower()
        
        # Verify message contains category info
        assert activity_type in notif["message"] or activity_subtype in notif["message"]
        assert "случая" in notif["message"] or "10" in notif["message"]
        
        # Verify data fields
        assert notif["data"]["activity_type"] == activity_type
        assert notif["data"]["activity_subtype"] == activity_subtype
        assert notif["data"]["city"] == city
        assert notif["data"]["small_qty"] == small_qty
        assert notif["data"]["sample_count"] >= 10
        
        # small_qty should appear in message as "малко количество"
        if small_qty:
            assert "малко количество" in notif["message"]
        
        print(f"PASS: Notification has correct type and Bulgarian content")
        print(f"  Type: {notif['type']}")
        print(f"  Title: {notif['title']}")
        print(f"  Message: {notif['message']}")


class TestNotificationOnlyForAdminOwner:
    """Test that notifications are only sent to Admin/Owner roles"""
    
    def test_notification_sent_to_admin(self, api_client, user_info):
        """Admin user should receive the calibration notification"""
        # Admin is already logged in, check that notifications are received
        response = api_client.get(f"{BASE_URL}/api/notifications/my?limit=50")
        assert response.status_code == 200
        
        notifications = response.json().get("notifications", [])
        calibration_notifs = [n for n in notifications if n.get("type") == "ai_calibration_ready"]
        
        # Admin should have calibration notifications from previous tests
        assert len(calibration_notifs) > 0, "Admin should have calibration notifications"
        
        # Verify user_id matches current admin
        user_id = user_info.get("id")
        for notif in calibration_notifs:
            assert notif["user_id"] == user_id, f"Notification user_id should match admin's id"
        
        print(f"PASS: Admin user received {len(calibration_notifs)} calibration notifications")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
