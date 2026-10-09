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
    ("agent", "\U0001F916", "AI Agent", "智能体"),
    ("coding", "\U0001F4BB", "Coding", "编程开发"),
    ("image-video", "\U0001F3A8", "Image & Video", "图像视频"),
    ("audio", "\U0001F399", "Audio & Voice", "音频语音"),
    ("writing", "\u270D\uFE0F", "Writing", "写作"),
    ("search", "\U0001F50D", "Search & Knowledge", "搜索知识"),
    ("devtools", "\U0001F6E0\uFE0F", "Dev Tools", "开发工具"),
    ("data", "\U0001F4CA", "Data & Analysis", "数据分析"),
    ("chat", "\U0001F4AC", "Chat & Assistant", "对话助手"),
    ("other", "\U0001F4E6", "Other", "其他"),
]

# 功能分类（agent 除外）：topics 映射与关键词
TOPIC_MAP = {
    "code": "coding", "coding": "coding", "programming": "coding",
    "code-review": "coding",
    "image": "image-video", "images": "image-video", "video": "image-video",
    "animation": "image-video", "motion-graphics": "image-video",
    "text-to-image": "image-video", "3d": "image-video", "ppt": "image-video",
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
AGENT_TOPICS = {
    "ai-agents", "agent", "agents", "autonomous-agents", "multi-agent",
    "agent-framework",
}

KEYWORDS = {
    "coding": ["code", "coding", "programmer", "developer", "ide", "debug",
               "refactor", "pull request", "readme"],
    "image-video": ["video", "image", "motion graphic", "animation",
                    "drawing", "painting", "photo", "flip book", "ppt",
                    "slide", "3d"],
    "audio": ["audio", "voice", "speech", "podcast", "music", "sound"],
    "writing": ["writing", "write", "blog", "copywriting", "essay",
                "study page", "novel"],
    "search": ["search", "rag", "knowledge", "retrieval"],
    "devtools": ["devtool", "cli", "terminal", "adb", "deploy",
                 "control", "pipeline", "automation"],
    "data": ["data analysis", "dashboard", "chart", "insight"],
    "chat": ["chatbot", "companion", "conversation"],
}
AGENT_PHRASES = [
    "autonomous agent", "multi-agent", "ai agent", "agent framework",
    "agent system", "vlm agent", "agent",
]
# 客户端名称只是载体，不代表功能，匹配前去掉
CLIENT_NAMES = re.compile(
    r"\b(claude code|codex|opencode|open code|cursor|windsurf|kilocode)\b")

FUNCTIONAL = ["coding", "image-video", "audio", "writing", "search",
              "devtools", "data", "chat"]


def _norm_topics(topics):
    return [(t or "").lower().replace("_", "-") for t in (topics or [])]


def _kw_hit(text, words):
    for w in words:
        if re.search(r"\b" + re.escape(w) + r"s?\b", text):
            return True
    return False


def ensure_zh_desc(items):
    """中文描述由助手直接翻译（不再调用第三方机翻）。
    这里只保证字段存在，缺失的由每日翻译任务补齐。"""
    for d in items:
        if "desc_zh" not in d:
            d["desc_zh"] = ""


def categorize(name, desc, topics):
    """先按功能分类（topics 优先、关键词兜底），都不中再看是否为智能体，
    最后归入其他。"""
    text = CLIENT_NAMES.sub(" ", f"{name} {desc}".lower())
    norm = _norm_topics(topics)
    # pass 1: 功能分类 by topics
    for t in norm:
        if t in TOPIC_MAP:
            return TOPIC_MAP[t]
    # pass 2: 功能分类 by 关键词
    for cat in FUNCTIONAL:
        if _kw_hit(text, KEYWORDS[cat]):
            return cat
    # pass 3: 智能体
    if any(t in AGENT_TOPICS for t in norm):
        return "agent"
    if _kw_hit(text, AGENT_PHRASES):
        return "agent"
    return "other"


def repo_entry(r, category, first_seen):
    topics = r.get("topics", []) or []
    desc = clean_desc(r.get("description"))
    return {
        "name": r["full_name"],
        "url": r["html_url"],
        "desc": desc,
        "stars": r.get("stargazers_count", 0),
        "stars_prev": r.get("stargazers_count", 0),
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
            d["stars_prev"] = d.get("stars", 0)
            d["stars"] = r.get("stargazers_count", d["stars"])
            d["lang"] = r.get("language") or d["lang"]
            if r.get("description"):
                d["desc"] = clean_desc(r.get("description"))
            d["tags"] = [categorize(d["name"], d.get("desc", ""),
                                   r.get("topics", []) or [])]
            ok += 1
        except Exception:
            fail += 1
    print(f"star refresh: ok={ok} fail={fail}")


def is_quality_repo(r):
    """质量过滤：剔除归档、fork、禁用、无有效描述的仓库。"""
    if r.get("archived") or r.get("fork") or r.get("disabled"):
        return False
    desc = (r.get("description") or "").strip()
    if len(desc) < 15:
        return False
    return True


AI_TERMS = re.compile(
    r"\b(ai|artificial intelligence|llm|gpt|llama|mistral|gemini|Muse|"
    r"machine learning|deep learning|neural|diffusion|transformer|"
    r"agent|agents|mcp|rag|embedding|vector|tts|stt|text-to-image|"
    r"text-to-speech|speech-to-text|chatbot|copilot|"
    r"openai|anthropic|huggingface)\b", re.I)


def is_ai_relevant(r):
    """AI 相关性过滤：名称/描述/topics 至少命中一个 AI 相关词。"""
    text = f"{r.get('full_name','')} {r.get('description','')} {' '.join(r.get('topics') or [])}"
    return bool(AI_TERMS.search(text))


# 回填配置：库中条目少于此数时，触发一次 90 天窗口的大扫荡
BACKFILL_MIN_ENTRIES = 80
BACKFILL_DAYS = 90
# (搜索词, 最低 star)
BACKFILL_QUERIES = [
    ("artificial intelligence", 100),
    ("ai agent", 50),
    ("llm application", 50),
    ("mcp server", 20),
    ("ai coding", 50),
    ("ai image generation", 50),
    ("ai video generation", 30),
    ("ai chatbot", 50),
    ("rag", 50),
    ("ai voice", 30),
    ("text-to-speech ai", 30),
    ("ai writing assistant", 30),
    ("claude skill", 10),
    ("agent skill", 10),
]


def collect_github_tools(seen):
    queries = [
        f"ai agent stars:>30 created:>{SINCE}",
        f"llm tool stars:>30 created:>{SINCE}",
        f"mcp stars:>10 created:>{SINCE}",
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
            if url in seen or not is_quality_repo(r) or not is_ai_relevant(r):
                continue
            seen[url] = DATESTR
            items.append(repo_entry(r, "tool", DATESTR))
    items.sort(key=lambda x: -x["stars"])
    return items[:20]


def collect_backfill(seen):
    """一次性回填：90 天窗口、多查询扫荡，把项目库撑到 100+。
    只进 data.json，不进当日日报。库条目数达标后自动停止触发。"""
    since = (NOW - timedelta(days=BACKFILL_DAYS)).strftime("%Y-%m-%d")
    items = []
    for term, min_stars in BACKFILL_QUERIES:
        q = f"{term} stars:>{min_stars} created:>{since}"
        try:
            data = gh_get("/search/repositories?" + urllib.parse.urlencode(
                {"q": q, "sort": "stars", "order": "desc", "per_page": 30}))
        except Exception as e:
            print(f"backfill search failed ({q}): {e}")
            continue
        n = 0
        for r in data.get("items", []):
            url = r["html_url"]
            if url in seen or not is_quality_repo(r) or not is_ai_relevant(r):
                continue
            seen[url] = DATESTR
            desc = (r.get("description") or "").lower()
            category = "skill" if "skill" in r["full_name"].lower() or "skill" in desc else "tool"
            items.append(repo_entry(r, category, DATESTR))
            n += 1
        print(f"backfill '{term}': +{n}")
    items.sort(key=lambda x: -x["stars"])
    print(f"backfill total: {len(items)}")
    return items


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
            if url in seen or not is_quality_repo(r) or not is_ai_relevant(r):
                continue
            seen[url] = DATESTR
            items.append(repo_entry(r, "skill", DATESTR))
    items.sort(key=lambda x: -x["stars"])
    return items[:10]


def _show_desc(t):
    d = t.get("desc_zh") or t.get("desc") or ""
    return f" — {d}" if d else ""


def leaderboard_table(items, limit=50):
    lines = [
        "| # | Project 项目 | ⭐ Stars | Language 语言 | First seen 首次收录 |",
        "|---|---|---|---|---|",
    ]
    for i, t in enumerate(items[:limit], 1):
        desc = _show_desc(t)
        lines.append(
            f"| {i} | [{t['name']}]({t['url']}){desc} "
            f"| {t['stars']} | {t['lang']} | {t['first_seen']} |")
    return "\n".join(lines)


def render_leaderboard(data):
    tools = sorted([d for d in data if d["category"] == "tool"],
                   key=lambda x: -x["stars"])
    skills = sorted([d for d in data if d["category"] == "skill"],
                    key=lambda x: -x["stars"])
    gainers = [d for d in data
               if d.get("stars", 0) - d.get("stars_prev", d.get("stars", 0)) > 0]
    gainers.sort(key=lambda x: -(x["stars"] - x.get("stars_prev", x["stars"])))
    tlines = ["| # | Project 项目 | ⭐ Stars | 📈 24h 涨幅 |",
              "|---|---|---|---|"]
    for i, g in enumerate(gainers[:10], 1):
        gain = g["stars"] - g.get("stars_prev", g["stars"])
        tlines.append(f"| {i} | [{g['name']}]({g['url']}) | {g['stars']} | +{gain} |")
    trending = ("\n".join(tlines) if gainers
                else "暂无 / No data yet (needs 2 days of history).")
    return f"""# 🏆 Leaderboard · 排行榜

> Ranked by GitHub stars, updated daily. 按 GitHub star 数排名，每日更新。
> Last updated · 更新时间：{DATESTR}

## 📈 Trending Up · 涨幅最快

> 过去 24 小时 star 增长最多 · Biggest star gains in the last 24 hours.

{trending}

## 🛠️ AI Tools · AI 工具

{leaderboard_table(tools) if tools else "暂无 / No data yet."}

## 🧩 AI Skills · AI 技能

{leaderboard_table(skills) if skills else "暂无 / No data yet."}
"""


def render_categories(data):
    """按功能分类展示所有收录项目（中英双语）。"""
    groups = {k: [] for k, _, _, _ in CATEGORIES}
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
    for key, emoji, en, zh in CATEGORIES:
        items = groups.get(key, [])
        if not items:
            continue
        lines.append(f'## <a id="{key}"></a>{emoji} {en} · {zh}')
        lines.append("")
        lines.append("| Project 项目 | ⭐ Stars | Language 语言 | First seen 首次收录 |")
        lines.append("|---|---|---|---|")
        for t in items:
            desc = _show_desc(t)
            lines.append(
                f"| [{t['name']}]({t['url']}){desc} "
                f"| {t['stars']} | {t['lang']} | {t['first_seen']} |")
        lines.append("")
    return "\n".join(lines)


def _item_line_zh(t):
    d = t.get("desc_zh") or t.get("desc") or ""
    d = f" — {d}" if d else ""
    return f"- [{t['name']}]({t['url']}){d} ⭐ {t['stars']} · {t['lang']}"


def _item_line_en(t):
    d = f" — {t['desc']}" if t.get("desc") else ""
    return f"- [{t['name']}]({t['url']}){d} ⭐ {t['stars']} · {t['lang']}"


def render_digest_zh(tools, hn_items, skills):
    lines = [
        f"# 📰 AI 工具日报 {DATESTR}",
        "",
        "> 每天自动搜集广受好评的 AI 工具与 AI Skills。",
        "> 数据来源：GitHub、Hacker News。",
        "",
        "## 🔥 GitHub 热门 AI 项目",
        "",
    ]
    lines += [_item_line_zh(t) for t in tools] or ["今日暂无新增热门项目。"]
    lines += ["", "## 💬 Hacker News 热议", ""]
    if hn_items:
        for h in hn_items:
            lines.append(
                f"- [{h['title']}]({h['url']}) — "
                f"{h['points']} points · {h['comments']} comments")
    else:
        lines.append("今日暂无高分讨论。")
    lines += ["", "## 🧩 新增 AI Skills", ""]
    lines += [_item_line_zh(s) for s in skills] or ["今日暂无新增 Skill。"]
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


def render_digest_en(tools, hn_items, skills):
    lines = [
        f"# 📰 AI Tools Daily {DATESTR}",
        "",
        "> Daily auto-collection of highly-rated AI tools and AI skills.",
        "> Sources: GitHub, Hacker News.",
        "",
        "## 🔥 Trending AI Projects on GitHub",
        "",
    ]
    lines += [_item_line_en(t) for t in tools] or ["No new trending projects today."]
    lines += ["", "## 💬 Hot on Hacker News", ""]
    if hn_items:
        for h in hn_items:
            lines.append(
                f"- [{h['title']}]({h['url']}) — "
                f"{h['points']} points · {h['comments']} comments")
    else:
        lines.append("No hot discussions today.")
    lines += ["", "## 🧩 New AI Skills", ""]
    lines += [_item_line_en(s) for s in skills] or ["No new skills today."]
    lines += [
        "",
        "## 📊 Today's stats",
        "",
        f"- New GitHub projects: {len(tools)}",
        f"- HN discussions: {len(hn_items)}",
        f"- New skills: {len(skills)}",
        "",
    ]
    return "\n".join(lines)


def top_preview(data, category, n=10, lang="en"):
    items = sorted([d for d in data if d["category"] == category],
                   key=lambda x: -x["stars"])[:n]
    if not items:
        return "暂无。" if lang == "zh" else "No data yet."
    head = "| # | 项目 | ⭐ |" if lang == "zh" else "| # | Project | ⭐ |"
    lines = [head, "|---|---|---|"]
    for i, t in enumerate(items, 1):
        lines.append(f"| {i} | [{t['name']}]({t['url']}) | {t['stars']} |")
    return "\n".join(lines)


def _cat_counts(data):
    counts = {}
    for d in data:
        tag = (d.get("tags") or ["other"])[0]
        counts[tag] = counts.get(tag, 0) + 1
    return counts


def _cat_grid(counts, lang="en"):
    """分类导航九宫格（HTML 表格，每行 5 个）。"""
    cells = []
    for key, emoji, en, zh in CATEGORIES:
        n = counts.get(key, 0)
        if lang == "zh":
            label = f"<b>{zh}</b><br/><sub>{en} · {n}</sub>"
        else:
            label = f"<b>{en}</b><br/><sub>{zh} · {n}</sub>"
        cells.append(
            f'<td align="center" width="20%">'
            f'<a href="CATEGORIES.md#{key}">{emoji}<br/>{label}</a></td>')
    rows = []
    for i in range(0, len(cells), 5):
        rows.append("  <tr>\n    " + "\n    ".join(cells[i:i + 5]) + "\n  </tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def _badges():
    return (
        '<p>\n'
        '  <img src="https://img.shields.io/badge/updated-daily-brightgreen" alt="updated daily" />\n'
        '  <img src="https://img.shields.io/badge/bilingual-EN_/_\u4e2d\u6587-blue" alt="bilingual" />\n'
        '  <img src="https://img.shields.io/badge/automated-GitHub_Actions-orange" alt="automated" />\n'
        '</p>')


def render_readmes(data, days):
    counts = _cat_counts(data)
    total = len(data)
    grid = _cat_grid(counts, "en")
    grid_zh = _cat_grid(counts, "zh")
    badges = _badges()
    latest = days[0] if days else None
    archive_items = "\n".join(f"- [{d}](daily/{d}.md)" for d in days[:60])
    latest_link = f"[**{latest}**](daily/{latest}.en.md)" if latest else "None yet."
    latest_link_zh = f"[**{latest}**](daily/{latest}.md)" if latest else "暂无。"

    readme_en = f"""<div align="center">
  <h1>\U0001F916 ai-tools-daily</h1>
  <p><b>Discover the best AI tools & skills, every single day</b></p>
{badges}
  <p><a href="README.zh-CN.md"><b>\u4e2d\u6587</b></a> · <b>English</b></p>
</div>

---

Daily auto-collection of **highly-rated AI tools** and **AI skills**.

- \U0001F50D **Sources**: GitHub (high-star new AI projects from the last 2 days), Hacker News (top discussions)
- ⏰ **Updated**: daily at 08:00 (Beijing time, UTC+8) — {total} projects tracked
- \U0001F9F9 **Dedup**: featured projects never appear twice

## \U0001F9ED Browse by Category

{grid}

## \U0001F3C6 Leaderboard · Top 10

> Full ranking: [LEADERBOARD.md](LEADERBOARD.md)

### \U0001F6E0\uFE0F Top AI Tools

{top_preview(data, "tool")}

### \U0001F9E9 Top AI Skills

{top_preview(data, "skill")}

## \U0001F4F0 Latest Digest

> ### {latest_link}

<details>
<summary><b>\U0001F4DA Archive</b></summary>

{archive_items or "None yet."}

</details>

---

<sub>\U0001F916 Fully automated by <a href=".github/workflows/daily.yml">GitHub Actions</a> · Data from GitHub & Hacker News public APIs</sub>
"""

    readme_zh = f"""<div align="center">
  <h1>\U0001F916 ai-tools-daily · AI 工具日报</h1>
  <p><b>每天发现最值得关注的 AI 工具与 Skills</b></p>
{badges}
  <p><b>\u4e2d\u6587</b> · <a href="README.md"><b>English</b></a></p>
</div>

---

每天自动搜集**广受好评的 AI 工具**与 **AI Skills**。

- \U0001F50D **数据来源**：GitHub（近 2 天高 star 新项目）、Hacker News（高分讨论）
- ⏰ **更新时间**：每天 08:00（北京时间）自动运行 — 已收录 {total} 个项目
- \U0001F9F9 **去重**：收录过的项目不会重复出现

## \U0001F9ED 分类浏览

{grid_zh}

## \U0001F3C6 排行榜 · Top 10

> 完整榜单：[LEADERBOARD.md](LEADERBOARD.md)

### \U0001F6E0\uFE0F AI 工具 Top

{top_preview(data, "tool")}

### \U0001F9E9 AI Skills Top

{top_preview(data, "skill")}

## \U0001F4F0 最新日报

> ### {latest_link_zh}

<details>
<summary><b>\U0001F4DA 历史归档</b></summary>

{archive_items or "暂无。"}

</details>

---

<sub>\U0001F916 由 <a href=".github/workflows/daily.yml">GitHub Actions</a> 全自动运行 · 数据来自 GitHub 与 Hacker News 公开 API</sub>
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

    # 回填：库太小时做一次 90 天大扫荡（只进 data.json，不进当日日报）
    backfilled = []
    if len(data) < BACKFILL_MIN_ENTRIES:
        print(f"data has {len(data)} entries < {BACKFILL_MIN_ENTRIES}, running backfill...")
        backfilled = collect_backfill(seen)

    known_urls = {d["url"] for d in data}
    for item in new_tools + new_skills + backfilled:
        if item["url"] not in known_urls:
            data.append(item)
            known_urls.add(item["url"])

    refresh_stars(data)
    ensure_zh_desc(data)
    save_data(data)
    save_seen(seen)

    with open(os.path.join(ROOT, "LEADERBOARD.md"), "w", encoding="utf-8") as f:
        f.write(render_leaderboard(data))

    with open(os.path.join(ROOT, "CATEGORIES.md"), "w", encoding="utf-8") as f:
        f.write(render_categories(data))

    with open(os.path.join(DAILY_DIR, f"{DATESTR}.md"), "w", encoding="utf-8") as f:
        f.write(render_digest_zh(new_tools, hn_items, new_skills))
    with open(os.path.join(DAILY_DIR, f"{DATESTR}.en.md"), "w", encoding="utf-8") as f:
        f.write(render_digest_en(new_tools, hn_items, new_skills))

    days = sorted(
        (f[:-3] for f in os.listdir(DAILY_DIR) if f.endswith(".md")),
        reverse=True,
    )
    render_readmes(data, days)
    print(f"done {DATESTR}: new_tools={len(new_tools)} new_skills={len(new_skills)} "
          f"hn={len(hn_items)} backfilled={len(backfilled)} total_tracked={len(data)}")


if __name__ == "__main__":
    main()
