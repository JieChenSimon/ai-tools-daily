# Contributing · 投稿指南

[English](#english) · [中文](#chinese)

<a id="english"></a>
## English

### Suggest a tool / skill
The easiest way to contribute: [open an issue](https://github.com/JieChenSimon/ai-tools-daily/issues/new/choose) with the **Suggest a tool** template. Tell us:
- Project URL
- Why it's worth featuring (what it does, who it's for)

A maintainer will review it, and once accepted it joins the daily-tracked collection (star counts refresh daily, rankings update automatically).

### How this repo works
- `collect.py` runs daily via GitHub Actions (08:00 Beijing time).
- It collects high-star new AI projects from GitHub, hot AI discussions from Hacker News, and new AI skills.
- `data.json` is the persistent collection; `seen.json` prevents duplicates.
- Rankings (`LEADERBOARD.md`), categories (`CATEGORIES.md`), READMEs and daily digests (`daily/`) are all auto-generated. **Please don't edit generated files by hand** — change `collect.py` instead.

<a id="chinese"></a>
## 中文

### 推荐工具 / Skill
最简单的参与方式：用 **[推荐工具] 模板提一个 issue**，写清楚：
- 项目链接
- 推荐理由（它是做什么的，适合谁用）

维护者审核通过后，该项目会进入每日追踪（star 数每天刷新，排名自动更新）。

### 本仓库如何运作
- `collect.py` 每天 08:00（北京时间）由 GitHub Actions 自动运行。
- 搜集 GitHub 近 2 天高 star AI 新项目、Hacker News 高分 AI 讨论、新增 AI Skills。
- `data.json` 是累积项目库；`seen.json` 负责去重。
- 排行榜（`LEADERBOARD.md`）、分类（`CATEGORIES.md`）、首页与日报均为自动生成，**请勿手工改生成文件**，改 `collect.py` 即可。
