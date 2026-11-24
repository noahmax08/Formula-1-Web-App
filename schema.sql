-- =====================================================================
-- F1 Race Results Tracker -- schema.sql
-- DBMS: SQLite 3
-- Run FIRST, then insert_data.sql.
-- =====================================================================

-- SQLite does not enforce foreign keys unless this is turned on, and the
-- setting is per connection (it must also be set in insert_data.sql).
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- Cleanup (children first, so the script can be re-run on any database)
-- ---------------------------------------------------------------------
DROP VIEW  IF EXISTS v_driver_season_standings;
DROP VIEW  IF EXISTS v_race_results_detail;
DROP TABLE IF EXISTS Race_Result;
DROP TABLE IF EXISTS Driver_Entry;
DROP TABLE IF EXISTS Race;
DROP TABLE IF EXISTS Circuit;
DROP TABLE IF EXISTS Driver;
DROP TABLE IF EXISTS Team;

-- ---------------------------------------------------------------------
-- Team: a constructor that enters cars in the championship
-- ---------------------------------------------------------------------
CREATE TABLE Team (
    team_id       INTEGER PRIMARY KEY,
    team_name     TEXT NOT NULL UNIQUE,       -- a team name identifies one team
    base_country  TEXT NOT NULL,
    base_city     TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- Driver: a person who races
-- birth_date is stored as TEXT in ISO format (YYYY-MM-DD)
-- ---------------------------------------------------------------------
CREATE TABLE Driver (
    driver_id    INTEGER PRIMARY KEY,
    driver_name  TEXT NOT NULL,
    nationality  TEXT NOT NULL,
    birth_date   TEXT NOT NULL
        CHECK (birth_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
);

-- ---------------------------------------------------------------------
-- Circuit: a track that hosts races
-- ---------------------------------------------------------------------
CREATE TABLE Circuit (
    circuit_id       INTEGER PRIMARY KEY,
    circuit_name     TEXT NOT NULL UNIQUE,
    city_location    TEXT NOT NULL,
    country_location TEXT NOT NULL,
    track_length_km  REAL NOT NULL CHECK (track_length_km > 0)
);

-- ---------------------------------------------------------------------
-- Race: one Grand Prix on a season's calendar, held at one circuit
-- ---------------------------------------------------------------------
CREATE TABLE Race (
    race_id       INTEGER PRIMARY KEY,
    circuit_id    INTEGER NOT NULL,
    season_year   INTEGER NOT NULL CHECK (season_year >= 1950),
    round_number  INTEGER NOT NULL CHECK (round_number >= 1),
    race_name     TEXT NOT NULL,
    race_date     TEXT NOT NULL
        CHECK (race_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    FOREIGN KEY (circuit_id) REFERENCES Circuit (circuit_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- A season can only have one race per round number
    UNIQUE (season_year, round_number)
);

-- ---------------------------------------------------------------------
-- Driver_Entry: JUNCTION TABLE resolving the Driver <-> Team many-to-many.
-- One row = one driver racing for one team in one season. A driver who
-- changes team mid-season (for example Oliver Bearman in 2024) has one
-- entry per team.
-- ---------------------------------------------------------------------
CREATE TABLE Driver_Entry (
    entry_id     INTEGER PRIMARY KEY,
    driver_id    INTEGER NOT NULL,
    team_id      INTEGER NOT NULL,
    season_year  INTEGER NOT NULL CHECK (season_year >= 1950),
    car_number   INTEGER NOT NULL CHECK (car_number BETWEEN 1 AND 99),
    FOREIGN KEY (driver_id) REFERENCES Driver (driver_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (team_id) REFERENCES Team (team_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- Design rule: at most one entry per driver, team and season
    UNIQUE (driver_id, team_id, season_year),
    -- Two cars cannot share a number in the same season
    UNIQUE (season_year, car_number)
);

-- ---------------------------------------------------------------------
-- Race_Result: how one Driver_Entry finished one Race
-- finish_position is NULL for a driver who did not finish (DNF);
-- finish_status records 'Finished' or the reason for the DNF.
-- ---------------------------------------------------------------------
CREATE TABLE Race_Result (
    result_id        INTEGER PRIMARY KEY,
    race_id          INTEGER NOT NULL,
    entry_id         INTEGER NOT NULL,
    grid_position    INTEGER NOT NULL CHECK (grid_position >= 1),
    finish_position  INTEGER CHECK (finish_position IS NULL OR finish_position >= 1),
    points           REAL NOT NULL DEFAULT 0 CHECK (points >= 0),
    finish_status    TEXT NOT NULL DEFAULT 'Finished',
    FOREIGN KEY (race_id) REFERENCES Race (race_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (entry_id) REFERENCES Driver_Entry (entry_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- An entry can only have one result per race
    UNIQUE (race_id, entry_id),
    -- A finisher has a position; a DNF does not (and vice versa)
    CHECK (
        (finish_position IS NOT NULL AND finish_status = 'Finished')
        OR
        (finish_position IS NULL AND finish_status <> 'Finished')
    )
);

-- ---------------------------------------------------------------------
-- Indexes (created intentionally, in addition to the automatic key indexes)
-- ---------------------------------------------------------------------
-- UNIQUE (race_id, entry_id) already speeds up "results for a race", but
-- not "all results for an entry". This index supports that join, which is
-- used by career and season totals (Driver_Entry -> Race_Result).
CREATE INDEX idx_race_result_entry ON Race_Result (entry_id);

-- Supports looking up a driver by name in the application's search.
CREATE INDEX idx_driver_name ON Driver (driver_name);

-- ---------------------------------------------------------------------
-- View 1: season driver standings, calculated from results.
-- Championship standings are NOT stored in a table; this view derives them
-- so they can never be out of sync with Race_Result. Results are totalled per
-- driver and season (a driver with two team entries appears once, with both
-- team names).
-- ---------------------------------------------------------------------
CREATE VIEW v_driver_season_standings AS
SELECT
    de.season_year,
    d.driver_id,
    d.driver_name,
    GROUP_CONCAT(DISTINCT t.team_name)                     AS team_name,
    COUNT(rr.result_id)                                    AS races_entered,
    COALESCE(SUM(rr.points), 0)                            AS total_points,
    COALESCE(SUM(CASE WHEN rr.finish_position = 1 THEN 1 ELSE 0 END), 0) AS wins,
    COALESCE(SUM(CASE WHEN rr.finish_position <= 3 THEN 1 ELSE 0 END), 0) AS podiums
FROM Driver_Entry de
JOIN Driver d ON d.driver_id = de.driver_id
JOIN Team   t ON t.team_id   = de.team_id
LEFT JOIN Race_Result rr ON rr.entry_id = de.entry_id
GROUP BY de.season_year, d.driver_id;

-- ---------------------------------------------------------------------
-- View 2: one readable row per result (joins all six tables).
-- ---------------------------------------------------------------------
CREATE VIEW v_race_results_detail AS
SELECT
    r.season_year,
    r.round_number,
    r.race_name,
    r.race_date,
    c.circuit_name,
    c.country_location,
    d.driver_name,
    t.team_name,
    de.car_number,
    rr.grid_position,
    rr.finish_position,
    rr.points,
    rr.finish_status
FROM Race_Result rr
JOIN Race         r  ON r.race_id     = rr.race_id
JOIN Circuit      c  ON c.circuit_id  = r.circuit_id
JOIN Driver_Entry de ON de.entry_id   = rr.entry_id
JOIN Driver       d  ON d.driver_id   = de.driver_id
JOIN Team         t  ON t.team_id     = de.team_id;
