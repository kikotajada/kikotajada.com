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
# Per-video files for the "most-watched" ranking, each [date, title/caption, views]:
#   instagram_reels.json  ["IGRE01","IGRE03","IGRE23"]
#   youtube_videos.json   ["YTVP01","YTVP17","YTVP06"]
#   facebook_reels.json   ["FBRE01","FBRE05","FBRE10"]
#   youtube_videos.json may also carry url + thumbnail: ["YTVP01","YTVP17","YTVP06","YTVP05","YTVP03"]
# Links/thumbnails for Instagram and Facebook, each [date, views, url, thumb]:
#   instagram_links.json  ["IGRE01","IGRE23","IGRE06","IGRE05"]
#   facebook_links.json   ["FBRE01","FBRE10","FBRE06","FBRE04"]
# TikTok links come from tiktok_posts.json when fetched as ["TKPO01","TKPO05","TKPO07","TKPO03","TKPO04"],
# or from the slim daily tiktok_links.json ["TKPO01","TKPO07","TKPO03"] = [date, views, url]
# (cover derived from the video id: static.metricool.com/tkvideocovers/YYYYMM/<brand>-<id>.jpeg).
# Daily view refresh, each [date, views, url] — overrides the views above, matched on url:
#   instagram_views.json  ["IGRE01","IGRE23","IGRE06"]
#   facebook_views.json   ["FBRE01","FBRE10","FBRE06"]
#   youtube_views.json    ["YTVP01","YTVP06","YTVP05"]
# The reels/videos/links files above are a static catalog (titles, thumbnails); refresh them
# occasionally to pick up captions of new videos. New videos only in a *_views file still rank.
VIDEO_FILES = [
    ("instagram_reels.json", "Instagram", "instagram_links.json"),
    ("youtube_videos.json", "YouTube", None),
    ("facebook_reels.json", "Facebook", "facebook_links.json"),
]
VIEW_FILES = {"Instagram": "instagram_views.json", "YouTube": "youtube_views.json", "Facebook": "facebook_views.json"}
BRAND_ID = "7304322"

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


def clean_url(u):
    """Drop tracking query strings (TikTok's utm_*), keep YouTube's ?v=."""
    if not u:
        return None
    if "youtube.com/watch" in u:
        return u
    return u.split("?", 1)[0]


def better_thumb(thumb, url):
    """YouTube: Metricool gives the 120px default.jpg; use the 320x180 16:9 one instead."""
    m = re.search(r"[?&]v=([\w-]{11})", url or "")
    if m and "youtube.com" in (url or ""):
        return f"https://i.ytimg.com/vi/{m.group(1)}/mqdefault.jpg"
    return thumb or None


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
    # Columns: date, description, views[, url, cover] — the last two are optional.
    tk_rows = [dict(zip(["date", "title", "views", "url", "thumb"], r)) for r in tk["rows"] if r and r[2] not in (None, "")]
    tk_by_day = {}
    for r in tk_rows:
        d = iso(r["date"])
        tk_by_day[d] = tk_by_day.get(d, 0) + int(float(r["views"]))

    # Window: launch → last day where any views were recorded, but never later than
    # two days before the run: the most recent day is still incomplete in Metricool.
    view_cols = [p[5] for p in PLATFORMS if p[5]]
    last = max(
        [d for d, r in days.items() if any(num(r.get(c)) for c in view_cols)]
        + list(tk_by_day)
    )
    start = datetime.fromisoformat(LAUNCH).date()
    chart_cutoff = datetime.fromisoformat(updated).date() - timedelta(days=2)
    end = min(datetime.fromisoformat(last).date(), chart_cutoff)
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

    # Most-watched videos across every platform. Per-video files are optional:
    # a missing one just leaves that platform out of the ranking.
    tk_links = {}
    tlf = RAW / "tiktok_links.json"
    if tlf.exists():
        for lr in json.loads(tlf.read_text()).get("rows", []):
            if lr and len(lr) >= 3 and lr[1] not in (None, "") and lr[2]:
                tk_links[(lr[0], int(float(lr[1])))] = lr[2]
    videos = []
    for r in tk_rows:
        r = dict(r, platform="TikTok")
        if not r.get("url"):
            r["url"] = tk_links.get((r["date"], int(float(r["views"]))))
        if r.get("url") and not r.get("thumb"):
            m = re.search(r"/video/(\d+)", r["url"])
            if m:
                r["thumb"] = f"https://static.metricool.com/tkvideocovers/{r['date'][:6]}/{BRAND_ID}-{m.group(1)}.jpeg"
        videos.append(r)
    for fname, pname, links_name in VIDEO_FILES:
        f = RAW / fname
        if not f.exists():
            continue
        # Instagram/Facebook responses get too large with url+thumb added, so those
        # come from a separate [date, views, url, thumb] file, matched on date + views.
        links = {}
        lf = RAW / links_name if links_name else None
        if lf and lf.exists():
            for lr in json.loads(lf.read_text()).get("rows", []):
                if lr and len(lr) >= 4 and lr[1] not in (None, ""):
                    links[(lr[0], int(float(lr[1])))] = (lr[2], lr[3])
        for row in json.loads(f.read_text()).get("rows", []):
            if row and len(row) >= 3 and row[2] not in (None, ""):
                url, thumb = (row[3] if len(row) > 3 else None), (row[4] if len(row) > 4 else None)
                if not url:
                    url, thumb = links.get((row[0], int(float(row[2]))), (None, None))
                videos.append({"date": row[0], "title": row[1] or "", "views": row[2],
                               "platform": pname, "url": url, "thumb": thumb})
    # Fresh per-video views (slim daily files) override the catalog, matched on clean url.
    for pname, fname in VIEW_FILES.items():
        f = RAW / fname
        if not f.exists():
            continue
        fresh = {}
        for row in json.loads(f.read_text()).get("rows", []):
            if row and len(row) >= 3 and row[1] not in (None, "") and row[2]:
                fresh[clean_url(row[2])] = (row[0], row[1], row[2])
        seen = set()
        for v in videos:
            if v["platform"] == pname and clean_url(v.get("url")) in fresh:
                k = clean_url(v["url"])
                v["views"] = fresh[k][1]
                seen.add(k)
        for k, (d, views, url) in fresh.items():
            if k not in seen:
                videos.append({"date": d, "title": "", "views": views, "platform": pname, "url": url, "thumb": None})
    top = sorted(videos, key=lambda r: -float(r["views"]))[:3]
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
            {"platform": r["platform"], "title": clean_title(r["title"]), "views": int(float(r["views"])), "date": iso(r["date"]),
             "url": clean_url(r.get("url")), "thumb": better_thumb(r.get("thumb"), r.get("url"))}
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
