#!/usr/bin/env python3
"""每天搜集广受好评的 AI 工具与 AI Skills，生成中文日报。

数据源（全部免 key 公开 API）：
- GitHub Search API：近 2 天创建、已获不少 star 的 AI 相关仓库
- Hacker News Algolia API：近 2 天高分 AI 相关讨论
- GitHub Search API：近 2 天新增的 agent/claude skill 相关仓库

持久化：
- seen.json：去重（URL -> 首次收录日期）
- data.json：累积项目库 [{name, url, desc, stars, lang, category, first_seen}]，
  每天刷新 star 数，用于生成排行榜
输出：
- daily/YYYY-MM-DD.md：双语日报
- LEADERBOARD.md：按 star 排名的双语排行榜
- README.md（英文）/ README.zh-CN.md（中文）：首页均含 Top 10 排行榜预览
"""
import json
import os
import re
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
DATA_PATH = os.path.join(ROOT, "data.json")
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


def load_data():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_data(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def clean_desc(s, limit=140):
    s = (s or "").replace("\r", " ").replace("\n", " ").strip()
    return s[:limit] + ("…" if len(s) > limit else "")

# 分类体系：(key, 英文名, 中文名)
CATEGORIES = [
    ("agent", "AI Agent", "智能体"),
    ("coding", "Coding", "编程开发"),
    ("image-video", "Image & Video", "图像视频"),
    ("audio", "Audio & Voice", "音频语音"),
    ("writing", "Writing", "写作"),
    ("search", "Search & Knowledge", "搜索知识"),
    ("devtools", "Dev Tools", "开发工具"),
    ("data", "Data & Analysis", "数据分析"),
    ("chat", "Chat & Assistant", "对话助手"),
    ("other", "Other", "其他"),
]
CATEGORY_NAMES = {k: (en, zh) for k, en, zh in CATEGORIES}

TOPIC_MAP = {
    "ai-agents": "agent", "agent": "agent", "agents": "agent",
    "autonomous-agents": "agent", "multi-agent": "agent",
    "code": "coding", "coding": "coding", "programming": "coding",
    "code-review": "coding", "copilot": "coding",
    "image": "image-video", "images": "image-video", "video": "image-video",
    "animation": "image-video", "motion-graphics": "image-video",
    "text-to-image": "image-video", "3d": "image-video",
    "audio": "audio", "voice": "audio", "speech": "audio",
    "text-to-speech": "audio", "tts": "audio", "music": "audio",
    "writing": "writing", "blog": "writing", "copywriting": "writing",
    "search": "search", "search-engine": "search", "rag": "search",
    "knowledge-base": "search", "retrieval": "search",
    "devtools": "devtools", "developer-tools": "devtools", "cli": "devtools",
    "terminal": "devtools", "adb": "devtools", "automation": "devtools",
    "data": "data", "analytics": "data", "visualization": "data",
    "chat": "chat", "chatbot": "chat", "assistant": "chat",
    "conversational-ai": "chat",
}

KEYWORDS = {
    "agent": ["agent", "autonomous", "multi-agent", "crewai", "swarm"],
    "coding": ["code", "coding", "programmer", "developer", "ide", "debug",
               "pull request", "readme", "refactor"],
    "image-video": ["image", "video", "motion graphic", "animat", "draw",
                    "paint", "3d", "flip book", "edit video"],
    "audio": ["audio", "voice", "speech", "podcast", "music", "sound"],
    "writing": ["writ", "blog", "copywrit", "essay", "study page", "novel"],
    "search": ["search", "rag", "knowledge", "retriev", "question answer"],
    "devtools": ["devtool", "cli", "terminal", "adb", "deploy", "ci/cd",
                 "control", "pipeline"],
    "data": ["data analy", "dashboard", "chart", "insight"],
    "chat": ["chat", "assistant", "companion", "conversation"],
}


def categorize(name, desc, topics):
    """按 topics 优先、关键词兜底，给仓库定一个主分类。"""
    for t in topics or []:
        t = t.lower().replace("_", "-")
        if t in TOPIC_MAP:
            return TOPIC_MAP[t]
        for key, mapped in TOPIC_MAP.items():
            if key in t:
                return mapped
    text = f"{name} {desc}".lower()
    for cat, words in KEYWORDS.items():
        if any(w in text for w in words):
            return cat
    return "other"


def repo_entry(r, category, first_seen):
    topics = r.get("topics", []) or []
    desc = clean_desc(r.get("description"))
    return {
        "name": r["full_name"],
        "url": r["html_url"],
        "desc": desc,
        "stars": r.get("stargazers_count", 0),
        "lang": r.get("language") or "-",
        "category": category,
        "tags": [categorize(r["full_name"], desc, topics)],
        "first_seen": first_seen,
    }


def backfill_data(seen, data):
    """首次运行时把 seen.json 里已有的仓库补进 data.json。"""
    known = {d["url"] for d in data}
    added = 0
    for url, first_seen in list(seen.items()):
        if url in known or not url.startswith("https://github.com/"):
            continue
        m = re.match(r"https://github\.com/([^/]+)/([^/]+)/?$", url)
        if not m:
            continue
        try:
            r = gh_get(f"/repos/{m.group(1)}/{m.group(2)}")
        except Exception as e:
            print(f"backfill failed for {url}: {e}")
            continue
        desc = (r.get("description") or "").lower()
        category = "skill" if "skill" in r["full_name"].lower() or "skill" in desc else "tool"
        data.append(repo_entry(r, category, first_seen))
        known.add(url)
        added += 1
    if added:
        print(f"backfilled {added} repos into data.json")


def refresh_stars(data):
    """刷新所有收录项目的当前 star 数（失败则保留旧值）。"""
    ok, fail = 0, 0
    for d in data:
        try:
            r = gh_get(f"/repos/{d['name']}")
            d["stars"] = r.get("stargazers_count", d["stars"])
            d["lang"] = r.get("language") or d["lang"]
            if r.get("description"):
                d["desc"] = clean_desc(r.get("description"))
            if not d.get("tags"):
                d["tags"] = [categorize(d["name"], d.get("desc", ""),
                                       r.get("topics", []) or [])]
            ok += 1
        except Exception:
            fail += 1
    print(f"star refresh: ok={ok} fail={fail}")


def collect_github_tools(seen):
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
            items.append(repo_entry(r, "tool", DATESTR))
    items.sort(key=lambda x: -x["stars"])
    return items[:20]


def collect_hn(seen):
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
            items.append(repo_entry(r, "skill", DATESTR))
    items.sort(key=lambda x: -x["stars"])
    return items[:10]


def leaderboard_table(items, limit=50):
    lines = [
        "| # | Project 项目 | ⭐ Stars | Language 语言 | First seen 首次收录 |",
        "|---|---|---|---|---|",
    ]
    for i, t in enumerate(items[:limit], 1):
        desc = f" — {t['desc']}" if t["desc"] else ""
        lines.append(
            f"| {i} | [{t['name']}]({t['url']}){desc} "
            f"| {t['stars']} | {t['lang']} | {t['first_seen']} |")
    return "\n".join(lines)


def render_leaderboard(data):
    tools = sorted([d for d in data if d["category"] == "tool"],
                   key=lambda x: -x["stars"])
    skills = sorted([d for d in data if d["category"] == "skill"],
                    key=lambda x: -x["stars"])
    return f"""# 🏆 Leaderboard · 排行榜

> Ranked by GitHub stars, updated daily. 按 GitHub star 数排名，每日更新。
> Last updated · 更新时间：{DATESTR}

## 🛠️ AI Tools · AI 工具

{leaderboard_table(tools) if tools else "暂无 / No data yet."}

## 🧩 AI Skills · AI 技能

{leaderboard_table(skills) if skills else "暂无 / No data yet."}
"""


def render_categories(data):
    """按功能分类展示所有收录项目（中英双语）。"""
    groups = {k: [] for k, _, _ in CATEGORIES}
    for d in data:
        tag = (d.get("tags") or ["other"])[0]
        groups.setdefault(tag, groups["other"]).append(d)
    for items in groups.values():
        items.sort(key=lambda x: -x["stars"])
    lines = [
        "# 🗂️ Categories · 分类浏览",
        "",
        "> 按功能分类展示所有收录的 AI 工具与 Skills，中英双语。",
        "> Browse all collected AI tools and skills by category, bilingual.",
        f"> Last updated · 更新时间：{DATESTR}",
        "",
    ]
    for key, en, zh in CATEGORIES:
        items = groups.get(key, [])
        if not items:
            continue
        lines.append(f"## {en} · {zh}")
        lines.append("")
        lines.append("| Project 项目 | ⭐ Stars | Language 语言 | First seen 首次收录 |")
        lines.append("|---|---|---|---|")
        for t in items:
            desc = f" — {t['desc']}" if t["desc"] else ""
            lines.append(
                f"| [{t['name']}]({t['url']}){desc} "
                f"| {t['stars']} | {t['lang']} | {t['first_seen']} |")
        lines.append("")
    return "\n".join(lines)


def render_digest(tools, hn_items, skills):
    lines = [
        f"# 📰 AI 工具日报 / AI Tools Daily — {DATESTR}",
        "",
        "> 每天自动搜集广受好评的 AI 工具与 AI Skills。",
        "> Daily auto-collection of highly-rated AI tools and AI skills.",
        "> 数据来源 / Sources: GitHub、Hacker News。",
        "",
        "## 🔥 GitHub 热门 AI 项目 / Trending AI Projects",
        "",
    ]
    if tools:
        for t in tools:
            desc = f" — {t['desc']}" if t["desc"] else ""
            lines.append(
                f"- [{t['name']}]({t['url']}){desc} "
                f"⭐ {t['stars']} · {t['lang']}")
    else:
        lines.append("今日暂无新增热门项目。/ No new trending projects today.")
    lines += ["", "## 💬 Hacker News 热议 / Hot on HN", ""]
    if hn_items:
        for h in hn_items:
            lines.append(
                f"- [{h['title']}]({h['url']}) — "
                f"{h['points']} points · {h['comments']} comments")
    else:
        lines.append("今日暂无高分讨论。/ No hot discussions today.")
    lines += ["", "## 🧩 新增 AI Skills / New AI Skills", ""]
    if skills:
        for s in skills:
            desc = f" — {s['desc']}" if s["desc"] else ""
            lines.append(
                f"- [{s['name']}]({s['url']}){desc} ⭐ {s['stars']}")
    else:
        lines.append("今日暂无新增 Skill。/ No new skills today.")
    lines += [
        "",
        "## 📊 今日统计 / Today's stats",
        "",
        f"- GitHub 新增收录 / New projects: {len(tools)}",
        f"- HN 热议 / HN discussions: {len(hn_items)}",
        f"- 新增 Skills / New skills: {len(skills)}",
        "",
    ]
    return "\n".join(lines)


def top_preview(data, category, n=10):
    items = sorted([d for d in data if d["category"] == category],
                   key=lambda x: -x["stars"])[:n]
    if not items:
        return "暂无 / No data yet."
    lines = ["| # | Project | ⭐ |", "|---|---|---|"]
    for i, t in enumerate(items, 1):
        lines.append(f"| {i} | [{t['name']}]({t['url']}) | {t['stars']} |")
    return "\n".join(lines)


def render_readmes(data, days):
    latest = days[0] if days else None
    archive_en = "\n".join(f"- [{d}](daily/{d}.md)" for d in days[:30]) or "None yet."
    archive_zh = "\n".join(f"- [{d}](daily/{d}.md)" for d in days[:30]) or "暂无。"
    latest_en = f"- [{latest}](daily/{latest}.md)" if latest else "None yet."
    latest_zh = f"- [{latest}](daily/{latest}.md)" if latest else "暂无。"

    readme_en = f"""# ai-tools-daily

> [中文版](README.zh-CN.md)

Daily auto-collection of **highly-rated AI tools** and **AI skills**, with a Chinese/English daily digest.

- **Sources**: GitHub (high-star new AI projects from the last 2 days), Hacker News (top discussions)
- **Updated**: daily at 08:00 (Beijing time, UTC+8)
- **Dedup**: already-featured projects won't appear again

## 🏆 Leaderboard (Top 10)

Full ranking: [LEADERBOARD.md](LEADERBOARD.md) (bilingual · 中英双语)\n\nBrowse by category: [CATEGORIES.md](CATEGORIES.md) (bilingual · 中英双语)

### 🛠️ Top AI Tools

{top_preview(data, "tool")}

### 🧩 Top AI Skills

{top_preview(data, "skill")}

## 📰 Latest digest

{latest_en}

## 📚 Archive

{archive_en}
"""

    readme_zh = f"""# ai-tools-daily · AI 工具日报

> [English version](README.md)

每天自动搜集**广受好评的 AI 工具**与 **AI Skills**，生成中英双语日报。

- **数据来源**：GitHub（近 2 天高 star 新项目）、Hacker News（高分讨论）
- **更新时间**：每天 08:00（北京时间）自动运行
- **去重**：已收录过的项目不会重复出现

## 🏆 排行榜（Top 10）

完整榜单：[LEADERBOARD.md](LEADERBOARD.md)（中英双语）\n\n按分类浏览：[CATEGORIES.md](CATEGORIES.md)（中英双语）

### 🛠️ AI 工具 Top

{top_preview(data, "tool")}

### 🧩 AI Skills Top

{top_preview(data, "skill")}

## 📰 最新日报

{latest_zh}

## 📚 历史归档

{archive_zh}
"""
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme_en)
    with open(os.path.join(ROOT, "README.zh-CN.md"), "w", encoding="utf-8") as f:
        f.write(readme_zh)


def main():
    os.makedirs(DAILY_DIR, exist_ok=True)
    seen = load_seen()
    data = load_data()

    backfill_data(seen, data)

    new_tools = collect_github_tools(seen)
    new_skills = collect_skills(seen)
    hn_items = collect_hn(seen)

    known_urls = {d["url"] for d in data}
    for item in new_tools + new_skills:
        if item["url"] not in known_urls:
            data.append(item)
            known_urls.add(item["url"])

    refresh_stars(data)
    save_data(data)
    save_seen(seen)

    with open(os.path.join(ROOT, "LEADERBOARD.md"), "w", encoding="utf-8") as f:
        f.write(render_leaderboard(data))

    with open(os.path.join(ROOT, "CATEGORIES.md"), "w", encoding="utf-8") as f:
        f.write(render_categories(data))

    digest = render_digest(new_tools, hn_items, new_skills)
    with open(os.path.join(DAILY_DIR, f"{DATESTR}.md"), "w", encoding="utf-8") as f:
        f.write(digest)

    days = sorted(
        (f[:-3] for f in os.listdir(DAILY_DIR) if f.endswith(".md")),
        reverse=True,
    )
    render_readmes(data, days)
    print(f"done {DATESTR}: new_tools={len(new_tools)} new_skills={len(new_skills)} "
          f"hn={len(hn_items)} total_tracked={len(data)}")


if __name__ == "__main__":
    main()
