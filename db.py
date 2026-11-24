"""
db.py -- all database access for the F1 Race Results Tracker.

Every SQL statement that uses user-supplied values is parameterized
(? placeholders); values are never concatenated into SQL strings.
The relational database (SQLite, f1.db) is the only store of project data.
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "f1.db"

# Standard F1 points scale for finishing positions 1-10 (a rule, not stored data).
POINTS_BY_POSITION = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}


def points_for(finish_position):
    """Points for a finishing position; a DNF (None) or P11+ scores 0."""
    if finish_position is None:
        return 0.0
    return float(POINTS_BY_POSITION.get(finish_position, 0))


# ---------------------------------------------------------------------
# Connection / setup
# ---------------------------------------------------------------------
def build_database(db_path=DB_FILE):
    """Create a fresh database from schema.sql and insert_data.sql."""
    Path(db_path).unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    try:
        for name in ("schema.sql", "insert_data.sql"):
            con.executescript((BASE_DIR / name).read_text(encoding="utf-8"))
    finally:
        con.close()


def connect(db_path=DB_FILE):
    """Open the database (building it first if the file is missing)."""
    if not Path(db_path).exists():
        build_database(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")  # must be set on every connection
    return con


# ---------------------------------------------------------------------
# Lookups used by menus and validation
# ---------------------------------------------------------------------
def list_seasons(con):
    return con.execute(
        "SELECT DISTINCT season_year FROM Driver_Entry ORDER BY season_year").fetchall()


def list_teams(con):
    return con.execute(
        "SELECT team_id, team_name, base_country FROM Team ORDER BY team_name").fetchall()


def list_races(con):
    """Races with how many results have been recorded (LEFT JOIN keeps empty races)."""
    return con.execute(
        """SELECT r.race_id, r.season_year, r.round_number, r.race_name, r.race_date,
                  COUNT(rr.result_id) AS results_recorded
           FROM Race r
           LEFT JOIN Race_Result rr ON rr.race_id = r.race_id
           GROUP BY r.race_id
           ORDER BY r.season_year, r.round_number""").fetchall()


def list_season_drivers(con, season_year):
    """One row per driver in a season (a mid-season team change shows both teams)."""
    return con.execute(
        """SELECT d.driver_id, d.driver_name,
                  GROUP_CONCAT(DISTINCT t.team_name) AS team_name,
                  MIN(de.car_number)                 AS car_number
           FROM Driver_Entry de
           JOIN Driver d ON d.driver_id = de.driver_id
           JOIN Team   t ON t.team_id   = de.team_id
           WHERE de.season_year = ?
           GROUP BY d.driver_id
           ORDER BY d.driver_name""", (season_year,)).fetchall()


# ---------------------------------------------------------------------
# 1. Search / browse
# ---------------------------------------------------------------------
def search_drivers(con, text):
    """Drivers whose name contains the text (empty text lists everyone)."""
    return con.execute(
        """SELECT driver_id, driver_name, nationality, birth_date
           FROM Driver
           WHERE driver_name LIKE ?
           ORDER BY driver_name""", (f"%{text}%",)).fetchall()


# ---------------------------------------------------------------------
# 2. Related data (joins)
# ---------------------------------------------------------------------
def get_driver(con, driver_id):
    return con.execute(
        "SELECT driver_id, driver_name, nationality, birth_date FROM Driver WHERE driver_id = ?",
        (driver_id,)).fetchone()


def driver_teams(con, driver_id):
    """Teams a driver has raced for (Driver_Entry is the junction table)."""
    return con.execute(
        """SELECT de.season_year, t.team_name, de.car_number
           FROM Driver_Entry de
           JOIN Team t ON t.team_id = de.team_id
           WHERE de.driver_id = ?
           ORDER BY de.season_year""", (driver_id,)).fetchall()


def driver_results(con, driver_id):
    """Every race result for one driver, joined across five tables."""
    return con.execute(
        """SELECT r.season_year, r.round_number, r.race_name, c.circuit_name,
                  t.team_name, rr.grid_position, rr.finish_position,
                  rr.points, rr.finish_status
           FROM Race_Result rr
           JOIN Race         r  ON r.race_id    = rr.race_id
           JOIN Circuit      c  ON c.circuit_id = r.circuit_id
           JOIN Driver_Entry de ON de.entry_id  = rr.entry_id
           JOIN Team         t  ON t.team_id    = de.team_id
           WHERE de.driver_id = ?
           ORDER BY r.season_year, r.round_number""", (driver_id,)).fetchall()


def get_race(con, race_id):
    return con.execute(
        """SELECT r.race_id, r.season_year, r.round_number, r.race_name, r.race_date,
                  c.circuit_name, c.country_location
           FROM Race r JOIN Circuit c ON c.circuit_id = r.circuit_id
           WHERE r.race_id = ?""", (race_id,)).fetchone()


def race_results(con, race_id):
    """Results for one race with driver, team and circuit data joined in."""
    return con.execute(
        """SELECT rr.result_id, rr.finish_position, d.driver_name, t.team_name,
                  de.car_number, rr.grid_position, rr.points, rr.finish_status
           FROM Race_Result rr
           JOIN Driver_Entry de ON de.entry_id  = rr.entry_id
           JOIN Driver       d  ON d.driver_id  = de.driver_id
           JOIN Team         t  ON t.team_id    = de.team_id
           WHERE rr.race_id = ?
           ORDER BY rr.finish_position IS NULL, rr.finish_position, rr.grid_position""",
        (race_id,)).fetchall()


# ---------------------------------------------------------------------
# 3. Add data
# ---------------------------------------------------------------------
def car_number_taken(con, season_year, car_number):
    return con.execute(
        "SELECT 1 FROM Driver_Entry WHERE season_year = ? AND car_number = ?",
        (season_year, car_number)).fetchone() is not None


def driver_exists(con, driver_name, birth_date):
    return con.execute(
        "SELECT 1 FROM Driver WHERE LOWER(driver_name) = LOWER(?) AND birth_date = ?",
        (driver_name, birth_date)).fetchone() is not None


def register_driver(con, driver_name, nationality, birth_date, team_id, season_year, car_number):
    """
    Add a new driver AND their season entry as ONE transaction.
    If the entry insert fails, the driver insert is rolled back too, so we
    never end up with a driver who has no entry.
    """
    with con:  # commits on success, rolls back if an exception is raised
        cur = con.execute(
            "INSERT INTO Driver (driver_name, nationality, birth_date) VALUES (?, ?, ?)",
            (driver_name, nationality, birth_date))
        driver_id = cur.lastrowid
        con.execute(
            """INSERT INTO Driver_Entry (driver_id, team_id, season_year, car_number)
               VALUES (?, ?, ?, ?)""", (driver_id, team_id, season_year, car_number))
    return driver_id


def entries_without_result(con, race_id):
    """
    Entries from the race's season that can still be given a result: the driver
    must not already have a result in this race (under any team entry).
    """
    return con.execute(
        """SELECT de.entry_id, d.driver_name, t.team_name, de.car_number
           FROM Driver_Entry de
           JOIN Driver d ON d.driver_id = de.driver_id
           JOIN Team   t ON t.team_id   = de.team_id
           WHERE de.season_year = (SELECT season_year FROM Race WHERE race_id = ?)
             AND de.driver_id NOT IN (
                 SELECT de2.driver_id
                 FROM Race_Result rr
                 JOIN Driver_Entry de2 ON de2.entry_id = rr.entry_id
                 WHERE rr.race_id = ?)
           ORDER BY d.driver_name""", (race_id, race_id)).fetchall()


def finish_position_taken(con, race_id, finish_position, exclude_result_id=None):
    """True if another result in this race already has that finishing position."""
    row = con.execute(
        """SELECT 1 FROM Race_Result
           WHERE race_id = ? AND finish_position = ? AND result_id <> ?""",
        (race_id, finish_position, exclude_result_id or -1)).fetchone()
    return row is not None


def insert_result(con, race_id, entry_id, grid_position, finish_position, status):
    """Record a result; points are calculated from the finishing position."""
    with con:
        cur = con.execute(
            """INSERT INTO Race_Result
                   (race_id, entry_id, grid_position, finish_position, points, finish_status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (race_id, entry_id, grid_position, finish_position,
             points_for(finish_position), status))
    return cur.lastrowid


# ---------------------------------------------------------------------
# 4. Update / delete data
# ---------------------------------------------------------------------
def get_result(con, result_id):
    return con.execute(
        """SELECT rr.result_id, rr.race_id, d.driver_name, rr.finish_position,
                  rr.points, rr.finish_status
           FROM Race_Result rr
           JOIN Driver_Entry de ON de.entry_id = rr.entry_id
           JOIN Driver d        ON d.driver_id = de.driver_id
           WHERE rr.result_id = ?""", (result_id,)).fetchone()


def update_result(con, result_id, finish_position, status):
    """Correct a result's outcome; points are recalculated to match."""
    with con:
        cur = con.execute(
            """UPDATE Race_Result
               SET finish_position = ?, points = ?, finish_status = ?
               WHERE result_id = ?""",
            (finish_position, points_for(finish_position), status, result_id))
    return cur.rowcount


def delete_result(con, result_id):
    with con:
        cur = con.execute("DELETE FROM Race_Result WHERE result_id = ?", (result_id,))
    return cur.rowcount


# ---------------------------------------------------------------------
# 5. Reports
# ---------------------------------------------------------------------
def driver_standings(con, season_year):
    """Uses the v_driver_season_standings view from the schema."""
    return con.execute(
        """SELECT driver_name, team_name, races_entered, total_points, wins, podiums
           FROM v_driver_season_standings
           WHERE season_year = ?
           ORDER BY total_points DESC, wins DESC, driver_name""", (season_year,)).fetchall()


def team_standings(con, season_year):
    """Constructor standings: points summed per team (JOIN + GROUP BY)."""
    return con.execute(
        """SELECT t.team_name,
                  COUNT(DISTINCT de.driver_id)  AS drivers,
                  COALESCE(SUM(rr.points), 0)   AS total_points,
                  COALESCE(SUM(CASE WHEN rr.finish_position = 1 THEN 1 ELSE 0 END), 0) AS wins
           FROM Driver_Entry de
           JOIN Team t ON t.team_id = de.team_id
           LEFT JOIN Race_Result rr ON rr.entry_id = de.entry_id
           WHERE de.season_year = ?
           GROUP BY t.team_id
           ORDER BY total_points DESC, t.team_name""", (season_year,)).fetchall()


# ---------------------------------------------------------------------
# 6. Additional operation: head-to-head comparison
# ---------------------------------------------------------------------
# Races in a season where both drivers have a result, and who finished ahead
# (a driver who finished beats one who did not). The SQL text is a constant;
# only the ? values come from the user.
_HEAD_TO_HEAD = """
    SELECT r.round_number, r.race_name,
           ra.finish_position AS first_driver_pos,
           rb.finish_position AS second_driver_pos,
           CASE
             WHEN ra.finish_position IS NOT NULL
                  AND (rb.finish_position IS NULL OR ra.finish_position < rb.finish_position)
                  THEN da.driver_name
             WHEN rb.finish_position IS NOT NULL
                  AND (ra.finish_position IS NULL OR rb.finish_position < ra.finish_position)
                  THEN db.driver_name
             ELSE 'Neither (both DNF)'
           END AS finished_ahead
    FROM Race r
    JOIN Race_Result  ra  ON ra.race_id   = r.race_id
    JOIN Driver_Entry dea ON dea.entry_id = ra.entry_id AND dea.driver_id = ?
    JOIN Race_Result  rb  ON rb.race_id   = r.race_id
    JOIN Driver_Entry deb ON deb.entry_id = rb.entry_id AND deb.driver_id = ?
    JOIN Driver da ON da.driver_id = dea.driver_id
    JOIN Driver db ON db.driver_id = deb.driver_id
    WHERE r.season_year = ?
"""


def head_to_head(con, driver_a, driver_b, season_year):
    params = (driver_a, driver_b, season_year)
    per_race = con.execute(_HEAD_TO_HEAD + " ORDER BY r.round_number", params).fetchall()
    summary = con.execute(
        "SELECT finished_ahead, COUNT(*) AS races FROM (" + _HEAD_TO_HEAD + ") "
        "GROUP BY finished_ahead ORDER BY races DESC", params).fetchall()
    return per_race, summary


# ---------------------------------------------------------------------
# Helpers shared by the web application
# ---------------------------------------------------------------------
def summary_counts(con):
    """Row counts for the home page."""
    return con.execute(
        """SELECT (SELECT COUNT(*) FROM Driver)       AS drivers,
                  (SELECT COUNT(*) FROM Team)         AS teams,
                  (SELECT COUNT(*) FROM Race)         AS races,
                  (SELECT COUNT(*) FROM Race_Result)  AS results""").fetchone()


def describe_integrity_error(err):
    """Turn a SQLite integrity error into a short message for the user."""
    text = str(err)
    if "UNIQUE" in text:
        return "That record already exists (a value that must be unique is duplicated)."
    if "FOREIGN KEY" in text:
        return ("That change conflicts with related records (something it refers to "
                "is missing, or other records depend on it).")
    if "CHECK" in text:
        return "The values entered break one of the database's data rules."
    if "NOT NULL" in text:
        return "A required value is missing."
    return "The database rejected that change."


# ---------------------------------------------------------------------
# Race-by-race standings (for the progression chart)
# ---------------------------------------------------------------------
def standings_progression(con, season_year):
    """
    Each driver's championship position after every race that has results.
    Running points and wins are summed per DRIVER up to each round (across all
    of the driver's team entries), then ROW_NUMBER() ranks the drivers within
    the round. Ties in points are broken by wins, then by name. A driver is only
    ranked from their first race onward.
    """
    return con.execute(
        """WITH played AS (
               SELECT race_id, season_year, round_number, race_name
               FROM Race
               WHERE season_year = ?
                 AND race_id IN (SELECT race_id FROM Race_Result)
           ),
           season_drivers AS (
               -- main team = the team entry with the most results (used for chart colours)
               SELECT DISTINCT d.driver_id, d.driver_name,
                      (SELECT t.team_name
                         FROM Driver_Entry de2
                         JOIN Team t ON t.team_id = de2.team_id
                         LEFT JOIN Race_Result rr2 ON rr2.entry_id = de2.entry_id
                        WHERE de2.driver_id = d.driver_id AND de2.season_year = ?
                        GROUP BY de2.entry_id
                        ORDER BY COUNT(rr2.result_id) DESC, de2.entry_id DESC
                        LIMIT 1) AS team_name
               FROM Driver_Entry de
               JOIN Driver d ON d.driver_id = de.driver_id
               WHERE de.season_year = ?
           ),
           running AS (
               SELECT p.round_number, p.race_name, sd.driver_name, sd.team_name,
                      (SELECT COALESCE(SUM(rr.points), 0)
                         FROM Race_Result rr
                         JOIN Race r          ON r.race_id   = rr.race_id
                         JOIN Driver_Entry de ON de.entry_id = rr.entry_id
                        WHERE de.driver_id = sd.driver_id
                          AND r.season_year = p.season_year
                          AND r.round_number <= p.round_number) AS points_after,
                      (SELECT COUNT(*)
                         FROM Race_Result rr
                         JOIN Race r          ON r.race_id   = rr.race_id
                         JOIN Driver_Entry de ON de.entry_id = rr.entry_id
                        WHERE de.driver_id = sd.driver_id
                          AND r.season_year = p.season_year
                          AND r.round_number <= p.round_number
                          AND rr.finish_position = 1) AS wins_after
               FROM played p
               CROSS JOIN season_drivers sd
               -- a driver is ranked from their first race onward
               WHERE EXISTS (SELECT 1
                               FROM Race_Result rr
                               JOIN Race r          ON r.race_id   = rr.race_id
                               JOIN Driver_Entry de ON de.entry_id = rr.entry_id
                              WHERE de.driver_id = sd.driver_id
                                AND r.season_year = p.season_year
                                AND r.round_number <= p.round_number)
           )
           SELECT round_number, race_name, driver_name, team_name, points_after,
                  ROW_NUMBER() OVER (PARTITION BY round_number
                                     ORDER BY points_after DESC, wins_after DESC, driver_name
                                    ) AS standing
           FROM running
           ORDER BY round_number, standing""", (season_year, season_year, season_year)).fetchall()


def team_progression(con, season_year):
    """
    Each team's constructors' championship position after every race that has
    results. Points and wins are summed per TEAM across all of its entries up to
    each round (so a driver's points count for the team they drove for in that
    race). Ties are broken by wins, then by name. A team is ranked from its
    first result onward.
    """
    return con.execute(
        """WITH played AS (
               SELECT race_id, season_year, round_number, race_name
               FROM Race
               WHERE season_year = ?
                 AND race_id IN (SELECT race_id FROM Race_Result)
           ),
           season_teams AS (
               SELECT DISTINCT t.team_id, t.team_name
               FROM Driver_Entry de
               JOIN Team t ON t.team_id = de.team_id
               WHERE de.season_year = ?
           ),
           running AS (
               SELECT p.round_number, p.race_name, st.team_name,
                      (SELECT COALESCE(SUM(rr.points), 0)
                         FROM Race_Result rr
                         JOIN Race r          ON r.race_id   = rr.race_id
                         JOIN Driver_Entry de ON de.entry_id = rr.entry_id
                        WHERE de.team_id = st.team_id
                          AND r.season_year = p.season_year
                          AND r.round_number <= p.round_number) AS points_after,
                      (SELECT COUNT(*)
                         FROM Race_Result rr
                         JOIN Race r          ON r.race_id   = rr.race_id
                         JOIN Driver_Entry de ON de.entry_id = rr.entry_id
                        WHERE de.team_id = st.team_id
                          AND r.season_year = p.season_year
                          AND r.round_number <= p.round_number
                          AND rr.finish_position = 1) AS wins_after
               FROM played p
               CROSS JOIN season_teams st
               WHERE EXISTS (SELECT 1
                               FROM Race_Result rr
                               JOIN Race r          ON r.race_id   = rr.race_id
                               JOIN Driver_Entry de ON de.entry_id = rr.entry_id
                              WHERE de.team_id = st.team_id
                                AND r.season_year = p.season_year
                                AND r.round_number <= p.round_number)
           )
           SELECT round_number, race_name, team_name, points_after,
                  ROW_NUMBER() OVER (PARTITION BY round_number
                                     ORDER BY points_after DESC, wins_after DESC, team_name
                                    ) AS standing
           FROM running
           ORDER BY round_number, standing""", (season_year, season_year)).fetchall()

# ---------------------------------------------------------------------
# Transaction demonstration (web version of transaction.sql)
# ---------------------------------------------------------------------
# Scenario: a stand-in driver is signed by Williams and gets a result in the
# 2024 Australian GP, where Williams ran only one car (so grid slot 20 was empty
# and finishing position 18 was not taken). Driver, season entry and result must
# all succeed together.
DEMO_DRIVER = {"driver_name": "Jamie Okafor", "nationality": "British",
               "birth_date": "2003-03-14"}
DEMO_SEASON = 2024
DEMO_TEAM_NAME = "Williams"
DEMO_RACE_NAME = "Australian Grand Prix"
DEMO_CAR = 99
DEMO_GRID = 20                   # the grid slot nobody used in this race
DEMO_FINISH = 18                 # a finishing position nobody else holds in this race
MISSING_RACE_ID = 999999         # used by the "failing step" demo: no such race exists


def _ordinal(n):
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 18 -> '18th', 21 -> '21st'."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def demo_context(con):
    """The Williams team row and the demo race row, or (None, None) if absent."""
    team = con.execute("SELECT team_id, team_name FROM Team WHERE team_name = ?",
                       (DEMO_TEAM_NAME,)).fetchone()
    race = con.execute("SELECT race_id, race_name FROM Race WHERE season_year = ? AND race_name = ?",
                       (DEMO_SEASON, DEMO_RACE_NAME)).fetchone()
    return team, race


def demo_data_present(con):
    """True if the demo driver is already in the database (e.g. after a COMMIT run)."""
    return driver_exists(con, DEMO_DRIVER["driver_name"], DEMO_DRIVER["birth_date"])


def remove_demo_data(con):
    """Delete the demo driver, entry and result (children first). Returns drivers removed."""
    name, born = DEMO_DRIVER["driver_name"], DEMO_DRIVER["birth_date"]
    with con:
        con.execute(
            """DELETE FROM Race_Result WHERE entry_id IN (
                   SELECT de.entry_id FROM Driver_Entry de
                   JOIN Driver d ON d.driver_id = de.driver_id
                   WHERE d.driver_name = ? AND d.birth_date = ?)""", (name, born))
        con.execute(
            """DELETE FROM Driver_Entry WHERE driver_id IN (
                   SELECT driver_id FROM Driver WHERE driver_name = ? AND birth_date = ?)""",
            (name, born))
        cur = con.execute("DELETE FROM Driver WHERE driver_name = ? AND birth_date = ?",
                          (name, born))
    return cur.rowcount


def _demo_snapshot(con, race_id):
    """Williams' standings plus how many demo rows exist in each table right now."""
    standings = con.execute(
        """SELECT driver_name, races_entered, total_points
           FROM v_driver_season_standings
           WHERE season_year = ? AND team_name LIKE ?
           ORDER BY total_points DESC, driver_name""",
        (DEMO_SEASON, f"%{DEMO_TEAM_NAME}%")).fetchall()
    name, born = DEMO_DRIVER["driver_name"], DEMO_DRIVER["birth_date"]
    counts = con.execute(
        """SELECT
             (SELECT COUNT(*) FROM Driver WHERE driver_name = ? AND birth_date = ?) AS driver_rows,
             (SELECT COUNT(*) FROM Driver_Entry de JOIN Driver d ON d.driver_id = de.driver_id
               WHERE d.driver_name = ? AND d.birth_date = ? AND de.season_year = ?) AS entry_rows,
             (SELECT COUNT(*) FROM Race_Result rr
               JOIN Driver_Entry de ON de.entry_id = rr.entry_id
               JOIN Driver d        ON d.driver_id = de.driver_id
               WHERE d.driver_name = ? AND d.birth_date = ? AND rr.race_id = ?) AS result_rows""",
        (name, born, name, born, DEMO_SEASON, name, born, race_id)).fetchone()
    return {"standings": [dict(r) for r in standings], "counts": [dict(counts)]}


def run_transaction_demo(mode, db_path=DB_FILE):
    """
    Run the three-step scenario from transaction.sql as ONE explicit transaction.

    mode "rollback": all steps succeed, then ROLLBACK undoes them (data unchanged).
    mode "commit":   all steps succeed, then COMMIT keeps them.
    mode "fail":     step 3 is given a race that does not exist, so it violates a
                     foreign key; steps 1 and 2 are then undone by ROLLBACK.

    Uses its own connection with isolation_level=None so Python does not start
    transactions implicitly: the BEGIN / COMMIT / ROLLBACK below are the real ones.
    Returns a dict describing every step and the data before, inside and after.
    """
    con = sqlite3.connect(db_path, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    steps = []

    def record(title, shown_sql, status, note):
        steps.append({"title": title, "sql": shown_sql, "status": status, "note": note})

    def attempt(title, shown_sql, note, sql, params):
        """Run one statement; record it as ok, or as failed (and re-raise)."""
        try:
            cur = con.execute(sql, params)
        except sqlite3.IntegrityError as err:
            record(title, shown_sql, "failed",
                   f"{describe_integrity_error(err)} (SQLite said: {err})")
            raise
        record(title, shown_sql, "ok", note)
        return cur.lastrowid

    try:
        team, race = demo_context(con)
        before = _demo_snapshot(con, race["race_id"])
        d, points = DEMO_DRIVER, points_for(DEMO_FINISH)

        con.execute("BEGIN TRANSACTION")
        record("BEGIN TRANSACTION", "BEGIN TRANSACTION;", "ok",
               "A transaction is now open. Nothing below is permanent yet.")

        failed = False
        try:
            driver_id = attempt(
                "Step 1: add the new driver",
                f"INSERT INTO Driver (driver_name, nationality, birth_date)\n"
                f"VALUES ('{d['driver_name']}', '{d['nationality']}', '{d['birth_date']}');",
                "The driver row was inserted.",
                "INSERT INTO Driver (driver_name, nationality, birth_date) VALUES (?, ?, ?)",
                (d["driver_name"], d["nationality"], d["birth_date"]))

            entry_id = attempt(
                f"Step 2: register the driver with {DEMO_TEAM_NAME} for {DEMO_SEASON}",
                f"INSERT INTO Driver_Entry (driver_id, team_id, season_year, car_number)\n"
                f"VALUES ({driver_id}, {team['team_id']}, {DEMO_SEASON}, {DEMO_CAR});",
                "The season entry was inserted.",
                "INSERT INTO Driver_Entry (driver_id, team_id, season_year, car_number) "
                "VALUES (?, ?, ?, ?)",
                (driver_id, team["team_id"], DEMO_SEASON, DEMO_CAR))

            result_race = MISSING_RACE_ID if mode == "fail" else race["race_id"]
            attempt(
                f"Step 3: record the result in the {DEMO_RACE_NAME}",
                f"INSERT INTO Race_Result (race_id, entry_id, grid_position,\n"
                f"                         finish_position, points, finish_status)\n"
                f"VALUES ({result_race}, {entry_id}, {DEMO_GRID}, {DEMO_FINISH}, {points}, 'Finished');",
                f"The result was inserted (started {_ordinal(DEMO_GRID)}, finished {_ordinal(DEMO_FINISH)}, no points).",
                "INSERT INTO Race_Result (race_id, entry_id, grid_position, finish_position, "
                "points, finish_status) VALUES (?, ?, ?, ?, ?, 'Finished')",
                (result_race, entry_id, DEMO_GRID, DEMO_FINISH, points))
        except sqlite3.IntegrityError:
            failed = True

        # What this connection can see right now, before the transaction ends.
        inside = _demo_snapshot(con, race["race_id"])

        if failed or mode != "commit":
            con.execute("ROLLBACK")
            ended = "ROLLBACK"
            note = ("A step failed, so everything done since BEGIN is undone together."
                    if failed else "Every change made since BEGIN is undone together.")
        else:
            con.execute("COMMIT")
            ended = "COMMIT"
            note = "Every change made since BEGIN is now permanent."
        record(ended, f"{ended};", "ok", note)

        after = _demo_snapshot(con, race["race_id"])
    finally:
        if con.in_transaction:      # safety net for unexpected errors
            con.execute("ROLLBACK")
        con.close()

    return {"mode": mode, "steps": steps, "before": before, "inside": inside,
            "after": after, "ended": ended, "failed": failed}
