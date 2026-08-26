import json
import subprocess
import sys
from datetime import datetime

QUERY = """
{
  user(login: "%s") {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

W, H = 1000, 240
PAD_L, PAD_R, PAD_T, PAD_B = 46, 16, 54, 34
FONT = "system-ui,-apple-system,Segoe UI,sans-serif"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fetch(user):
    out = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=" + QUERY % user],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def to_weeks(cal):
    weeks = []
    for wk in cal["weeks"]:
        days = wk["contributionDays"]
        if not days:
            continue
        weeks.append({
            "date": datetime.strptime(days[0]["date"], "%Y-%m-%d"),
            "count": sum(d["contributionCount"] for d in days),
        })
    return weeks


def nice_max(v):
    if v <= 10:
        return 10
    step = 10 ** (len(str(int(v))) - 1)
    return int((v // step + 1) * step)


def render(cal):
    weeks = to_weeks(cal)
    total = cal["totalContributions"]
    peak = max(w["count"] for w in weeks)
    top = nice_max(peak)

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / len(weeks)
    bar_w = max(3.0, slot - 3)

    p = []
    p.append(
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' "
        f"width='100%' role='img' aria-label='Weekly GitHub contributions over the last 12 months'>"
    )
    p.append("<defs>")
    p.append("<linearGradient id='bar' x1='0' y1='1' x2='0' y2='0'>"
             "<stop offset='0%' stop-color='#70a5fd'/>"
             "<stop offset='100%' stop-color='#bf91f3'/></linearGradient>")
    p.append("</defs>")
    p.append(f"<rect width='{W}' height='{H}' rx='8' fill='#1a1b27'/>")
    p.append(f"<text x='{PAD_L}' y='26' fill='#e2e8f0' font-family='{FONT}' "
             f"font-size='17' font-weight='600'>Contributions</text>")
    p.append(f"<text x='{PAD_L}' y='44' fill='#8b949e' font-family='{FONT}' font-size='12'>"
             f"{total:,} in the last year &#183; peak {peak:,} in a week</text>")

    for i in range(5):
        val = top * (4 - i) / 4
        y = PAD_T + plot_h * i / 4
        p.append(f"<line x1='{PAD_L}' y1='{y:.1f}' x2='{W - PAD_R}' y2='{y:.1f}' "
                 f"stroke='#2c2f45' stroke-width='1'/>")
        p.append(f"<text x='{PAD_L - 8}' y='{y + 3.5:.1f}' text-anchor='end' fill='#8b949e' "
                 f"font-family='{FONT}' font-size='10'>{int(val)}</text>")

    seen = set()
    for i, w in enumerate(weeks):
        x = PAD_L + i * slot
        h = (w["count"] / top) * plot_h
        y = PAD_T + plot_h - h
        if h > 0:
            r = min(2.0, bar_w / 2)
            p.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{h:.1f}' rx='{r:.1f}' fill='url(#bar)'>"
                     f"<title>{w['date']:%b %d, %Y} &#183; {w['count']:,} contributions</title></rect>")
        key = (w["date"].year, w["date"].month)
        if w["date"].day <= 7 and key not in seen:
            seen.add(key)
            p.append(f"<text x='{x:.1f}' y='{H - PAD_B + 18}' text-anchor='middle' fill='#8b949e' "
                     f"font-family='{FONT}' font-size='10'>{MONTHS[w['date'].month - 1]}</text>")

    p.append("</svg>")
    return "\n".join(p)


if __name__ == "__main__":
    user = sys.argv[1] if len(sys.argv) > 1 else "Jobayer109"
    dest = sys.argv[2] if len(sys.argv) > 2 else "assets/contributions.svg"
    svg = render(fetch(user))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {dest} ({len(svg)} bytes)")
