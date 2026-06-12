from fastapi import APIRouter

from app.db.pool import fetch_all_scoped
from app.middleware.tenant import CurrentUser
from app.models import Plant, User

router = APIRouter()


@router.get("/plants", response_model=list[Plant])
async def list_plants(user: User = CurrentUser):
    rows = await fetch_all_scoped(
        user,
        """SELECT p.id, p.name, p.nominal_power_kw::float8 AS nominal_power_kw,
                  p.region, p.commissioning_date::text AS commissioning_date,
                  count(d.id)::int AS datasource_count
           FROM plants p LEFT JOIN datasources d ON d.plant_id = p.id
           GROUP BY p.id ORDER BY p.id""",
    )
    return [Plant(**dict(r)) for r in rows]
