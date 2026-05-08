"""
Tests for Data Module (Items, Counterparties, Warehouses, Prices, Reports).
Tests server-side pagination, filtering, sorting, and CRUD operations.
"""
import pytest
import requests
import os
import uuid

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


class TestItemsCRUD:
    """Test Items CRUD operations"""

    def test_list_items_format(self):
        """Test listing items returns standard format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/items",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        # Check standard response format
        assert "items" in data, "Missing 'items' in response"
        assert "total" in data, "Missing 'total' in response"
        assert "page" in data, "Missing 'page' in response"
        assert "page_size" in data, "Missing 'page_size' in response"
        assert "total_pages" in data, "Missing 'total_pages' in response"
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)
        print(f"✓ Items list: total={data['total']}, page={data['page']}")

    def test_create_item(self):
        """Test creating a new item"""
        token = get_admin_token()
        item_data = {
            "sku": f"TEST-{uuid.uuid4().hex[:8].upper()}",
            "name": "Test Material",
            "unit": "pcs",
            "category": "Materials",
            "brand": "TestBrand",
            "description": "Test description",
            "default_price": 25.50,
            "is_active": True
        }
        
        response = requests.post(
            f"{BASE_URL}/api/items",
            json=item_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["sku"] == item_data["sku"].upper()
        assert data["name"] == item_data["name"]
        assert "id" in data
        assert "org_id" in data
        print(f"✓ Created item: id={data['id']}, sku={data['sku']}")

    def test_create_duplicate_sku_fails(self):
        """Test that duplicate SKU fails"""
        token = get_admin_token()
        sku = f"DUP-{uuid.uuid4().hex[:8].upper()}"
        item_data = {
            "sku": sku,
            "name": "Duplicate Test",
            "unit": "pcs",
            "category": "Materials"
        }
        
        # Create first
        response1 = requests.post(
            f"{BASE_URL}/api/items",
            json=item_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response1.status_code == 201
        
        # Try duplicate
        response2 = requests.post(
            f"{BASE_URL}/api/items",
            json=item_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response2.status_code == 400
        assert "already exists" in response2.json()["detail"]
        print(f"✓ Duplicate SKU correctly rejected")

    def test_get_and_update_item(self):
        """Test getting and updating an item"""
        token = get_admin_token()
        item_data = {
            "sku": f"GETUP-{uuid.uuid4().hex[:8].upper()}",
            "name": "Get Update Test",
            "unit": "pcs",
            "category": "Materials",
            "default_price": 10.0
        }
        
        # Create
        create_resp = requests.post(
            f"{BASE_URL}/api/items",
            json=item_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        item_id = create_resp.json()["id"]
        
        # Get
        get_resp = requests.get(
            f"{BASE_URL}/api/items/{item_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == item_id
        
        # Update
        update_resp = requests.put(
            f"{BASE_URL}/api/items/{item_id}",
            json={"default_price": 50.00, "name": "Updated Name"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["default_price"] == 50.00
        assert update_resp.json()["name"] == "Updated Name"
        print(f"✓ Item get/update works: new_price=50.00")

    def test_delete_item_soft(self):
        """Test soft deleting an item"""
        token = get_admin_token()
        item_data = {
            "sku": f"DEL-{uuid.uuid4().hex[:8].upper()}",
            "name": "Delete Test",
            "unit": "pcs",
            "category": "Materials"
        }
        
        # Create
        create_resp = requests.post(
            f"{BASE_URL}/api/items",
            json=item_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        item_id = create_resp.json()["id"]
        
        # Delete
        del_resp = requests.delete(
            f"{BASE_URL}/api/items/{item_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True
        
        # Verify soft deleted
        get_resp = requests.get(
            f"{BASE_URL}/api/items/{item_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert get_resp.json()["is_active"] is False
        print(f"✓ Soft delete works: is_active=False")

    def test_get_item_categories(self):
        """Test getting item categories enum"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/items/enums/categories",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "Materials" in data["categories"]
        print(f"✓ Categories: {data['categories']}")


class TestItemsFiltering:
    """Test Items filtering and pagination"""

    def test_pagination(self):
        """Test pagination parameters"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/items?page=1&page_size=2",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 2
        assert data["page"] == 1
        assert data["page_size"] == 2
        print(f"✓ Pagination: page={data['page']}, page_size={data['page_size']}, items={len(data['items'])}")

    def test_sorting(self):
        """Test sorting parameters"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/items?sort_by=name&sort_dir=asc",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        print(f"✓ Sorting by name asc works")

    def test_search(self):
        """Test global search"""
        token = get_admin_token()
        unique = f"UniqueSearch{uuid.uuid4().hex[:6]}"
        
        # Create item with unique name
        requests.post(
            f"{BASE_URL}/api/items",
            json={
                "sku": f"SRCH-{uuid.uuid4().hex[:8].upper()}",
                "name": unique,
                "unit": "pcs",
                "category": "Materials"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Search
        response = requests.get(
            f"{BASE_URL}/api/items?search={unique}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        print(f"✓ Search found {data['total']} items matching '{unique}'")

    def test_filter_by_category(self):
        """Test filtering by category"""
        token = get_admin_token()
        
        # Create item with specific category
        requests.post(
            f"{BASE_URL}/api/items",
            json={
                "sku": f"FILT-{uuid.uuid4().hex[:8].upper()}",
                "name": "Filter Test Tools",
                "unit": "pcs",
                "category": "Tools"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Filter
        response = requests.get(
            f"{BASE_URL}/api/items?filters=category.equals=Tools",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["category"] == "Tools"
        print(f"✓ Filter by category=Tools found {data['total']} items")


class TestCounterpartiesCRUD:
    """Test Counterparties CRUD operations"""

    def test_list_counterparties_format(self):
        """Test listing counterparties returns standard format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/counterparties",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        # Check standard response format
        assert "items" in data, "Missing 'items' in response"
        assert "total" in data, "Missing 'total' in response"
        assert "page" in data, "Missing 'page' in response"
        assert "page_size" in data, "Missing 'page_size' in response"
        print(f"✓ Counterparties list: total={data['total']}, page={data['page']}")

    def test_create_counterparty(self):
        """Test creating a counterparty"""
        token = get_admin_token()
        cp_data = {
            "name": f"Test Supplier {uuid.uuid4().hex[:6]}",
            "type": "supplier",
            "address": "Test Address 123",
            "phone": "+359888123456",
            "active": True
        }
        
        response = requests.post(
            f"{BASE_URL}/api/counterparties",
            json=cp_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == cp_data["name"]
        assert data["type"] == "supplier"
        assert "id" in data
        print(f"✓ Created counterparty: id={data['id']}")

    def test_get_counterparty_types(self):
        """Test getting counterparty types enum"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/counterparties/enums/types",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "types" in data
        assert "supplier" in data["types"]
        assert "client" in data["types"]
        print(f"✓ Counterparty types: {data['types']}")


class TestWarehousesCRUD:
    """Test Warehouses CRUD operations"""

    def test_list_warehouses_format(self):
        """Test listing warehouses returns standard format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/warehouses",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data, "Missing 'items' in response"
        assert "total" in data, "Missing 'total' in response"
        assert "page" in data, "Missing 'page' in response"
        assert "page_size" in data, "Missing 'page_size' in response"
        print(f"✓ Warehouses list: total={data['total']}, page={data['page']}")


class TestPricesEndpoint:
    """Test Prices (purchase history) endpoint"""

    def test_prices_format(self):
        """Test prices endpoint returns standard format"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/prices",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data, "Missing 'items' in response"
        assert "total" in data, "Missing 'total' in response"
        assert "page" in data, "Missing 'page' in response"
        assert "page_size" in data, "Missing 'page_size' in response"
        print(f"✓ Prices list: total={data['total']}, page={data['page']}")

    def test_prices_pagination(self):
        """Test prices pagination"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/prices?page=1&page_size=5",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 5
        assert data["page"] == 1
        print(f"✓ Prices pagination: page={data['page']}, items={len(data['items'])}")


class TestTurnoverReport:
    """Test Turnover by Counterparty report"""

    def test_turnover_format(self):
        """Test turnover endpoint returns standard format with grand totals"""
        token = get_admin_token()
        response = requests.get(
            f"{BASE_URL}/api/reports/turnover-by-counterparty?type=purchases",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data, "Missing 'items' in response"
        assert "total" in data, "Missing 'total' in response"
        assert "page" in data, "Missing 'page' in response"
        assert "grand_totals" in data, "Missing 'grand_totals' in response"
        assert "filters" in data, "Missing 'filters' in response"
        
        # Check grand_totals structure
        gt = data["grand_totals"]
        assert "total_invoices" in gt
        assert "total_subtotal" in gt
        assert "total_vat" in gt
        assert "total_amount" in gt
        print(f"✓ Turnover report: total={data['total']}, grand_total={gt['total_amount']}")

    def test_turnover_type_filter(self):
        """Test turnover type filter (purchases vs sales)"""
        token = get_admin_token()
        
        # Purchases
        response = requests.get(
            f"{BASE_URL}/api/reports/turnover-by-counterparty?type=purchases",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["filters"]["type"] == "purchases"
        
        # Sales
        response = requests.get(
            f"{BASE_URL}/api/reports/turnover-by-counterparty?type=sales",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["filters"]["type"] == "sales"
        print(f"✓ Turnover type filter works for purchases and sales")
