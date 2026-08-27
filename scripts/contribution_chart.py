import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from xml.sax.saxutils import escape

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

W, H = 1000, 250
PAD_L, PAD_R, PAD_T, PAD_B = 46, 16, 56, 44
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

BG = "#1a1b27"
BAND = "#20223a"
RULE = "#2c2f45"
EDGE = "#3d4266"
FG = "#e2e8f0"
MUTED = "#8b949e"
DAYS_PER_WEEK = 7


class ChartError(RuntimeError):
    pass


def fetch(login):
    if not login or not login.replace("-", "").isalnum():
        raise ChartError(f"invalid GitHub login: {login!r}")
    try:
        proc = subprocess.run(
            ["gh", "api", "graphql", "-f", "query=" + QUERY, "-F", f"login={login}"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise ChartError("the 'gh' CLI is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise ChartError("timed out calling the GitHub API")

    if proc.returncode != 0:
        raise ChartError(f"GitHub API call failed: {proc.stderr.strip()[:300]}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ChartError("GitHub API returned a non-JSON response")

    if payload.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in payload["errors"])
        raise ChartError(f"GitHub API error: {msg[:300]}")

    user = (payload.get("data") or {}).get("user")
    if not user:
        raise ChartError(f"no such GitHub user: {login}")
    calendar = user["contributionsCollection"]["contributionCalendar"]
    if not calendar.get("weeks"):
        raise ChartError(f"no contribution calendar returned for {login}")
    return calendar


def to_weeks(calendar):
    weeks = []
    for week in calendar["weeks"]:
        days = week.get("contributionDays") or []
        if not days:
            continue
        try:
            start = datetime.strptime(days[0]["date"], "%Y-%m-%d")
            mid = datetime.strptime(days[min(3, len(days) - 1)]["date"], "%Y-%m-%d")
        except (KeyError, ValueError) as exc:
            raise ChartError(f"malformed day entry: {exc}")
        weeks.append({
            "start": start,
            "month": (mid.year, mid.month),
            "count": sum(int(d.get("contributionCount") or 0) for d in days),
            "days": len(days),
            "partial": len(days) < DAYS_PER_WEEK,
        })
    if not weeks:
        raise ChartError("contribution calendar contained no days")
    return weeks


def nice_max(value):
    if value <= 10:
        return 10
    step = 10 ** (len(str(int(value))) - 1)
    return int((value // step + 1) * step)


def month_bands(weeks, x_of, bar_w):
    bands, current = [], None
    for i, week in enumerate(weeks):
        if current is None or week["month"] != current["month"]:
            current = {"month": week["month"], "x0": x_of(i), "x1": x_of(i) + bar_w}
            bands.append(current)
        else:
            current["x1"] = x_of(i) + bar_w
    return bands


def render(calendar):
    weeks = to_weeks(calendar)
    total = int(calendar.get("totalContributions") or 0)

    full = [w for w in weeks if not w["partial"]]
    peak = max((w["count"] for w in full), default=0) or max(w["count"] for w in weeks)
    top = nice_max(peak)

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / len(weeks)
    bar_w = max(3.0, slot - 3)
    x_of = lambda i: PAD_L + i * slot
    has_partial = any(w["partial"] for w in weeks)

    out = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' width='100%' "
        f"role='img' aria-label='Weekly GitHub contributions over the last 12 months'>",
        "<defs><linearGradient id='bar' x1='0' y1='1' x2='0' y2='0'>"
        "<stop offset='0%' stop-color='#70a5fd'/>"
        "<stop offset='100%' stop-color='#bf91f3'/></linearGradient></defs>",
        f"<rect width='{W}' height='{H}' rx='8' fill='{BG}'/>",
        f"<text x='{PAD_L}' y='26' fill='{FG}' font-family=\"{FONT}\" font-size='17' "
        f"font-weight='600'>Contributions</text>",
        f"<text x='{PAD_L}' y='45' fill='{MUTED}' font-family=\"{FONT}\" font-size='12'>"
        f"{total:,} in the last year &#183; peak {peak:,} in a week</text>",
    ]

    bands = month_bands(weeks, x_of, bar_w)
    for i, band in enumerate(bands):
        x0, x1 = band["x0"] - 1.5, band["x1"] + 1.5
        if i % 2 == 0:
            out.append(f"<rect x='{x0:.1f}' y='{PAD_T}' width='{x1 - x0:.1f}' "
                       f"height='{plot_h}' fill='{BAND}'/>")
        if i:
            out.append(f"<line x1='{x0:.1f}' y1='{PAD_T - 6}' x2='{x0:.1f}' "
                       f"y2='{PAD_T + plot_h + 6}' stroke='{EDGE}' stroke-width='1'/>")
        year, month = band["month"]
        label = MONTHS[month - 1]
        if month == 1 or i == 0:
            label += f" &#8217;{str(year)[2:]}"
        out.append(f"<text x='{(x0 + x1) / 2:.1f}' y='{PAD_T + plot_h + 22}' "
                   f"text-anchor='middle' fill='{MUTED}' font-family=\"{FONT}\" "
                   f"font-size='10'>{label}</text>")

    for i in range(5):
        value = top * (4 - i) / 4
        y = PAD_T + plot_h * i / 4
        out.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{W - PAD_R}' y2='{y:.1f}' "
                   f"stroke='{RULE}' stroke-width='1'/>")
        out.append(f"<text x='{PAD_L - 8}' y='{y + 3.5:.1f}' text-anchor='end' "
                   f"fill='{MUTED}' font-family=\"{FONT}\" font-size='10'>{int(value)}</text>")

    for i, week in enumerate(weeks):
        height = min(plot_h, (week["count"] / top) * plot_h) if top else 0
        if height <= 0:
            continue
        x, y = x_of(i), PAD_T + plot_h - height
        note = f" &#183; partial week ({week['days']} of 7 days)" if week["partial"] else ""
        tip = escape(f"{week['start']:%b %d, %Y}") + f" &#183; {week['count']:,} contributions{note}"
        opacity = " opacity='0.45'" if week["partial"] else ""
        out.append(
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{height:.1f}' "
            f"rx='{min(2.0, bar_w / 2):.1f}' fill='url(#bar)'{opacity}>"
            f"<title>{tip}</title></rect>"
        )

    if has_partial:
        out.append(f"<text x='{W - PAD_R}' y='45' text-anchor='end' fill='{MUTED}' "
                   f"font-family=\"{FONT}\" font-size='10'>faded bar = current partial week</text>")

    out.append("</svg>")
    return "\n".join(out)


def main():
    login = sys.argv[1] if len(sys.argv) > 1 else "Jobayer109"
    dest = sys.argv[2] if len(sys.argv) > 2 else "assets/contributions.svg"
    try:
        svg = render(fetch(login))
    except ChartError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".svg")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(svg)
        os.replace(tmp, dest)
    except BaseException:
        os.path.exists(tmp) and os.unlink(tmp)
        raise
    print(f"wrote {dest} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
