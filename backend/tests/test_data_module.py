"""
Tests for Data Module (Items, Counterparties, Warehouses, Prices, Reports).
Tests server-side pagination, filtering, sorting, and CRUD operations.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
import uuid

# Test settings
BASE_URL = "http://test"


@pytest.fixture
def test_item_data():
    """Sample item data for testing"""
    return {
        "sku": f"TEST-{uuid.uuid4().hex[:8].upper()}",
        "name": "Test Material",
        "unit": "pcs",
        "category": "Materials",
        "brand": "TestBrand",
        "description": "Test description",
        "default_price": 25.50,
        "is_active": True
    }


@pytest.fixture
def test_counterparty_data():
    """Sample counterparty data for testing"""
    return {
        "name": f"Test Supplier {uuid.uuid4().hex[:6]}",
        "type": "supplier",
        "eik": f"BG{uuid.uuid4().hex[:9].upper()}",
        "vat_number": f"BG{uuid.uuid4().hex[:9].upper()}",
        "address": "Test Address 123",
        "phone": "+359888123456",
        "email": "test@supplier.com",
        "contact_person": "John Doe",
        "payment_terms_days": 30,
        "active": True
    }


class TestItemsCRUD:
    """Test Items CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_items_empty(self, app, admin_token):
        """Test listing items returns standard format"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/items",
                headers={"Authorization": f"Bearer {admin_token}"}
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
    async def test_create_item(self, app, admin_token, test_item_data):
        """Test creating a new item"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.post(
                "/api/items",
                json=test_item_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 201
            data = response.json()
            assert data["sku"] == test_item_data["sku"].upper()
            assert data["name"] == test_item_data["name"]
            assert "id" in data
            assert "org_id" in data
            return data["id"]

    @pytest.mark.asyncio
    async def test_create_duplicate_sku_fails(self, app, admin_token, test_item_data):
        """Test that duplicate SKU fails"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create first
            response1 = await client.post(
                "/api/items",
                json=test_item_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response1.status_code == 201
            
            # Try duplicate
            response2 = await client.post(
                "/api/items",
                json=test_item_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response2.status_code == 400
            assert "already exists" in response2.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_item(self, app, admin_token, test_item_data):
        """Test getting a single item"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create
            create_resp = await client.post(
                "/api/items",
                json=test_item_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            item_id = create_resp.json()["id"]
            
            # Get
            response = await client.get(
                f"/api/items/{item_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == item_id
            assert data["sku"] == test_item_data["sku"].upper()

    @pytest.mark.asyncio
    async def test_update_item(self, app, admin_token, test_item_data):
        """Test updating an item"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create
            create_resp = await client.post(
                "/api/items",
                json=test_item_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            item_id = create_resp.json()["id"]
            
            # Update
            response = await client.put(
                f"/api/items/{item_id}",
                json={"default_price": 50.00, "name": "Updated Name"},
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["default_price"] == 50.00
            assert data["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_item_soft(self, app, admin_token, test_item_data):
        """Test soft deleting an item"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create
            create_resp = await client.post(
                "/api/items",
                json=test_item_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            item_id = create_resp.json()["id"]
            
            # Delete
            response = await client.delete(
                f"/api/items/{item_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True
            
            # Verify soft deleted (is_active=False)
            get_resp = await client.get(
                f"/api/items/{item_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert get_resp.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_get_item_categories(self, app, admin_token):
        """Test getting item categories enum"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/items/enums/categories",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "categories" in data
            assert "Materials" in data["categories"]


class TestItemsFiltering:
    """Test Items filtering and pagination"""

    @pytest.mark.asyncio
    async def test_pagination(self, app, admin_token):
        """Test pagination parameters"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create multiple items
            for i in range(5):
                await client.post(
                    "/api/items",
                    json={
                        "sku": f"PAGE-{uuid.uuid4().hex[:8].upper()}",
                        "name": f"Pagination Test {i}",
                        "unit": "pcs",
                        "category": "Materials"
                    },
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
            
            # Test page_size
            response = await client.get(
                "/api/items?page=1&page_size=2",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) <= 2
            assert data["page"] == 1
            assert data["page_size"] == 2

    @pytest.mark.asyncio
    async def test_sorting(self, app, admin_token):
        """Test sorting parameters"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create items with different names
            names = ["Alpha", "Zeta", "Beta"]
            for name in names:
                await client.post(
                    "/api/items",
                    json={
                        "sku": f"SORT-{uuid.uuid4().hex[:8].upper()}",
                        "name": f"Sort {name}",
                        "unit": "pcs",
                        "category": "Materials"
                    },
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
            
            # Sort by name asc
            response = await client.get(
                "/api/items?sort_by=name&sort_dir=asc",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_search(self, app, admin_token):
        """Test global search"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create item with unique name
            unique = f"UniqueSearch{uuid.uuid4().hex[:6]}"
            await client.post(
                "/api/items",
                json={
                    "sku": f"SRCH-{uuid.uuid4().hex[:8].upper()}",
                    "name": unique,
                    "unit": "pcs",
                    "category": "Materials"
                },
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            # Search
            response = await client.get(
                f"/api/items?search={unique}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_category(self, app, admin_token):
        """Test filtering by category"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Create item with specific category
            await client.post(
                "/api/items",
                json={
                    "sku": f"FILT-{uuid.uuid4().hex[:8].upper()}",
                    "name": "Filter Test Tools",
                    "unit": "pcs",
                    "category": "Tools"
                },
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            
            # Filter
            response = await client.get(
                "/api/items?filters=category.equals=Tools",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            for item in data["items"]:
                assert item["category"] == "Tools"


class TestCounterpartiesCRUD:
    """Test Counterparties CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_counterparties_format(self, app, admin_token):
        """Test listing counterparties returns standard format"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/counterparties",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            # Check standard response format
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data

    @pytest.mark.asyncio
    async def test_create_counterparty(self, app, admin_token, test_counterparty_data):
        """Test creating a counterparty"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.post(
                "/api/counterparties",
                json=test_counterparty_data,
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 201
            data = response.json()
            assert data["name"] == test_counterparty_data["name"]
            assert data["type"] == "supplier"
            assert "id" in data

    @pytest.mark.asyncio
    async def test_get_counterparty_types(self, app, admin_token):
        """Test getting counterparty types enum"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/counterparties/enums/types",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "types" in data
            assert "supplier" in data["types"]
            assert "client" in data["types"]


class TestWarehousesCRUD:
    """Test Warehouses CRUD operations"""

    @pytest.mark.asyncio
    async def test_list_warehouses_format(self, app, admin_token):
        """Test listing warehouses returns standard format"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/warehouses",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            # Check standard response format
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data


class TestPricesEndpoint:
    """Test Prices (purchase history) endpoint"""

    @pytest.mark.asyncio
    async def test_prices_format(self, app, admin_token):
        """Test prices endpoint returns standard format"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/prices",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data

    @pytest.mark.asyncio
    async def test_prices_pagination(self, app, admin_token):
        """Test prices pagination"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/prices?page=1&page_size=5",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) <= 5
            assert data["page"] == 1


class TestTurnoverReport:
    """Test Turnover by Counterparty report"""

    @pytest.mark.asyncio
    async def test_turnover_format(self, app, admin_token):
        """Test turnover endpoint returns standard format with grand totals"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.get(
                "/api/reports/turnover-by-counterparty?type=purchases",
                headers={"Authorization": f"Bearer {admin_token}"}
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
    async def test_turnover_type_filter(self, app, admin_token):
        """Test turnover type filter (purchases vs sales)"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Purchases
            response = await client.get(
                "/api/reports/turnover-by-counterparty?type=purchases",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            assert response.json()["filters"]["type"] == "purchases"
            
            # Sales
            response = await client.get(
                "/api/reports/turnover-by-counterparty?type=sales",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            assert response.json()["filters"]["type"] == "sales"

    @pytest.mark.asyncio
    async def test_turnover_drilldown(self, app, admin_token):
        """Test turnover drilldown to invoices"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            # Get counterparty ID from turnover
            turnover_resp = await client.get(
                "/api/reports/turnover-by-counterparty?type=purchases",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            items = turnover_resp.json()["items"]
            
            if items:
                cp_id = items[0]["counterparty_id"]
                if cp_id:
                    # Drilldown
                    response = await client.get(
                        f"/api/reports/turnover-by-counterparty/{cp_id}/invoices",
                        headers={"Authorization": f"Bearer {admin_token}"}
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert "items" in data
                    assert "counterparty_id" in data
