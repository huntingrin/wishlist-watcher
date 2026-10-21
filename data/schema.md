# 状态 schema v1

状态文件默认：`~/.wishlist-watcher/watchlist.json`

所有价格都是**整数分**，避免浮点误差。时间使用带时区的 ISO 8601 字符串。

```json
{
  "version": 1,
  "onboarded_at": "2026-10-21T13:40:00+08:00",
  "items": [
    {
      "id": "w_627211cae00a",
      "status": "active",
      "created_at": "2026-10-21T13:42:46+08:00",
      "input": {
        "raw": "索尼 A7C2",
        "type": "keyword"
      },
      "product": {
        "candidate_id": "b68d96afba89",
        "title": "索尼（SONY）A7C2 全画幅微单…",
        "url": "https://…",
        "image": "https://…",
        "mall": "京东",
        "shop": "索尼（SONY）影像京东自营专区",
        "brand": "索尼（SONY）",
        "search_query": "索尼 A7C2",
        "price_cents": 853145,
        "page_price_cents": 1012900,
        "price_tags": [
          {"title": "历史最低", "price_cents": 860965}
        ],
        "historical_low_cents": 860965,
        "low_30d_cents": 860965,
        "usual_price_cents": 1078300,
        "promo_price_cents": 1151220,
        "below_promo": true
      },
      "target_price_cents": 800000,
      "deadline": "2026-11-11",
      "created_price_cents": 853145,
      "lowest_seen_cents": 853145,
      "last_price_cents": 853145,
      "last_checked_at": "2026-10-21T13:42:49+08:00",
      "last_alert_at": null,
      "last_alert_price_cents": null,
      "snooze_until": null,
      "needs_review": false,
      "feedback": [],
      "checks": [
        {
          "checked_at": "2026-10-21T13:42:49+08:00",
          "price_cents": 853145,
          "page_price_cents": 1012900,
          "title": "索尼（SONY）A7C2 全画幅微单…",
          "mall": "京东",
          "shop": "索尼（SONY）影像京东自营专区",
          "url": "https://…",
          "match_score": 1.0,
          "match_status": "matched",
          "trigger": false,
          "reason": "not_met"
        }
      ]
    }
  ]
}
```

## 字段说明

| 字段 | 说明 |
|---|---|
| `version` | schema 版本，当前 1 |
| `onboarded_at` | 首次使用说明展示时间；为空表示还没展示 |
| `status` | `active` / `bought` / `expired` |
| `product.search_query` | 建档时的搜索词；后续 check 用它重新召回 |
| `product.candidate_id` | 商品标题+平台+店铺的稳定哈希，用于优先匹配 |
| `target_price_cents` | 用户目标到手价（分） |
| `lowest_seen_cents` | 本 Skill 观察到的到手价最低值（分） |
| `last_alert_at` | 上次提醒时间，用于 24h 冷却 |
| `snooze_until` | “再等等”截止时间 |
| `needs_review` | 用户反馈“不准”后标记 |
| `checks` | 最近 90 次检查，超过自动裁剪 |

## 兼容性

- 状态是普通 JSON，UTF-8，无数据库依赖。
- 换 Agent/换会话只要 `--state-dir` 指向同一目录即可恢复。
- 写入使用临时文件 + `os.replace`，避免半写坏文件。
- 当前是单用户本地状态，不做并发写锁；不要让两个进程同时 `check` 同一个状态目录。

## 待选候选

两步建档时，`pending-add.json` 保存上一次 `add` 返回的候选列表，避免用户确认序号后重新搜索导致顺序变化。成功建档后自动删除；它不包含 API Key。

## 代理配置

`proxy.json` 只在内测代理模式存在，保存代理 URL 和邀请 token，权限 0600。它不是监控状态的一部分，不会提交到仓库；`watch.py logout` 会删除它。
