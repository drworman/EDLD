"""
components/catalog.py — Persistent career body catalog.

Records scanned bodies to a lightweight SQLite database, enabling career-level
statistics (total ELWs found, total first discoveries, etc.) that persist
across sessions.

Database: ~/.local/share/EDLD/catalog/bodies.db (Linux)

Schema (single table):
  bodies (
      system_address  INTEGER NOT NULL,
      body_id         INTEGER NOT NULL,
      system_name     TEXT,
      body_name       TEXT,
      body_class      TEXT,     -- planet class or star type
      is_planet       INTEGER,  -- 1=planet, 0=star
      terraformable   INTEGER,  -- 1=yes
      first_discovery INTEGER,  -- 1=was first discovered
      first_mapped    INTEGER,  -- 1=was first mapped
      scan_date       TEXT,     -- ISO date (UTC) of first scan in this catalog
      PRIMARY KEY (system_address, body_id)
  )

On duplicate (system_address, body_id), the row is preserved as-is (INSERT OR IGNORE)
since first-discovered/first-mapped flags are meaningful only on the first scan.

Notable class shortcuts:
  ELW              → body_class = 'Earthlike body'
  Water World      → body_class = 'Water world'
  Ammonia World    → body_class = 'Ammonia world'
  Terraformable    → terraformable = 1
  Neutron Star     → body_class contains 'neutron'
  Black Hole       → body_class contains 'black hole'
"""

import sqlite3
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import cmdr_data_dir


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS bodies (
    system_address  INTEGER NOT NULL,
    body_id         INTEGER NOT NULL,
    system_name     TEXT,
    body_name       TEXT,
    body_class      TEXT,
    is_planet       INTEGER NOT NULL DEFAULT 1,
    terraformable   INTEGER NOT NULL DEFAULT 0,
    first_discovery INTEGER NOT NULL DEFAULT 0,
    first_mapped    INTEGER NOT NULL DEFAULT 0,
    scan_date       TEXT,
    PRIMARY KEY (system_address, body_id)
);
CREATE INDEX IF NOT EXISTS idx_body_class ON bodies(body_class);
CREATE INDEX IF NOT EXISTS idx_first_discovery ON bodies(first_discovery);
"""

_INSERT_SQL = """
INSERT OR IGNORE INTO bodies
    (system_address, body_id, system_name, body_name, body_class,
     is_planet, terraformable, first_discovery, first_mapped, scan_date)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_FIRST_MAPPED_SQL = """
UPDATE bodies SET first_mapped = 1
WHERE system_address = ? AND body_id = ? AND first_mapped = 0
"""


def _terraformable(terraform_state: str) -> bool:
    s = (terraform_state or "").lower()
    return bool(s) and s not in ("not terraformable", "")


class CatalogPlugin(BasePlugin):
    PLUGIN_NAME        = "catalog"
    PLUGIN_DISPLAY     = "Body Catalog"
    PLUGIN_DESCRIPTION = "Persistent SQLite catalog of all scanned bodies for career statistics."
    PLUGIN_VERSION     = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "Scan",
        "SAAScanComplete",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        self._db: sqlite3.Connection | None = None
        self._db_path = cmdr_data_dir() / "catalog" / "bodies.db"
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._db.executescript(_CREATE_SQL)
            self._db.commit()
        except Exception as exc:
            print(f"[catalog] DB init failed: {exc}")
            self._db = None

    def on_event(self, event: dict, state) -> None:
        if self._db is None:
            return
        ev = event.get("event")

        match ev:

            case "Scan":
                scan_type = event.get("ScanType", "")
                # Skip surface scanner pings that aren't body scans
                if scan_type not in ("AutoScan", "Detailed", ""):
                    return

                planet_class    = event.get("PlanetClass", "")
                star_type       = event.get("StarType", "")
                system_address  = event.get("SystemAddress")
                body_id         = event.get("BodyID")
                system_name     = event.get("StarSystem", "")
                body_name       = event.get("BodyName", "")
                was_discovered  = event.get("WasDiscovered", True)
                terraform_state = event.get("TerraformState", "")

                if system_address is None or body_id is None:
                    return
                if not planet_class and not star_type:
                    return   # non-body scan (belts, rings, etc.)

                is_planet   = 1 if planet_class else 0
                body_class  = planet_class if planet_class else star_type
                terra       = 1 if (is_planet and _terraformable(terraform_state)) else 0
                first_disc  = 0 if was_discovered else 1
                scan_date   = (event.get("timestamp") or "")[:10]

                try:
                    self._db.execute(_INSERT_SQL, (
                        system_address, body_id, system_name, body_name,
                        body_class, is_planet, terra, first_disc, 0, scan_date,
                    ))
                    self._db.commit()
                except Exception as exc:
                    print(f"[catalog] Insert failed: {exc}")

            case "SAAScanComplete":
                system_address = event.get("SystemAddress")
                body_id        = event.get("BodyID")
                was_mapped     = event.get("WasMapped", True)
                if system_address is None or body_id is None:
                    return
                if not was_mapped:
                    try:
                        self._db.execute(_FIRST_MAPPED_SQL, (system_address, body_id))
                        self._db.commit()
                    except Exception as exc:
                        print(f"[catalog] Update failed: {exc}")

    # ── Query helpers (callable from the dashboard or other plugins) ───────────

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Execute a read-only query and return rows. Returns [] on error."""
        if self._db is None:
            return []
        try:
            cur = self._db.execute(sql, params)
            return cur.fetchall()
        except Exception as exc:
            print(f"[catalog] Query failed: {exc}")
            return []

    def career_totals(self) -> dict:
        """Return a summary dict of career scanning statistics."""
        rows = self.query("""
            SELECT
                COUNT(*)                                                    AS total_bodies,
                SUM(CASE WHEN first_discovery = 1 THEN 1 ELSE 0 END)      AS first_discoveries,
                SUM(CASE WHEN first_mapped    = 1 THEN 1 ELSE 0 END)      AS first_mapped,
                SUM(CASE WHEN body_class = 'Earthlike body'               THEN 1 ELSE 0 END) AS elw,
                SUM(CASE WHEN body_class = 'Water world'                  THEN 1 ELSE 0 END) AS water_world,
                SUM(CASE WHEN body_class = 'Ammonia world'                THEN 1 ELSE 0 END) AS ammonia_world,
                SUM(CASE WHEN terraformable = 1                           THEN 1 ELSE 0 END) AS terraformable,
                SUM(CASE WHEN LOWER(body_class) LIKE '%neutron%'          THEN 1 ELSE 0 END) AS neutron_star,
                SUM(CASE WHEN LOWER(body_class) LIKE '%black hole%'       THEN 1 ELSE 0 END) AS black_hole,
                SUM(CASE WHEN is_planet = 0                               THEN 1 ELSE 0 END) AS stars
            FROM bodies
        """)
        if not rows:
            return {}
        r = rows[0]
        keys = [
            "total_bodies", "first_discoveries", "first_mapped",
            "elw", "water_world", "ammonia_world", "terraformable",
            "neutron_star", "black_hole", "stars",
        ]
        return {k: (v or 0) for k, v in zip(keys, r)}
