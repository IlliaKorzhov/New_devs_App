from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List

from sqlalchemy import text

from app.core.database_pool import db_pool


async def _get_db_pool():
    """Return the shared database pool, initializing it on first use."""
    if not db_pool.session_factory:
        await db_pool.initialize()
    return db_pool


async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Decimal:
    """
    Calculates revenue for a specific month.

    Month boundaries are evaluated in the property's local timezone, not UTC:
    a check-in at 2024-02-29 23:30 UTC for a Europe/Paris property is already
    March 1st locally, so it belongs to March.
    """

    start_local = datetime(year, month, 1)
    if month < 12:
        end_local = datetime(year, month + 1, 1)
    else:
        end_local = datetime(year + 1, 1, 1)

    query = text("""
        SELECT COALESCE(SUM(r.total_amount), 0) AS total
        FROM reservations r
        JOIN properties p
          ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.property_id = :property_id
          AND r.tenant_id = :tenant_id
          AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_local
          AND (r.check_in_date AT TIME ZONE p.timezone) < :end_local
    """)

    pool = await _get_db_pool()
    async with pool.get_session() as session:
        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "start_local": start_local,
            "end_local": end_local,
        })
        total = result.scalar_one()
        return Decimal(str(total))


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    pool = await _get_db_pool()

    if not pool.session_factory:
        raise Exception("Database pool not available")

    async with pool.get_session() as session:
        query = text("""
            SELECT
                property_id,
                SUM(total_amount) as total_revenue,
                COUNT(*) as reservation_count
            FROM reservations
            WHERE property_id = :property_id AND tenant_id = :tenant_id
            GROUP BY property_id
        """)

        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id
        })
        row = result.fetchone()

        if row:
            total_revenue = Decimal(str(row.total_revenue))
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": str(total_revenue),
                "currency": "USD",
                "count": row.reservation_count
            }
        else:
            # No reservations found for this property
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": "0.00",
                "currency": "USD",
                "count": 0
            }
