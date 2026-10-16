#!/usr/bin/env python3
"""Build data/historias-stats.json for the Historias de Pasta dashboard.

Inputs: raw Metricool responses (brand "Historias de Pasta", id 7304322),
saved verbatim from getAnalyticsDataByMetrics as {"rows": [...]}:
  data/metricool/evolution.json     metrics = EVOLUTION_METRICS (in that order); last column is the date
  data/metricool/tiktok_posts.json  metrics = TIKTOK_POST_METRICS (date, description, views)

Usage: python3 scripts/build_historias_stats.py [--updated YYYY-MM-DD]
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "metricool"
OUT = ROOT / "data" / "historias-stats.json"
LAUNCH = "2026-10-04"  # first day with real publishing volume

# Order matters: it maps the columns of the raw Metricool response.
EVOLUTION_METRICS = [
    ("YTEV01", "yt_subs"), ("YTEV02", "yt_views"), ("YTEV04", "yt_videos"), ("YTEV05", "yt_gained"),
    ("YTEV06", "yt_lost"), ("TKEV07", "tk_followers"), ("TKEV12", "tk_views"), ("TKEV01", "tk_videos"),
    ("TKEV08", "tk_newf"), ("IGEV01", "ig_followers"), ("IGEV05", "ig_views"), ("IGEV23", "ig_reels_views"),
    ("IGEV37", "ig_posts"), ("FBEV17", "fb_followers"), ("FBEV22", "fb_reels_views"), ("FBEV49", "fb_media_views"),
]
TIKTOK_POST_METRICS = ["TKPO01", "TKPO05", "TKPO07"]  # published date, description, views

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


def clean_title(desc, limit=72):
    """Headline of a TikTok caption: the text before the first emoji or hashtag word."""
    t = re.sub(r"^\s*Replying to @\S+\s*", "", desc)
    t = re.split(r"\s#[^\d\W]|Contenido educativo|Educativo,|Ejemplo ilustrativo", t)[0]
    # cut at the first emoji (captions use them as separators)
    t = re.split(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]|\\ud83", t)[0]
    t = re.sub(r"\s+", " ", t).strip(" .,:;")
    t = re.sub(r"^Est[ea] es \w+\.\s+(?=\S)", "", t)  # drop the series intro ("Este es Dani.")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" .,:;") + "…"
    return t


def main():
    updated = date.today().isoformat()
    if "--updated" in sys.argv:
        updated = sys.argv[sys.argv.index("--updated") + 1]
    as_of = (datetime.fromisoformat(updated).date() - timedelta(days=1)).isoformat()

    evo = json.loads((RAW / "evolution.json").read_text())
    cols = [c for _, c in EVOLUTION_METRICS] + ["date"]
    days = {}
    for row in evo["rows"]:
        r = dict(zip(cols, row))
        days[iso(r["date"])] = r

    tk = json.loads((RAW / "tiktok_posts.json").read_text())
    tk_rows = [dict(zip(["date", "title", "views"], r)) for r in tk["rows"] if r and r[2] not in (None, "")]
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
        "asOf": as_of,  # Metricool lags a day: the data describes the day before the run
        "launched": LAUNCH,
        "source": "Metricool",
        "totals": {
            "followers": sum(p["followers"] for p in platforms),
            "views": sum(p["views"] for p in platforms),
            "days": (datetime.fromisoformat(as_of).date() - start).days + 1,  # launch day counts as day 1
        },
        "platforms": platforms,
        "topVideos": [
            {"platform": "TikTok", "title": clean_title(r["title"]), "views": int(float(r["views"])), "date": iso(r["date"])}
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
