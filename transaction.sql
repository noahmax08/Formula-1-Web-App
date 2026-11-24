-------------------------------------------------------------------------------
-- F1 Race Results Tracker -- transaction.sql  (full 2024 season data)
-- Scenario: a stand-in driver is signed by Williams and gets a result in
-- the 2024 Australian Grand Prix (race 3). Adding the driver, creating their
-- season entry, and recording the result must all succeed together. If any
-- step failed on its own, a result could point at a driver or entry that does
-- not exist, or a driver could be added with no entry. A transaction prevents
-- these partial updates.
-- The demonstration ends with ROLLBACK so the sample data is unchanged.
-- (To keep the changes, replace ROLLBACK with COMMIT.)
-------------------------------------------------------------------------------

PRAGMA foreign_keys = ON;  

.print ''
.print '--- Before the transaction: Williams drivers in 2024 ---'
SELECT driver_name, team_name, total_points
FROM v_driver_season_standings
WHERE season_year = 2024 AND team_name LIKE '%Williams%'
ORDER BY driver_name;

BEGIN TRANSACTION;

-- Step 1: add the new driver (a synthetic sample person)
INSERT INTO Driver (driver_id, driver_name, nationality, birth_date)
VALUES (25, 'Jamie Okafor', 'British', '2003-03-14');

-- Step 2: register the driver with Williams (team 9) for 2024
INSERT INTO Driver_Entry (entry_id, driver_id, team_id, season_year, car_number)
VALUES (26, 25, 9, 2024, 99);

-- Step 3: record the driver's result in the Australian GP (race_id 3). Williams ran
-- only one car in this race, so grid slot 20 was empty and P18 was not taken:
-- started 20th, finished 18th, no points.
INSERT INTO Race_Result (result_id, race_id, entry_id, grid_position,
                         finish_position, points, finish_status)
VALUES (480, 3, 26, 20, 18, 0.0, 'Finished');

.print ''
.print '--- Inside the transaction: all three changes are visible ---'
SELECT driver_name, team_name, races_entered, total_points
FROM v_driver_season_standings
WHERE season_year = 2024 AND team_name LIKE '%Williams%'
ORDER BY driver_name;

-- Undo all three steps together (use COMMIT to make them permanent)
ROLLBACK;

.print ''
.print '--- After ROLLBACK: the new driver, entry and result are gone ---'
SELECT
    (SELECT COUNT(*) FROM Driver       WHERE driver_id = 25)  AS new_driver_rows,
    (SELECT COUNT(*) FROM Driver_Entry WHERE entry_id  = 26)  AS new_entry_rows,
    (SELECT COUNT(*) FROM Race_Result  WHERE result_id = 480) AS new_result_rows;
