#!/usr/bin/env python3
"""Generate GitHub stats and top-languages SVG cards from the GitHub GraphQL API.

Usage: GITHUB_TOKEN=... python3 scripts/stats.py <username> <out_dir> [excluded,repos]
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from html import escape

API = "https://api.github.com/graphql"

BG = "#0b1628"
BORDER = "#1f3354"
ACCENT = "#4f8ef7"
GREEN = "#7ee787"
TEXT = "#e6edf3"
MUTED = "#8b949e"
HIDDEN_LANGS = {"HTML", "CSS", "SCSS", "Blade", "Mustache", "Vue", "Hack"}
FONT = "'JetBrains Mono','Fira Code',Consolas,monospace"


def gql(query, variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch(user):
    repos, cursor = [], None
    while True:
        data = gql(
            """
            query($login: String!, $cursor: String) {
              user(login: $login) {
                createdAt
                followers { totalCount }
                contributionsCollection { contributionYears }
                pullRequests { totalCount }
                issues { totalCount }
                repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100, after: $cursor) {
                  totalCount
                  pageInfo { hasNextPage endCursor }
                  nodes {
                    name
                    stargazerCount
                    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                      edges { size node { name color } }
                    }
                  }
                }
              }
            }""",
            {"login": user, "cursor": cursor},
        )["user"]
        repos += data["repositories"]["nodes"]
        page = data["repositories"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    commits = 0
    for year in data["contributionsCollection"]["contributionYears"]:
        c = gql(
            """
            query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                  totalCommitContributions
                  restrictedContributionsCount
                }
              }
            }""",
            {"login": user, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]

    return data, repos, commits


def card(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <style>
    text {{ font-family: {FONT}; }}
    .title {{ font-size: 16px; font-weight: 700; fill: {ACCENT}; }}
    .label {{ font-size: 13px; fill: {MUTED}; }}
    .value {{ font-size: 15px; font-weight: 700; fill: {TEXT}; }}
    .row {{ opacity: 0; animation: in .45s ease-out forwards; }}
    @keyframes in {{ from {{ opacity: 0; transform: translateX(-8px); }} to {{ opacity: 1; transform: none; }} }}
    .bar {{ transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow .9s ease-out forwards; }}
    @keyframes grow {{ to {{ transform: scaleX(1); }} }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>
  <text class="title" x="24" y="36">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(user_data, repos, commits):
    years = datetime.now(timezone.utc).year - int(user_data["createdAt"][:4])
    rows = [
        ("★", "Total stars", sum(r["stargazerCount"] for r in repos)),
        ("⎇", "Total commits", commits),
        ("⇄", "Pull requests", user_data["pullRequests"]["totalCount"]),
        ("!", "Issues", user_data["issues"]["totalCount"]),
        ("▣", "Public repositories", user_data["repositories"]["totalCount"]),
        ("◉", "Followers", user_data["followers"]["totalCount"]),
    ]
    body = []
    for i, (icon, label, value) in enumerate(rows):
        y = 72 + i * 27
        body.append(
            f'  <g class="row" style="animation-delay:{0.15 * i:.2f}s">'
            f'<text x="24" y="{y}" style="font-size:14px;fill:{GREEN}">{icon}</text>'
            f'<text class="label" x="48" y="{y}">{label}</text>'
            f'<text class="value" x="396" y="{y}" text-anchor="end">{value:,}</text></g>'
        )
    body.append(
        f'  <text x="24" y="{72 + len(rows) * 27 + 6}" style="font-size:11px;fill:#5b6b85">'
        f"on GitHub for {years}+ years · updated {datetime.now(timezone.utc):%Y-%m-%d}</text>"
    )
    return card(420, 260, "GitHub Stats", "\n".join(body))


def langs_svg(repos, excluded, limit=8):
    totals, colors = {}, {}
    for r in repos:
        if r["name"] in excluded:
            continue
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            if name in HIDDEN_LANGS:
                continue
            totals[name] = totals.get(name, 0) + e["size"]
            colors[name] = e["node"]["color"] or ACCENT
    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    grand = sum(v for _, v in top) or 1
    body = []
    for i, (name, size) in enumerate(top):
        y = 66 + i * 23
        pct = size / grand * 100
        bar_w = max(2.0, 180 * pct / 100)
        body.append(
            f'  <g class="row" style="animation-delay:{0.1 * i:.2f}s">'
            f'<circle cx="30" cy="{y - 4}" r="5" fill="{colors[name]}"/>'
            f'<text class="label" x="44" y="{y}" style="fill:{TEXT}">{escape(name)}</text>'
            f'<rect x="170" y="{y - 10}" width="180" height="8" rx="4" fill="{BORDER}"/>'
            f'<rect class="bar" style="animation-delay:{0.3 + 0.1 * i:.2f}s" x="170" y="{y - 10}" '
            f'width="{bar_w:.1f}" height="8" rx="4" fill="{colors[name]}"/>'
            f'<text class="label" x="396" y="{y}" text-anchor="end">{pct:.1f}%</text></g>'
        )
    return card(420, 260, "Top Languages", "\n".join(body))


def main():
    user, out = sys.argv[1], sys.argv[2]
    excluded = set(filter(None, (sys.argv[3] if len(sys.argv) > 3 else "").split(",")))
    user_data, repos, commits = fetch(user)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "stats.svg"), "w") as f:
        f.write(stats_svg(user_data, repos, commits))
    with open(os.path.join(out, "top-langs.svg"), "w") as f:
        f.write(langs_svg(repos, excluded))
    print(f"wrote stats.svg and top-langs.svg to {out}")


if __name__ == "__main__":
    main()
