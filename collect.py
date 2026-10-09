#!/usr/bin/env python3
"""每天搜集广受好评的 AI 工具与 AI Skills，生成中文日报。

数据源（全部免 key 公开 API）：
- GitHub Search API：近 2 天创建、已获不少 star 的 AI 相关仓库
- Hacker News Algolia API：近 2 天高分 AI 相关讨论
- GitHub Search API：近 2 天新增的 agent/claude skill 相关仓库

去重：seen.json 记录已收录 URL。
输出：daily/YYYY-MM-DD.md，并更新 README.md 的最新日报与归档列表。
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
NOW = datetime.now(BJ)
DATESTR = NOW.strftime("%Y-%m-%d")
SINCE = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
HN_SINCE_TS = int((NOW - timedelta(days=2)).timestamp())

ROOT = os.path.dirname(os.path.abspath(__file__))
DAILY_DIR = os.path.join(ROOT, "daily")
SEEN_PATH = os.path.join(ROOT, "seen.json")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

UA = {"User-Agent": "ai-tools-daily-digest"}


def gh_get(path):
    headers = {"Accept": "application/vnd.github+json", **UA}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request("https://api.github.com" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def hn_get(params):
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_seen():
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1)


def clean_desc(s, limit=120):
    s = (s or "").replace("\r", " ").replace("\n", " ").strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def collect_github_tools(seen):
    """近 2 天创建、已有一定 star 的 AI 工具/应用仓库。"""
    queries = [
        f"ai agent stars:>30 created:>{SINCE}",
        f"llm tool stars:>30 created:>{SINCE}",
    ]
    items = []
    for q in queries:
        try:
            data = gh_get("/search/repositories?" + urllib.parse.urlencode(
                {"q": q, "sort": "stars", "order": "desc", "per_page": 15}))
        except Exception as e:
            print(f"github search failed ({q}): {e}")
            continue
        for r in data.get("items", []):
            url = r["html_url"]
            if url in seen:
                continue
            seen[url] = DATESTR
            items.append({
                "name": r["full_name"],
                "url": url,
                "desc": clean_desc(r.get("description")),
                "stars": r.get("stargazers_count", 0),
                "lang": r.get("language") or "-",
            })
    items.sort(key=lambda x: -x["stars"])
    return items[:20]


def collect_hn(seen):
    """近 2 天 HN 上高分的 AI 工具相关讨论。"""
    try:
        data = hn_get({
            "query": "AI tool",
            "tags": "story",
            "numericFilters": f"created_at_i>{HN_SINCE_TS},points>40",
            "hitsPerPage": 30,
        })
    except Exception as e:
        print(f"hn search failed: {e}")
        return []
    hits = [h for h in data.get("hits", []) if h.get("title")]
    hits.sort(key=lambda h: -(h.get("points") or 0))
    items = []
    for h in hits[:12]:
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
        key = f"hn:{h['objectID']}"
        if key in seen:
            continue
        seen[key] = DATESTR
        items.append({
            "title": h["title"],
            "url": url,
            "points": h.get("points", 0),
            "comments": h.get("num_comments", 0),
        })
    return items


def collect_skills(seen):
    """近 2 天新增的 AI agent / Claude skill 相关仓库。"""
    queries = [
        f"claude skill in:name,description stars:>5 created:>{SINCE}",
        f"agent skill in:name,description stars:>5 created:>{SINCE}",
    ]
    items = []
    for q in queries:
        try:
            data = gh_get("/search/repositories?" + urllib.parse.urlencode(
                {"q": q, "sort": "stars", "order": "desc", "per_page": 10}))
        except Exception as e:
            print(f"skill search failed ({q}): {e}")
            continue
        for r in data.get("items", []):
            url = r["html_url"]
            if url in seen:
                continue
            seen[url] = DATESTR
            items.append({
                "name": r["full_name"],
                "url": url,
                "desc": clean_desc(r.get("description")),
                "stars": r.get("stargazers_count", 0),
            })
    items.sort(key=lambda x: -x["stars"])
    return items[:10]


def render_digest(tools, hn_items, skills):
    lines = [
        f"# AI 工具日报 {DATESTR}",
        "",
        "> 每天自动搜集广受好评的 AI 工具与 AI Skills。数据来源：GitHub、Hacker News。",
        "",
        "## 🔥 GitHub 热门 AI 项目",
        "",
    ]
    if tools:
        for t in tools:
            lines.append(
                f"- [{t['name']}]({t['url']}) — {t['desc']} "
                f"⭐ {t['stars']} · {t['lang']}")
    else:
        lines.append("今日暂无新增热门项目。")
    lines += ["", "## 💬 Hacker News 热议", ""]
    if hn_items:
        for h in hn_items:
            lines.append(
                f"- [{h['title']}]({h['url']}) — "
                f"{h['points']} points · {h['comments']} comments")
    else:
        lines.append("今日暂无高分讨论。")
    lines += ["", "## 🛠️ 新增 AI Skills", ""]
    if skills:
        for s in skills:
            lines.append(
                f"- [{s['name']}]({s['url']}) — {s['desc']} ⭐ {s['stars']}")
    else:
        lines.append("今日暂无新增 Skill。")
    lines += [
        "",
        "## 📊 今日统计",
        "",
        f"- GitHub 新增收录：{len(tools)} 个",
        f"- HN 热议：{len(hn_items)} 条",
        f"- 新增 Skills：{len(skills)} 个",
        "",
    ]
    return "\n".join(lines)


def update_readme():
    days = sorted(
        (f[:-3] for f in os.listdir(DAILY_DIR) if f.endswith(".md")),
        reverse=True,
    )
    latest = days[0] if days else None
    archive = "\n".join(f"- [{d}](daily/{d}.md)" for d in days[:30])
    readme = f"""# ai-tools-daily

每天自动搜集**广受好评的 AI 工具**与 **AI Skills**，生成中文日报。

- 数据来源：GitHub（近 2 天高 star 新项目）、Hacker News（高分讨论）
- 更新时间：每天 08:00（北京时间）自动运行
- 去重：已收录过的项目不会重复出现

## 📰 最新日报

{f"- [{latest}](daily/{latest}.md)" if latest else "暂无"}

## 📚 历史归档

{archive if archive else "暂无"}
"""
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)


def main():
    os.makedirs(DAILY_DIR, exist_ok=True)
    seen = load_seen()
    tools = collect_github_tools(seen)
    hn_items = collect_hn(seen)
    skills = collect_skills(seen)
    save_seen(seen)

    digest = render_digest(tools, hn_items, skills)
    with open(os.path.join(DAILY_DIR, f"{DATESTR}.md"), "w", encoding="utf-8") as f:
        f.write(digest)
    update_readme()
    print(f"digest {DATESTR}: tools={len(tools)} hn={len(hn_items)} skills={len(skills)}")


if __name__ == "__main__":
    main()
