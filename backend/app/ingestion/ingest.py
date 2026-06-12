"""Idempotent loader: data/ -> Postgres (PLANNING.md Phase 2).

Walks data/company_*/, parses the API-style JSON exports and financial CSVs,
and upserts everything with the denormalized company_id columns the RLS
policies key on. Runs as the admin role: ingestion must write across tenants,
which the RLS-bound app role (correctly) cannot.

Source -> schema mapping (PLANNING.md §1.1):
  company.json                          -> companies
  users.csv                             -> users
  api/GET_api_Plant.json                -> plants (Parameters[] flattened)
  api/plant_*/..._Element.json          -> elements
  api/plant_*/..._Datasource.json       -> datasources
  api/plant_*/GET_api_DataList_v2__ds_<id>__<agg>.json -> datapoints
                                           (and aggregation_type on datasources)
  financial/hourly_market_prices.csv    -> market_prices
  financial/monthly_costs.csv           -> monthly_costs
"""

import asyncio
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import asyncpg

from app.config import DATABASE_ADMIN_URL, DATA_DIR

DATALIST_RE = re.compile(r"GET_api_DataList_v2__ds_(\d+)__(sum|average)\.json$")


def _param(plant: dict, key: str) -> str | None:
    for p in plant.get("Parameters", []):
        if p["Key"] == key:
            return p["Value"]
    return None


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def ingest_company(conn: asyncpg.Connection, company_dir: Path) -> dict:
    counts = {"plants": 0, "elements": 0, "datasources": 0, "datapoints": 0,
              "market_prices": 0, "monthly_costs": 0, "users": 0}

    company = json.loads((company_dir / "company.json").read_text(encoding="utf-8"))
    company_id = company["company_id"]
    await conn.execute(
        """INSERT INTO companies (company_id, display_name) VALUES ($1, $2)
           ON CONFLICT (company_id) DO UPDATE SET display_name = EXCLUDED.display_name""",
        company_id, company["display_name"],
    )

    with (company_dir / "users.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            await conn.execute(
                """INSERT INTO users (user_id, company_id, email, role, access_scope)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (user_id) DO UPDATE SET email = EXCLUDED.email,
                       role = EXCLUDED.role, access_scope = EXCLUDED.access_scope""",
                row["user_id"], company_id, row["email"], row["role"], row["access_scope"],
            )
            counts["users"] += 1

    # Plants: flatten Parameters[] into typed columns (Decision 1).
    plants = json.loads((company_dir / "api" / "GET_api_Plant.json").read_text(encoding="utf-8"))
    for plant in plants:
        nominal = _param(plant, "Nominal Power")
        commissioned = _param(plant, "Commissioning Date")
        await conn.execute(
            """INSERT INTO plants (id, company_id, name, unique_id, nominal_power_kw,
                                   region, commissioning_date)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                   nominal_power_kw = EXCLUDED.nominal_power_kw,
                   region = EXCLUDED.region,
                   commissioning_date = EXCLUDED.commissioning_date""",
            plant["Id"], company_id, plant["Name"], plant["UniqueID"],
            float(nominal) if nominal else None,
            _param(plant, "Region"),
            date.fromisoformat(commissioned) if commissioned else None,
        )
        counts["plants"] += 1

        plant_dir = company_dir / "api" / f"plant_{plant['Id']}"

        elements = json.loads(
            (plant_dir / "GET_api_Plant_{plantId}_Element.json").read_text(encoding="utf-8")
        )
        for el in elements:
            await conn.execute(
                """INSERT INTO elements (id, plant_id, company_id, unique_id, name,
                                         type, type_string)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                       type = EXCLUDED.type, type_string = EXCLUDED.type_string""",
                el["Identifier"], plant["Id"], company_id, el["UniqueID"],
                el["Name"], el["Type"], el["TypeString"],
            )
            counts["elements"] += 1

        # aggregation_type comes from the DataList filename suffix, the only
        # place the source records how each series should be aggregated.
        agg_by_ds: dict[int, str] = {}
        for dl_path in plant_dir.glob("GET_api_DataList_v2__ds_*.json"):
            m = DATALIST_RE.search(dl_path.name)
            if m:
                agg_by_ds[int(m.group(1))] = m.group(2)

        datasources = json.loads(
            (plant_dir / "GET_api_Plant_{plantId}_Datasource.json").read_text(encoding="utf-8")
        )
        for ds in datasources:
            ds_id = ds["DataSourceId"]
            if ds_id not in agg_by_ds:
                raise ValueError(
                    f"datasource {ds_id} has no DataList file to derive aggregation_type from"
                )
            await conn.execute(
                """INSERT INTO datasources (id, element_id, plant_id, company_id,
                                            name, units, aggregation_type)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                       units = EXCLUDED.units,
                       aggregation_type = EXCLUDED.aggregation_type""",
                ds_id, ds["ElementId"], plant["Id"], company_id,
                ds["DataSourceName"], ds["Units"], agg_by_ds[ds_id],
            )
            counts["datasources"] += 1

        for dl_path in sorted(plant_dir.glob("GET_api_DataList_v2__ds_*.json")):
            points = json.loads(dl_path.read_text(encoding="utf-8"))
            rows = [
                (p["DataSourceId"], company_id, _parse_ts(p["Date"]), float(p["Value"]))
                for p in points
            ]
            await conn.executemany(
                """INSERT INTO datapoints (datasource_id, company_id, ts, value)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (datasource_id, ts) DO UPDATE SET value = EXCLUDED.value""",
                rows,
            )
            counts["datapoints"] += len(rows)

    with (company_dir / "financial" / "hourly_market_prices.csv").open(encoding="utf-8") as f:
        rows = [
            (r["company_id"], r["zone"], _parse_ts(r["timestamp"]), float(r["eur_per_mwh"]))
            for r in csv.DictReader(f)
        ]
        await conn.executemany(
            """INSERT INTO market_prices (company_id, zone, ts, eur_per_mwh)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (company_id, zone, ts) DO UPDATE
                   SET eur_per_mwh = EXCLUDED.eur_per_mwh""",
            rows,
        )
        counts["market_prices"] = len(rows)

    with (company_dir / "financial" / "monthly_costs.csv").open(encoding="utf-8") as f:
        rows = [
            (r["company_id"], int(r["plant_id"]), int(r["year"]), int(r["month"]),
             r["category"], float(r["amount_eur"]), r["notes"] or None)
            for r in csv.DictReader(f)
        ]
        await conn.executemany(
            """INSERT INTO monthly_costs (company_id, plant_id, year, month, category,
                                          amount_eur, notes)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (company_id, plant_id, year, month, category) DO UPDATE
                   SET amount_eur = EXCLUDED.amount_eur, notes = EXCLUDED.notes""",
            rows,
        )
        counts["monthly_costs"] = len(rows)

    return counts


async def ingest() -> None:
    company_dirs = sorted(d for d in DATA_DIR.glob("company_*") if d.is_dir())
    if not company_dirs:
        raise FileNotFoundError(f"no company_* directories under {DATA_DIR}")

    conn = await asyncpg.connect(DATABASE_ADMIN_URL)
    try:
        for company_dir in company_dirs:
            async with conn.transaction():
                counts = await ingest_company(conn, company_dir)
            print(f"{company_dir.name}: {counts}")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(ingest())
    except Exception as exc:  # noqa: BLE001 — entrypoint surface
        print(f"ingestion failed: {exc}", file=sys.stderr)
        sys.exit(1)
