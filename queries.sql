-- =====================================================================
-- F1 Race Results Tracker -- queries.sql  (full 2024 season data)
-- DBMS: SQLite 3. Run by run_queries.sh after schema.sql + insert_data.sql.
-- The ".print" lines are sqlite3 shell commands that label each result.
-- =====================================================================

.print ''
.print '=== Requirement 1: Filtering and Sorting ==='
-- Requirement 1: Filtering and Sorting
-- Who won each race? Keeps only the winning result of every race
-- (WHERE finish_position = 1) and lists the wins in calendar order.
-- Project question: "Who won each race on a given season's calendar?"
SELECT round_number,
       race_name,
       driver_name AS winner,
       team_name   AS winning_team,
       points      AS points_awarded
FROM v_race_results_detail
WHERE finish_position = 1
ORDER BY round_number;

.print ''
.print '=== Requirement 2: INNER JOIN ==='
-- Requirement 2: INNER JOIN
-- Shows the race calendar together with where each race is held, by joining
-- each Race to its Circuit. Only races with a matching circuit are returned.
SELECT r.round_number,
       r.race_name,
       r.race_date,
       c.circuit_name,
       c.country_location AS country,
       c.track_length_km  AS track_km
FROM Race r
INNER JOIN Circuit c ON c.circuit_id = r.circuit_id
ORDER BY r.race_date;

.print ''
.print '=== Requirement 3: LEFT JOIN ==='
-- Requirement 3: LEFT JOIN
-- How many races has each circuit hosted? LEFT JOIN keeps circuits that
-- have no races, so Circuit Paul Ricard and Istanbul Park (real circuits that
-- were not on the 2024 calendar) appear with 0 races instead of being dropped.
SELECT c.circuit_name,
       c.country_location AS country,
       COUNT(r.race_id)   AS races_hosted
FROM Circuit c
LEFT JOIN Race r ON r.circuit_id = c.circuit_id
GROUP BY c.circuit_id
ORDER BY races_hosted, c.circuit_name
LIMIT 6;

.print ''
.print '=== Requirement 4: Three-Table Join ==='
-- Requirement 4: Three-Table Join
-- Which team(s) did each driver race for in 2024, and with what car number?
-- Joins Driver -> Driver_Entry (junction) -> Team. Oliver Bearman appears
-- twice because he raced for Ferrari and then for Haas.
-- Project question: "Which teams has a given driver raced for, and in which seasons?"
SELECT d.driver_name,
       de.season_year,
       t.team_name,
       de.car_number
FROM Driver d
JOIN Driver_Entry de ON de.driver_id = d.driver_id
JOIN Team t          ON t.team_id    = de.team_id
ORDER BY d.driver_name, de.car_number;

.print ''
.print '=== Requirement 5: Aggregate Query ==='
-- Requirement 5: Aggregate Query
-- Season summary for one driver (Max Verstappen): races entered, total
-- points, wins, podiums, and best grid slot, using COUNT, SUM and MIN over
-- all of his results, with no grouping.
-- Project question: "How many wins, podiums, and total points has a given driver earned?"
SELECT COUNT(*)                                                 AS races_entered,
       SUM(rr.points)                                           AS season_points,
       SUM(CASE WHEN rr.finish_position = 1 THEN 1 ELSE 0 END)  AS wins,
       SUM(CASE WHEN rr.finish_position <= 3 THEN 1 ELSE 0 END) AS podiums,
       MIN(rr.grid_position)                                    AS best_grid_position
FROM Race_Result rr
JOIN Driver_Entry de ON de.entry_id  = rr.entry_id
JOIN Driver d        ON d.driver_id  = de.driver_id
WHERE d.driver_name = 'Max Verstappen';

.print ''
.print '=== Requirement 6: GROUP BY and HAVING ==='
-- Requirement 6: GROUP BY and HAVING
-- Constructor (team) points per season, keeping only teams that scored more
-- than 100 points. Groups are team + season; HAVING removes the low-scoring
-- groups (Aston Martin, Alpine, Haas, RB, Williams and Kick Sauber).
-- Project question: "What is the team (constructor) standing for a given season?"
SELECT de.season_year,
       t.team_name,
       SUM(rr.points) AS team_points,
       COUNT(*)       AS results_counted
FROM Race_Result rr
JOIN Driver_Entry de ON de.entry_id = rr.entry_id
JOIN Team t          ON t.team_id   = de.team_id
GROUP BY de.season_year, t.team_id
HAVING SUM(rr.points) > 100
ORDER BY de.season_year, team_points DESC;

.print ''
.print '=== Requirement 7: Subquery ==='
-- Requirement 7: Subquery
-- Which drivers won at least one race, and when were they born? The subquery
-- finds every driver who has a first-place result, and the outer query
-- returns those drivers' details.
SELECT driver_name,
       nationality,
       birth_date
FROM Driver
WHERE driver_id IN (
    SELECT de.driver_id
    FROM Driver_Entry de
    JOIN Race_Result rr ON rr.entry_id = de.entry_id
    WHERE rr.finish_position = 1
)
ORDER BY driver_name;

.print ''
.print '=== Requirement 8: Set Operation (EXCEPT) ==='
-- Requirement 8: Set Operation (EXCEPT)
-- Which drivers reached the podium (top 3) at least once but never won a
-- race? Takes the set of drivers with a podium finish and removes the set of
-- drivers with a first-place finish.
SELECT d.driver_name
FROM Driver d
JOIN Driver_Entry de ON de.driver_id = d.driver_id
JOIN Race_Result rr  ON rr.entry_id  = de.entry_id
WHERE rr.finish_position <= 3
EXCEPT
SELECT d.driver_name
FROM Driver d
JOIN Driver_Entry de ON de.driver_id = d.driver_id
JOIN Race_Result rr  ON rr.entry_id  = de.entry_id
WHERE rr.finish_position = 1
ORDER BY driver_name;

.print ''
.print '=== Requirement 9: View ==='
-- Requirement 9: View (v_driver_season_standings)
-- Driver championship standings for 2024 (race results only). The view
-- already joins Driver, Driver_Entry, Team and Race_Result and totals the
-- points per driver, so this query is a simple filter and sort instead of a
-- four-table join with GROUP BY.
-- Project question: "What is the final driver championship standing for a given season?"
SELECT driver_name,
       team_name,
       races_entered,
       total_points,
       wins,
       podiums
FROM v_driver_season_standings
WHERE season_year = 2024
ORDER BY total_points DESC, wins DESC
LIMIT 10;
