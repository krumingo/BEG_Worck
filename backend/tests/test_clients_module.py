"""
Tests for Clients CRUD and Linking endpoints.
"""
import pytest
import requests
import os

from tests.test_utils import VALID_ADMIN_PASSWORD

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD


def get_admin_token():
    """Get admin auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


class TestClientsCRUD:
    """Test Clients CRUD operations"""

    def test_list_clients_format(self):
        """Test listing clients returns correct format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/clients",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        print(f"✓ Clients list: total={data['total']}")

    def test_create_client(self):
        """Test creating a new client"""
        token = get_admin_token()
        import uuid
        unique_phone = f"+35988{str(uuid.uuid4())[:7].replace('-', '')}"
        
        client_data = {
            "first_name": "Тест",
            "last_name": "Клиент",
            "phone": unique_phone,
            "email": "test.client@example.com",
            "address": "ул. Тестова 1",
            "notes": "Тестов клиент",
            "is_active": True
        }
        
        response = requests.post(
            f"{BASE_URL}/api/clients",
            json=client_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        
        assert data["first_name"] == "Тест"
        assert data["last_name"] == "Клиент"
        assert data["phone_normalized"] is not None
        assert "id" in data
        print(f"✓ Created client: id={data['id']}, name={data['first_name']} {data['last_name']}")
        
        return data["id"]

    def test_create_duplicate_phone_fails(self):
        """Test creating client with duplicate phone fails"""
        token = get_admin_token()
        
        # Create first client
        import uuid
        unique_phone = f"+35987{str(uuid.uuid4())[:7].replace('-', '')}"
        
        client_data = {
            "first_name": "Първи",
            "last_name": "Клиент",
            "phone": unique_phone
        }
        
        response1 = requests.post(
            f"{BASE_URL}/api/clients",
            json=client_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response1.status_code == 201
        
        # Try to create second client with same phone
        client_data["first_name"] = "Втори"
        response2 = requests.post(
            f"{BASE_URL}/api/clients",
            json=client_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response2.status_code == 400
        assert "already exists" in response2.json()["detail"]
        print(f"✓ Duplicate phone correctly rejected")

    def test_get_and_update_client(self):
        """Test getting and updating a client"""
        token = get_admin_token()
        
        # Create a client first
        import uuid
        unique_phone = f"+35986{str(uuid.uuid4())[:7].replace('-', '')}"
        
        create_response = requests.post(
            f"{BASE_URL}/api/clients",
            json={
                "first_name": "Обновяем",
                "last_name": "Клиент",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert create_response.status_code == 201
        client_id = create_response.json()["id"]
        
        # Get the client
        get_response = requests.get(
            f"{BASE_URL}/api/clients/{client_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert get_response.status_code == 200
        
        # Update the client
        update_response = requests.put(
            f"{BASE_URL}/api/clients/{client_id}",
            json={"first_name": "Обновен", "email": "updated@example.com"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["first_name"] == "Обновен"
        assert updated["email"] == "updated@example.com"
        print(f"✓ Client updated successfully")

    def test_delete_client(self):
        """Test deleting a client"""
        token = get_admin_token()
        
        # Create a client first
        import uuid
        unique_phone = f"+35985{str(uuid.uuid4())[:7].replace('-', '')}"
        
        create_response = requests.post(
            f"{BASE_URL}/api/clients",
            json={
                "first_name": "Изтриваем",
                "last_name": "Клиент",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert create_response.status_code == 201
        client_id = create_response.json()["id"]
        
        # Delete the client
        delete_response = requests.delete(
            f"{BASE_URL}/api/clients/{client_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["ok"] is True
        print(f"✓ Client deleted successfully")


class TestClientLinking:
    """Test Client-Counterparty linking"""

    def test_find_or_create_client(self):
        """Test find-or-create endpoint"""
        token = get_admin_token()
        
        import uuid
        unique_phone = f"+35984{str(uuid.uuid4())[:7].replace('-', '')}"
        
        # First call - should create
        response1 = requests.post(
            f"{BASE_URL}/api/clients/find-or-create",
            json={
                "first_name": "Нов",
                "last_name": "Клиент",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["created"] is True
        client_id = data1["client"]["id"]
        
        # Second call with same phone - should find existing
        response2 = requests.post(
            f"{BASE_URL}/api/clients/find-or-create",
            json={
                "first_name": "Друго",
                "last_name": "Име",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["created"] is False
        assert data2["client"]["id"] == client_id
        print(f"✓ Find-or-create works correctly")

    def test_get_client_by_phone(self):
        """Test getting client by phone number"""
        token = get_admin_token()
        
        import uuid
        unique_phone = f"+35983{str(uuid.uuid4())[:7].replace('-', '')}"
        
        # Create a client
        requests.post(
            f"{BASE_URL}/api/clients",
            json={
                "first_name": "Телефон",
                "last_name": "Клиент",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Find by phone
        response = requests.get(
            f"{BASE_URL}/api/clients/by-phone/{unique_phone}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "Телефон"
        print(f"✓ Get by phone works")


class TestCounterpartyClientLink:
    """Test Counterparty-Client linking endpoints"""

    def test_link_counterparty_to_client(self):
        """Test linking a counterparty to a client"""
        token = get_admin_token()
        
        import uuid
        unique_phone = f"+35982{str(uuid.uuid4())[:7].replace('-', '')}"
        
        # Create a client
        client_response = requests.post(
            f"{BASE_URL}/api/clients",
            json={
                "first_name": "Свързан",
                "last_name": "Клиент",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert client_response.status_code == 201
        client_id = client_response.json()["id"]
        
        # Create a counterparty
        cp_response = requests.post(
            f"{BASE_URL}/api/counterparties",
            json={
                "name": "Свързан Контрагент",
                "type": "person",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert cp_response.status_code == 201
        cp_id = cp_response.json()["id"]
        
        # Link them
        link_response = requests.post(
            f"{BASE_URL}/api/counterparties/{cp_id}/link-client",
            json={"client_id": client_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert link_response.status_code == 200
        assert link_response.json()["ok"] is True
        print(f"✓ Counterparty linked to client successfully")

    def test_auto_link_counterparty(self):
        """Test auto-link creates or finds client from counterparty phone"""
        token = get_admin_token()
        
        import uuid
        unique_phone = f"+35981{str(uuid.uuid4())[:7].replace('-', '')}"
        
        # Create a counterparty with phone
        cp_response = requests.post(
            f"{BASE_URL}/api/counterparties",
            json={
                "name": "Авто Свързване",
                "type": "person",
                "phone": unique_phone
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert cp_response.status_code == 201
        cp_id = cp_response.json()["id"]
        
        # Auto-link (should create new client)
        auto_link_response = requests.post(
            f"{BASE_URL}/api/counterparties/{cp_id}/auto-link-client",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert auto_link_response.status_code == 200
        data = auto_link_response.json()
        assert data["ok"] is True
        assert data["created"] is True
        assert "client_id" in data
        print(f"✓ Auto-link created client: {data['client_id']}")


class TestFinanceExport:
    """Test Finance Export endpoints"""

    def test_export_pdf(self):
        """Test PDF export returns valid response"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-export?year=2026&month=1&format=pdf",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert "content-disposition" in response.headers
        assert "finance_report" in response.headers["content-disposition"]
        assert len(response.content) > 1000  # Should have some content
        print(f"✓ PDF export works: {len(response.content)} bytes")

    def test_export_xlsx(self):
        """Test XLSX export returns valid response"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-export?year=2026&month=1&format=xlsx",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert "spreadsheet" in response.headers.get("content-type", "")
        assert "content-disposition" in response.headers
        assert len(response.content) > 1000  # Should have some content
        print(f"✓ XLSX export works: {len(response.content)} bytes")

    def test_export_invalid_month(self):
        """Test export with invalid month fails"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/company-finance-export?year=2026&month=13&format=pdf",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 422
        print(f"✓ Invalid month correctly rejected")
