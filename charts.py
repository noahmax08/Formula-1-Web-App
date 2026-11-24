"""
charts.py -- builds the race-by-race standings ("bump") chart as inline SVG.

Drawing the chart on the server means it works offline on localhost with no
JavaScript libraries. All text is escaped, so driver names cannot inject markup.
"""
from html import escape

# Team colours (close to the real liveries, darkened a little so they stay readable on white).
# To change a team's colour, edit its hex value here.
TEAM_COLOURS = {
    "Red Bull Racing": "#3671C6",
    "Ferrari": "#E8002D",
    "Mercedes": "#00B5A8",
    "McLaren": "#FF8000",
    "Aston Martin": "#1F7A4D",
    "Kick Sauber": "#4DB82E",
    "Haas": "#7F858A",
    "RB": "#7A8CFF",
    "Williams": "#2BA3E0",
    "Alpine": "#E86DAA",
}
# Used for any team not listed above (cycled in order)
FALLBACK_COLOURS = ["#911eb4", "#9a6324", "#800000", "#000075", "#f032e6", "#808000"]
# Teammates share a colour; the 1st driver is solid, the others use these dash patterns
DASH_PATTERNS = ["", "8 5", "2 5", "10 4 2 4"]

WIDTH = 980
LEFT, RIGHT, TOP, BOTTOM = 215, 215, 30, 110
ROW_HEIGHT = 36


def _short_race(name):
    return name.replace(" Grand Prix", "")


def _group(rows, name_key="driver_name"):
    """Return (rounds, race_names, lines) where lines maps name -> {round: row}, ordered by final position."""
    rows = [dict(r) for r in rows]
    rounds = sorted({r["round_number"] for r in rows})
    last = rounds[-1]
    order = [r[name_key] for r in sorted(
        (r for r in rows if r["round_number"] == last), key=lambda r: r["standing"])]
    by_driver = {name: {} for name in order}
    for r in rows:
        by_driver[r[name_key]][r["round_number"]] = r
    race_names = {r["round_number"]: r["race_name"] for r in rows}
    return rounds, race_names, by_driver


def bump_chart_svg(rows, mode="driver"):
    """
    Build the SVG for rows from db.standings_progression (mode="driver") or
    db.team_progression (mode="team"). The rows must not be empty.
    """
    teams_mode = mode == "team"
    rounds, race_names, drivers = _group(rows, "team_name" if teams_mode else "driver_name")
    n_drivers = len(drivers)
    height = TOP + (n_drivers - 1) * ROW_HEIGHT + BOTTOM
    plot_w = max(WIDTH - LEFT - RIGHT, 44 * (len(rounds) - 1))  # wider for long seasons
    width = LEFT + plot_w + RIGHT
    step = plot_w / (len(rounds) - 1) if len(rounds) > 1 else 0
    x0 = LEFT if len(rounds) > 1 else LEFT + plot_w / 2

    def x(rnd):
        return x0 + rounds.index(rnd) * step

    def y(pos):
        return TOP + (pos - 1) * ROW_HEIGHT

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="bump" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="Championship position after each race">']

    # Grid and axes
    out.append('<g class="axis">')
    for pos in range(1, n_drivers + 1):
        out.append(f'<line x1="{LEFT - 10}" x2="{width - RIGHT + 10}" y1="{y(pos)}" y2="{y(pos)}" class="grid"/>')
        out.append(f'<text x="28" y="{y(pos) + 4}" text-anchor="end">P{pos}</text>')
    for rnd in rounds:
        out.append(f'<line x1="{x(rnd):.1f}" x2="{x(rnd):.1f}" y1="{TOP - 12}" '
                   f'y2="{y(n_drivers) + 12}" class="grid vgrid"/>')
        label_y = y(n_drivers) + 30
        out.append(f'<text x="{x(rnd):.1f}" y="{label_y}" text-anchor="end" '
                   f'transform="rotate(-35 {x(rnd):.1f} {label_y})">'
                   f'R{rnd} {escape(_short_race(race_names[rnd]))}</text>')
    out.append('</g>')

    # One group per driver: line, points with tooltips, and name labels
    colour_of = team_colours(rows)
    seen_in_team = {}
    for name, by_round in drivers.items():
        team = next(iter(by_round.values()))["team_name"]
        colour = colour_of[team]
        n = seen_in_team.get(team, 0)           # teammates: 1st solid, then dashed, dotted...
        seen_in_team[team] = n + 1
        pattern = "" if teams_mode else DASH_PATTERNS[n % len(DASH_PATTERNS)]
        label = name if teams_mode else f"{name} ({team})"
        dash = f' stroke-dasharray="{pattern}"' if pattern else ""
        present = [r for r in rounds if r in by_round]   # rounds from the driver's first race
        pts = " ".join(f"{x(r):.1f},{y(by_round[r]['standing'])}" for r in present)
        first, last = by_round[present[0]], by_round[present[-1]]
        out.append(f'<g class="driver" tabindex="0">')
        out.append(f'<title>{escape(label)}</title>')
        out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="3.5" '
                   f'stroke-linejoin="round" stroke-linecap="round"{dash}/>')
        for r in present:
            row = by_round[r]
            tip = (f"{label} after round {r} ({_short_race(row['race_name'])}): "
                   f"P{row['standing']}, {row['points_after']:g} points")
            out.append(f'<circle cx="{x(r):.1f}" cy="{y(row["standing"])}" r="6" fill="#fff" '
                       f'stroke="{colour}" stroke-width="3"><title>{escape(tip)}</title></circle>')
        # each label is drawn twice: a white "halo" underneath, then the coloured text,
        # so names stay readable where lines cross them (works in every browser)
        for cls, fill in (("halo", ""), ("name", f' fill="{colour}"')):
            if present[0] == rounds[0]:  # drivers who join later are labelled on the right only
                out.append(f'<text x="{x(present[0]) - 14:.1f}" y="{y(first["standing"]) + 4}" '
                           f'text-anchor="end" class="{cls}"{fill}>{escape(name)}</text>')
            out.append(f'<text x="{x(present[-1]) + 14:.1f}" y="{y(last["standing"]) + 4}" '
                       f'class="{cls}"{fill}>{escape(name)} · {last["points_after"]:g} pts</text>')
        out.append('</g>')
    out.append('</svg>')
    return "\n".join(out)


def team_colours(rows):
    """Map each team in the rows to a colour (known teams keep their livery colour)."""
    teams = list(dict.fromkeys(dict(r)["team_name"] for r in rows))
    spare = iter(FALLBACK_COLOURS * 3)
    return {t: TEAM_COLOURS.get(t) or next(spare) for t in teams}


def team_legend(rows):
    """Legend entries (team + colour), ordered by each team's best-placed driver."""
    _rounds, _names, drivers = _group(rows)
    colour_of = team_colours(rows)
    order = []
    for by_round in drivers.values():
        team = next(iter(by_round.values()))["team_name"]
        if team not in order:
            order.append(team)
    return [{"team": t, "colour": colour_of[t]} for t in order]


def position_table(rows, mode="driver"):
    """Pivot rows into one dict per driver (or team): final order, with position after each round."""
    teams_mode = mode == "team"
    rounds, _race_names, drivers = _group(rows, "team_name" if teams_mode else "driver_name")
    table = []
    for name, by_round in drivers.items():
        record = {"team" if teams_mode else "driver": name}
        for r in rounds:
            record[f"R{r}"] = by_round[r]["standing"] if r in by_round else None
        record["points"] = by_round[rounds[-1]]["points_after"]
        table.append(record)
    return table