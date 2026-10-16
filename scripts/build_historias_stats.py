#!/usr/bin/env python3
"""Build data/historias-stats.json for the Historias de Pasta dashboard.

Inputs (exported from Metricool, brand "Historias de Pasta"):
  data/metricool/evolution.json    daily account metrics, one row per day
  data/metricool/tiktok_posts.json per-video TikTok views (date, title, views)

Usage: python3 scripts/build_historias_stats.py [--updated YYYY-MM-DD]
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "metricool"
OUT = ROOT / "data" / "historias-stats.json"
LAUNCH = "2026-10-04"  # first day with real publishing volume

PLATFORMS = [
    # id, name, handle, url, followers column, daily-views column
    ("instagram", "Instagram", "@historias_pasta", "https://www.instagram.com/historias_pasta/", "ig_followers", "ig_reels_views"),
    ("tiktok", "TikTok", "@historias.pasta", "https://www.tiktok.com/@historias.pasta", "tk_followers", None),
    ("youtube", "YouTube", "Historias de Pasta", "https://www.youtube.com/channel/UCrToCbAnFH1Al7mHJjlORAw", "yt_subs", "yt_views"),
    ("facebook", "Facebook", "Historias de Pasta", "https://www.facebook.com/1366206256581346", "fb_followers", "fb_reels_views"),
]


def num(v):
    return None if v in (None, "") else float(v)


def iso(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def main():
    updated = date.today().isoformat()
    if "--updated" in sys.argv:
        updated = sys.argv[sys.argv.index("--updated") + 1]

    evo = json.loads((RAW / "evolution.json").read_text())
    cols = evo["columns"]
    days = {}
    for row in evo["rows"]:
        r = dict(zip(cols, row))
        days[iso(r["date"])] = r

    tk = json.loads((RAW / "tiktok_posts.json").read_text())
    tk_rows = [dict(zip(tk["columns"], r)) for r in tk["rows"]]
    tk_by_day = {}
    for r in tk_rows:
        d = iso(r["date"])
        tk_by_day[d] = tk_by_day.get(d, 0) + int(float(r["views"]))

    # Window: launch → last day where any views were recorded
    view_cols = [p[5] for p in PLATFORMS if p[5]]
    last = max(
        [d for d, r in days.items() if any(num(r.get(c)) for c in view_cols)]
        + list(tk_by_day)
    )
    start = datetime.fromisoformat(LAUNCH).date()
    end = datetime.fromisoformat(last).date()
    window = [(start + timedelta(n)).isoformat() for n in range((end - start).days + 1)]

    platforms = []
    for pid, name, handle, url, fcol, vcol in PLATFORMS:
        # follower series (only days Metricool recorded a value)
        fseries = [[d, int(num(days[d][fcol]))] for d in sorted(days) if num(days[d].get(fcol)) is not None]
        followers = fseries[-1][1] if fseries else 0
        if pid == "tiktok":
            first = min(tk_by_day)
            vseries = [[d, tk_by_day.get(d, 0) if d >= first else None] for d in window]
            views_all = sum(tk_by_day.values())
        else:
            # None = not reported yet (lag) or not tracked; keep it out of the chart
            vseries = [[d, None if num(days.get(d, {}).get(vcol)) is None else int(num(days[d][vcol]))] for d in window]
            views_all = int(sum(num(r.get(vcol)) or 0 for r in days.values()))
        platforms.append({
            "id": pid, "name": name, "handle": handle, "url": url,
            "followers": followers, "views": views_all,
            "followersSeries": fseries, "viewsSeries": vseries,
        })

    top = sorted(tk_rows, key=lambda r: -float(r["views"]))[:3]
    stats = {
        "updated": updated,
        "launched": LAUNCH,
        "source": "Metricool",
        "totals": {
            "followers": sum(p["followers"] for p in platforms),
            "views": sum(p["views"] for p in platforms),
            "days": (datetime.fromisoformat(updated).date() - start).days,
        },
        "platforms": platforms,
        "topVideos": [
            {"platform": "TikTok", "title": r["title"], "views": int(float(r["views"])), "date": iso(r["date"])}
            for r in top
        ],
        "notes": "TikTok and Instagram views are counted on the day each video was published; "
                 "YouTube and Facebook report views per day. Platforms report with a 1–2 day lag.",
    }
    OUT.write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    t = stats["totals"]
    print(f"wrote {OUT.relative_to(ROOT)}: {t['followers']} followers, {t['views']} views, window {window[0]}→{window[-1]}")


if __name__ == "__main__":
    main()
