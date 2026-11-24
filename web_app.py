"""
web_app.py -- Flask web application for the F1 Race Results Tracker.

Run with:  python3 web_app.py      then open http://127.0.0.1:5000
(python3 web_app.py --reset rebuilds the database from the SQL files first.)

All SQL lives in db.py (parameterized); input-checking helpers are defined below.
"""
import os
import sqlite3
import sys
from datetime import date, datetime

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, url_for)
from markupsafe import Markup

import charts
import db

app = Flask(__name__)
app.secret_key = os.urandom(16)  # only used to sign flash messages; new each start


# ---------------------------------------------------------------------
# Database connection: one per request, always closed afterwards
# ---------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_error):
    con = g.pop("db", None)
    if con is not None:
        con.close()


@app.template_filter("fmt")
def fmt(value):
    """Display None as a dash and whole-number floats without '.0'."""
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:g}"
    return value


# ---------------------------------------------------------------------
# Input checking for the forms. Each helper returns a (value, error_message)
# pair: the error is None when the input is valid; otherwise the value is None.
# ---------------------------------------------------------------------
def parse_text(raw, label, max_len=50, required=True):
    value = (raw or "").strip()
    if not value:
        return (None, f"{label} is required.") if required else ("", None)
    if len(value) > max_len:
        return None, f"{label} must be {max_len} characters or fewer."
    return value, None


def parse_int(raw, low, high, label):
    try:
        number = int((raw or "").strip())
    except ValueError:
        return None, f"{label} must be a whole number."
    if not low <= number <= high:
        return None, f"{label} must be between {low} and {high}."
    return number, None


def parse_past_date(raw, label):
    """An ISO date (YYYY-MM-DD) between 1900-01-01 and today."""
    try:
        parsed = datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None, f"{label} must be a date in the format YYYY-MM-DD."
    if not date(1900, 1, 1) <= parsed <= date.today():
        return None, f"{label} must be between 1900-01-01 and today."
    return parsed.isoformat(), None


def as_dicts(rows):
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------
# Error pages (no stack traces shown to the user)
# ---------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_error):
    return render_template("message.html", title="Not found",
                           message="That page or record does not exist."), 404


@app.errorhandler(sqlite3.Error)
def database_error(_error):
    return render_template("message.html", title="Database error",
                           message="A database error occurred. No changes were saved."), 500


# ---------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", counts=db.summary_counts(get_db()))


# ---------------------------------------------------------------------
# 1. Search / browse drivers
# ---------------------------------------------------------------------
@app.route("/drivers")
def drivers():
    query = request.args.get("q", "").strip()
    rows = db.search_drivers(get_db(), query)
    return render_template("drivers.html", drivers=rows, query=query)


# ---------------------------------------------------------------------
# 2. Related data: driver profile and race results
# ---------------------------------------------------------------------
@app.route("/drivers/<int:driver_id>")
def driver_profile(driver_id):
    con = get_db()
    driver = db.get_driver(con, driver_id)
    if driver is None:
        abort(404)
    return render_template("driver_profile.html", driver=driver,
                           teams=as_dicts(db.driver_teams(con, driver_id)),
                           results=as_dicts(db.driver_results(con, driver_id)))


@app.route("/races")
def races():
    return render_template("races.html", races=db.list_races(get_db()))


@app.route("/races/<int:race_id>")
def race_detail(race_id):
    con = get_db()
    race = db.get_race(con, race_id)
    if race is None:
        abort(404)
    return render_template("race_detail.html", race=race,
                           results=db.race_results(con, race_id),
                           can_add=bool(db.entries_without_result(con, race_id)))


# ---------------------------------------------------------------------
# 3. Add data: register a driver (one transaction) and record a result
# ---------------------------------------------------------------------
@app.route("/drivers/new", methods=["GET", "POST"])
def new_driver():
    con = get_db()
    teams = db.list_teams(con)
    form, errors = request.form, {}
    if request.method == "POST":
        name, errors["driver_name"] = parse_text(form.get("driver_name"), "Name", 50)
        nationality, errors["nationality"] = parse_text(form.get("nationality"), "Nationality", 30)
        birth_date, errors["birth_date"] = parse_past_date(form.get("birth_date"), "Date of birth")
        season, errors["season_year"] = parse_int(form.get("season_year"), 1950, 2100, "Season")
        car, errors["car_number"] = parse_int(form.get("car_number"), 1, 99, "Car number")
        team_id, errors["team_id"] = parse_int(form.get("team_id"), 1, 10**9, "Team")
        if team_id is not None and team_id not in {t["team_id"] for t in teams}:
            errors["team_id"] = "Choose a team from the list."
        errors = {k: v for k, v in errors.items() if v}
        if not errors and db.driver_exists(con, name, birth_date):
            errors["driver_name"] = "A driver with that name and birth date already exists."
        if not errors and db.car_number_taken(con, season, car):
            errors["car_number"] = f"Car number {car} is already used in {season}."
        if not errors:
            try:
                driver_id = db.register_driver(con, name, nationality, birth_date,
                                               team_id, season, car)
            except sqlite3.IntegrityError as err:
                errors["form"] = db.describe_integrity_error(err)
            else:
                flash(f"Registered {name} for {season} with car number {car}.", "success")
                return redirect(url_for("driver_profile", driver_id=driver_id))
    return render_template("driver_form.html", teams=teams, form=form, errors=errors)


def parse_outcome(con, form, race_id, exclude_result_id=None):
    """Read the finished / DNF part of a form. Returns (position, status, errors)."""
    errors, position, status = {}, None, "Finished"
    outcome = form.get("outcome")
    if outcome == "finished":
        position, err = parse_int(form.get("finish_position"), 1, 30, "Finishing position")
        if err:
            errors["finish_position"] = err
        elif db.finish_position_taken(con, race_id, position, exclude_result_id):
            errors["finish_position"] = f"Another driver already has position {position} in this race."
    elif outcome == "dnf":
        reason, err = parse_text(form.get("dnf_reason"), "Reason", 30)
        if err:
            errors["dnf_reason"] = err
        else:
            status = f"DNF - {reason}"
    else:
        errors["outcome"] = "Choose whether the driver finished the race."
    return position, status, errors


@app.route("/races/<int:race_id>/results/new", methods=["GET", "POST"])
def new_result(race_id):
    con = get_db()
    race = db.get_race(con, race_id)
    if race is None:
        abort(404)
    entries = db.entries_without_result(con, race_id)
    if not entries:
        flash("Every driver entered that season already has a result for this race.", "info")
        return redirect(url_for("race_detail", race_id=race_id))
    form, errors = request.form, {}
    if request.method == "POST":
        entry_id, err = parse_int(form.get("entry_id"), 1, 10**9, "Driver")
        if err or entry_id not in {e["entry_id"] for e in entries}:
            errors["entry_id"] = "Choose a driver from the list."
        grid, err = parse_int(form.get("grid_position"), 1, 30, "Grid position")
        if err:
            errors["grid_position"] = err
        position, status, outcome_errors = parse_outcome(con, form, race_id)
        errors.update(outcome_errors)
        if not errors:
            try:
                db.insert_result(con, race_id, entry_id, grid, position, status)
            except sqlite3.IntegrityError as err:
                errors["form"] = db.describe_integrity_error(err)
            else:
                flash(f"Result recorded ({status}). Points were calculated automatically.", "success")
                return redirect(url_for("race_detail", race_id=race_id))
    return render_template("result_form.html", race=race, entries=entries, form=form,
                           errors=errors, editing=False)


# ---------------------------------------------------------------------
# 4. Update / delete a result
# ---------------------------------------------------------------------
@app.route("/results/<int:result_id>/edit", methods=["GET", "POST"])
def edit_result(result_id):
    con = get_db()
    result = db.get_result(con, result_id)
    if result is None:
        abort(404)
    race = db.get_race(con, result["race_id"])
    errors = {}
    if request.method == "POST":
        form = request.form
        position, status, errors = parse_outcome(con, form, result["race_id"], result_id)
        if not errors:
            try:
                changed = db.update_result(con, result_id, position, status)
            except sqlite3.IntegrityError as err:
                errors["form"] = db.describe_integrity_error(err)
            else:
                flash("Result updated; points were recalculated." if changed
                      else "That result no longer exists.", "success" if changed else "error")
                return redirect(url_for("race_detail", race_id=result["race_id"]))
    else:
        finished = result["finish_position"] is not None
        form = {"outcome": "finished" if finished else "dnf",
                "finish_position": result["finish_position"] or "",
                "dnf_reason": "" if finished else result["finish_status"].replace("DNF - ", "", 1)}
    return render_template("result_form.html", race=race, result=result, form=form,
                           errors=errors, editing=True)


@app.route("/results/<int:result_id>/delete", methods=["GET", "POST"])
def delete_result(result_id):
    con = get_db()
    result = db.get_result(con, result_id)
    if result is None:
        abort(404)
    if request.method == "POST":
        if db.delete_result(con, result_id):
            flash(f"Deleted the result for {result['driver_name']}.", "success")
        else:
            flash("That result no longer exists.", "error")
        return redirect(url_for("race_detail", race_id=result["race_id"]))
    race = db.get_race(con, result["race_id"])
    message = Markup("This will permanently remove <strong>{}</strong>'s result "
                     "({}, {} points) from the {} {}.").format(
        result["driver_name"], result["finish_status"], fmt(result["points"]),
        race["season_year"], race["race_name"])
    return render_template("message.html", title="Delete this result?", message=message,
                           confirm_label="Yes, delete it",
                           cancel_url=url_for("race_detail", race_id=race["race_id"]))


# ---------------------------------------------------------------------
# 5. Reports: driver and team standings
# ---------------------------------------------------------------------
@app.route("/standings")
def standings():
    con = get_db()
    seasons = [r["season_year"] for r in db.list_seasons(con)]
    season = request.args.get("season", type=int)
    if season not in seasons:
        season = seasons[-1] if seasons else None
    driver_rows = team_rows = []
    if season is not None:
        driver_rows = [{"pos": i, **dict(r)} for i, r in enumerate(db.driver_standings(con, season), 1)]
        team_rows = [{"pos": i, **dict(r)} for i, r in enumerate(db.team_standings(con, season), 1)]
    return render_template("standings.html", seasons=seasons, season=season,
                           driver_rows=driver_rows, team_rows=team_rows)


# ---------------------------------------------------------------------
# 6. Additional operation: head-to-head comparison
# ---------------------------------------------------------------------
@app.route("/compare")
def compare():
    con = get_db()
    seasons = [r["season_year"] for r in db.list_seasons(con)]
    all_drivers = db.search_drivers(con, "")
    driver_ids = {d["driver_id"] for d in all_drivers}
    season = request.args.get("season", type=int)
    first = request.args.get("a", type=int)
    second = request.args.get("b", type=int)
    submitted = "season" in request.args
    error = per_race = summary = None
    if submitted:
        if season not in seasons or first not in driver_ids or second not in driver_ids:
            error = "Choose a season and two drivers from the lists."
        elif first == second:
            error = "Please choose two different drivers."
        else:
            per_race, summary = db.head_to_head(con, first, second, season)
            per_race, summary = as_dicts(per_race), as_dicts(summary)
    return render_template("compare.html", seasons=seasons, drivers=all_drivers, season=season,
                           first=first, second=second, error=error, submitted=submitted,
                           per_race=per_race, summary=summary)


# ---------------------------------------------------------------------
# 7. Race-by-race standings chart
# ---------------------------------------------------------------------
@app.route("/progression")
def progression():
    con = get_db()
    seasons = [r["season_year"] for r in db.list_seasons(con)]
    season = request.args.get("season", type=int)
    if season not in seasons:
        season = seasons[-1] if seasons else None
    view = "teams" if request.args.get("view") == "teams" else "drivers"
    mode = "team" if view == "teams" else "driver"
    rows = []
    if season is not None:
        rows = (db.team_progression(con, season) if view == "teams"
                else db.standings_progression(con, season))
    chart = table = legend = None
    if rows:
        chart = charts.bump_chart_svg(rows, mode)
        table = charts.position_table(rows, mode)
        legend = charts.team_legend(rows) if view == "drivers" else None
    return render_template("progression.html", seasons=seasons, season=season, view=view,
                           chart=chart, table=table, legend=legend)


# ---------------------------------------------------------------------
# 8. Transaction demonstration (the web version of transaction.sql)
# ---------------------------------------------------------------------
@app.route("/transaction", methods=["GET", "POST"])
def transaction_demo():
    con = get_db()
    team, race = db.demo_context(con)
    if team is None or race is None:
        return render_template("message.html", title="Transaction demo unavailable",
                               message=f"The demo needs the {db.DEMO_TEAM_NAME} team and the "
                                       f"{db.DEMO_SEASON} {db.DEMO_RACE_NAME}, which are not "
                                       "in this database.")
    result = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reset":
            removed = db.remove_demo_data(con)
            flash("Demo driver, entry and result removed." if removed
                  else "There was no demo data to remove.", "success" if removed else "info")
            return redirect(url_for("transaction_demo"))
        if action in ("rollback", "commit", "fail"):
            if db.demo_data_present(con) or db.car_number_taken(con, db.DEMO_SEASON, db.DEMO_CAR):
                flash("The demo cannot run while its data (or car number "
                      f"{db.DEMO_CAR}) is already in the database. Remove the demo data first.", "error")
                return redirect(url_for("transaction_demo"))
            result = db.run_transaction_demo(action)
    return render_template("transaction.html", result=result,
                           present=db.demo_data_present(con), team=team, race=race,
                           demo=db.DEMO_DRIVER, car=db.DEMO_CAR, season=db.DEMO_SEASON)


if __name__ == "__main__":
    if "--reset" in sys.argv:
        db.build_database()
        print("Database rebuilt from schema.sql and insert_data.sql.")
    elif not db.DB_FILE.exists():
        db.build_database()
    # 127.0.0.1 = this computer only; debug is off so no tracebacks are shown
    app.run(host="127.0.0.1", port=5000, debug=False)