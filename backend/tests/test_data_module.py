"""
Tests for Data Module (Items, Counterparties, Warehouses, Prices, Reports).
Tests server-side pagination, filtering, sorting, and CRUD operations.
Uses httpx for real HTTP requests against running server.
"""
import pytest
import httpx
import uuid

from tests.test_utils import VALID_ADMIN_PASSWORD


class TestItemsCRUD:
    """Test Items CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_items_empty(self, base_url):
        """Test listing items returns standard format"""
        async with httpx.AsyncClient(timeout=30) as client:
            # Login
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
            token = login_resp.json()["token"]
            
            # List items
            response = await client.get(
                f"{base_url}/api/items",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            # Check standard response format
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data
            assert "total_pages" in data
            assert isinstance(data["items"], list)
            assert isinstance(data["total"], int)

    @pytest.mark.asyncio
    async def test_create_item(self, base_url):
        """Test creating a new item"""
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
        
        async with httpx.AsyncClient(timeout=30) as client:
            # Login
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Create item
            response = await client.post(
                f"{base_url}/api/items",
                json=item_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 201
            data = response.json()
            assert data["sku"] == item_data["sku"].upper()
            assert data["name"] == item_data["name"]
            assert "id" in data
            assert "org_id" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_sku_fails(self, base_url):
        """Test that duplicate SKU fails"""
        sku = f"DUP-{uuid.uuid4().hex[:8].upper()}"
        item_data = {
            "sku": sku,
            "name": "Duplicate Test",
            "unit": "pcs",
            "category": "Materials"
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Create first
            response1 = await client.post(
                f"{base_url}/api/items",
                json=item_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response1.status_code == 201
            
            # Try duplicate
            response2 = await client.post(
                f"{base_url}/api/items",
                json=item_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response2.status_code == 400
            assert "already exists" in response2.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_and_update_item(self, base_url):
        """Test getting and updating an item"""
        item_data = {
            "sku": f"GETUP-{uuid.uuid4().hex[:8].upper()}",
            "name": "Get Update Test",
            "unit": "pcs",
            "category": "Materials",
            "default_price": 10.0
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Create
            create_resp = await client.post(
                f"{base_url}/api/items",
                json=item_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            item_id = create_resp.json()["id"]
            
            # Get
            get_resp = await client.get(
                f"{base_url}/api/items/{item_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert get_resp.status_code == 200
            assert get_resp.json()["id"] == item_id
            
            # Update
            update_resp = await client.put(
                f"{base_url}/api/items/{item_id}",
                json={"default_price": 50.00, "name": "Updated Name"},
                headers={"Authorization": f"Bearer {token}"}
            )
            assert update_resp.status_code == 200
            assert update_resp.json()["default_price"] == 50.00
            assert update_resp.json()["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_item_soft(self, base_url):
        """Test soft deleting an item"""
        item_data = {
            "sku": f"DEL-{uuid.uuid4().hex[:8].upper()}",
            "name": "Delete Test",
            "unit": "pcs",
            "category": "Materials"
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Create
            create_resp = await client.post(
                f"{base_url}/api/items",
                json=item_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            item_id = create_resp.json()["id"]
            
            # Delete
            del_resp = await client.delete(
                f"{base_url}/api/items/{item_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert del_resp.status_code == 200
            assert del_resp.json()["ok"] is True
            
            # Verify soft deleted
            get_resp = await client.get(
                f"{base_url}/api/items/{item_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert get_resp.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_get_item_categories(self, base_url):
        """Test getting item categories enum"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/items/enums/categories",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "categories" in data
            assert "Materials" in data["categories"]


class TestItemsFiltering:
    """Test Items filtering and pagination"""

    @pytest.mark.asyncio
    async def test_pagination(self, base_url):
        """Test pagination parameters"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Test page_size
            response = await client.get(
                f"{base_url}/api/items?page=1&page_size=2",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) <= 2
            assert data["page"] == 1
            assert data["page_size"] == 2

    @pytest.mark.asyncio
    async def test_sorting(self, base_url):
        """Test sorting parameters"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Sort by name asc
            response = await client.get(
                f"{base_url}/api/items?sort_by=name&sort_dir=asc",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_search(self, base_url):
        """Test global search"""
        unique = f"UniqueSearch{uuid.uuid4().hex[:6]}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Create item with unique name
            await client.post(
                f"{base_url}/api/items",
                json={
                    "sku": f"SRCH-{uuid.uuid4().hex[:8].upper()}",
                    "name": unique,
                    "unit": "pcs",
                    "category": "Materials"
                },
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Search
            response = await client.get(
                f"{base_url}/api/items?search={unique}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_category(self, base_url):
        """Test filtering by category"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Create item with specific category
            await client.post(
                f"{base_url}/api/items",
                json={
                    "sku": f"FILT-{uuid.uuid4().hex[:8].upper()}",
                    "name": "Filter Test Tools",
                    "unit": "pcs",
                    "category": "Tools"
                },
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Filter
            response = await client.get(
                f"{base_url}/api/items?filters=category.equals=Tools",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            for item in data["items"]:
                assert item["category"] == "Tools"


class TestCounterpartiesCRUD:
    """Test Counterparties CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_counterparties_format(self, base_url):
        """Test listing counterparties returns standard format"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/counterparties",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            # Check standard response format
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data

    @pytest.mark.asyncio
    async def test_create_counterparty(self, base_url):
        """Test creating a counterparty"""
        cp_data = {
            "name": f"Test Supplier {uuid.uuid4().hex[:6]}",
            "type": "supplier",
            "address": "Test Address 123",
            "phone": "+359888123456",
            "active": True
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.post(
                f"{base_url}/api/counterparties",
                json=cp_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 201
            data = response.json()
            assert data["name"] == cp_data["name"]
            assert data["type"] == "supplier"
            assert "id" in data

    @pytest.mark.asyncio
    async def test_get_counterparty_types(self, base_url):
        """Test getting counterparty types enum"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/counterparties/enums/types",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "types" in data
            assert "supplier" in data["types"]
            assert "client" in data["types"]


class TestWarehousesCRUD:
    """Test Warehouses CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_warehouses_format(self, base_url):
        """Test listing warehouses returns standard format"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/warehouses",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data


class TestPricesEndpoint:
    """Test Prices (purchase history) endpoint"""

    @pytest.mark.asyncio
    async def test_prices_format(self, base_url):
        """Test prices endpoint returns standard format"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/prices",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data

    @pytest.mark.asyncio
    async def test_prices_pagination(self, base_url):
        """Test prices pagination"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/prices?page=1&page_size=5",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) <= 5
            assert data["page"] == 1


class TestTurnoverReport:
    """Test Turnover by Counterparty report"""

    @pytest.mark.asyncio
    async def test_turnover_format(self, base_url):
        """Test turnover endpoint returns standard format with grand totals"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            response = await client.get(
                f"{base_url}/api/reports/turnover-by-counterparty?type=purchases",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "grand_totals" in data
            assert "filters" in data
            
            # Check grand_totals structure
            gt = data["grand_totals"]
            assert "total_invoices" in gt
            assert "total_subtotal" in gt
            assert "total_vat" in gt
            assert "total_amount" in gt

    @pytest.mark.asyncio
    async def test_turnover_type_filter(self, base_url):
        """Test turnover type filter (purchases vs sales)"""
        async with httpx.AsyncClient(timeout=30) as client:
            login_resp = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
            )
            token = login_resp.json()["token"]
            
            # Purchases
            response = await client.get(
                f"{base_url}/api/reports/turnover-by-counterparty?type=purchases",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["filters"]["type"] == "purchases"
            
            # Sales
            response = await client.get(
                f"{base_url}/api/reports/turnover-by-counterparty?type=sales",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["filters"]["type"] == "sales"
