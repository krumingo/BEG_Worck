"""
Universal pagination helper for MongoDB queries.
"""
from fastapi import Query


async def paginate_query(
    collection,
    query: dict,
    page: int = 1,
    page_size: int = 50,
    sort_field: str = "created_at",
    sort_order: int = -1,
    projection: dict = None,
) -> dict:
    if projection is None:
        projection = {"_id": 0}

    total = await collection.count_documents(query)
    skip = (page - 1) * page_size

    cursor = collection.find(query, projection)
    cursor = cursor.sort(sort_field, sort_order)
    cursor = cursor.skip(skip).limit(page_size)
    items = await cursor.to_list(length=page_size)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "has_next": page * page_size < total,
        "has_prev": page > 1,
    }


def pagination_params(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
):
    return {"page": page, "page_size": page_size}
