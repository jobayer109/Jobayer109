import calendar
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

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
RULE = "#2c2f45"
FG = "#e2e8f0"
MUTED = "#8b949e"
BAR_GAP = 14


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
        message = "; ".join(e.get("message", "?") for e in payload["errors"])
        raise ChartError(f"GitHub API error: {message[:300]}")

    user = (payload.get("data") or {}).get("user")
    if not user:
        raise ChartError(f"no such GitHub user: {login}")
    cal = user["contributionsCollection"]["contributionCalendar"]
    if not cal.get("weeks"):
        raise ChartError(f"no contribution calendar returned for {login}")
    return cal


def to_months(cal):
    buckets = {}
    for week in cal["weeks"]:
        for day in week.get("contributionDays") or []:
            try:
                date = datetime.strptime(day["date"], "%Y-%m-%d")
            except (KeyError, TypeError, ValueError) as exc:
                raise ChartError(f"malformed day entry: {exc}")
            key = (date.year, date.month)
            bucket = buckets.setdefault(key, {"count": 0, "days": 0})
            bucket["count"] += int(day.get("contributionCount") or 0)
            bucket["days"] += 1

    if not buckets:
        raise ChartError("contribution calendar contained no days")

    months = []
    for (year, month), bucket in sorted(buckets.items()):
        in_month = calendar.monthrange(year, month)[1]
        months.append({
            "year": year,
            "month": month,
            "count": bucket["count"],
            "days": bucket["days"],
            "in_month": in_month,
            "partial": bucket["days"] < in_month,
        })
    return months


def nice_max(value):
    if value <= 10:
        return 10
    step = 10 ** (len(str(int(value))) - 1)
    return int((value // step + 1) * step)


def label_for(entry, index):
    text = MONTHS[entry["month"] - 1]
    if entry["month"] == 1 or index == 0:
        text += f" &#8217;{str(entry['year'])[2:]}"
    return text


def render(cal):
    months = to_months(cal)
    total = int(cal.get("totalContributions") or 0)

    complete = [m for m in months if not m["partial"]]
    peak = max((m["count"] for m in complete), default=0) or max(m["count"] for m in months)
    top = nice_max(peak)

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / len(months)
    bar_w = max(4.0, slot - BAR_GAP)
    partial_count = sum(1 for m in months if m["partial"])

    out = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' width='100%' "
        f"role='img' aria-label='Monthly GitHub contributions over the last 12 months'>",
        "<defs><linearGradient id='bar' x1='0' y1='1' x2='0' y2='0'>"
        "<stop offset='0%' stop-color='#70a5fd'/>"
        "<stop offset='100%' stop-color='#bf91f3'/></linearGradient></defs>",
        f"<rect width='{W}' height='{H}' rx='8' fill='{BG}'/>",
        f"<text x='{PAD_L}' y='26' fill='{FG}' font-family=\"{FONT}\" font-size='17' "
        f"font-weight='600'>Contributions</text>",
        f"<text x='{PAD_L}' y='45' fill='{MUTED}' font-family=\"{FONT}\" font-size='12'>"
        f"{total:,} in the last year &#183; one bar per month</text>",
    ]
    if partial_count:
        out.append(f"<text x='{W - PAD_R}' y='45' text-anchor='end' fill='{MUTED}' "
                   f"font-family=\"{FONT}\" font-size='10'>faded = incomplete month</text>")

    for i in range(5):
        value = top * (4 - i) / 4
        y = PAD_T + plot_h * i / 4
        out.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{W - PAD_R}' y2='{y:.1f}' "
                   f"stroke='{RULE}' stroke-width='1'/>")
        out.append(f"<text x='{PAD_L - 8}' y='{y + 3.5:.1f}' text-anchor='end' fill='{MUTED}' "
                   f"font-family=\"{FONT}\" font-size='10'>{int(value)}</text>")

    for i, entry in enumerate(months):
        height = min(plot_h, (entry["count"] / top) * plot_h) if top else 0
        x = PAD_L + i * slot + (slot - bar_w) / 2
        mid = x + bar_w / 2
        y = PAD_T + plot_h - height
        faded = entry["partial"]

        if height > 0:
            note = (f" &#183; {entry['days']} of {entry['in_month']} days"
                    if faded else "")
            out.append(
                f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{height:.1f}' "
                f"rx='3' fill='url(#bar)'{' opacity=\"0.45\"' if faded else ''}>"
                f"<title>{MONTHS[entry['month'] - 1]} {entry['year']} &#183; "
                f"{entry['count']:,} contributions{note}</title></rect>"
            )
        out.append(f"<text x='{mid:.1f}' y='{y - 7:.1f}' text-anchor='middle' "
                   f"fill='{MUTED if faded else FG}' font-family=\"{FONT}\" font-size='10'>"
                   f"{entry['count']:,}</text>")
        out.append(f"<text x='{mid:.1f}' y='{PAD_T + plot_h + 22}' text-anchor='middle' "
                   f"fill='{MUTED}' font-family=\"{FONT}\" font-size='10'>"
                   f"{label_for(entry, i)}</text>")

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
    handle, tmp = tempfile.mkstemp(dir=parent, suffix=".svg")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(svg)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"wrote {dest} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
