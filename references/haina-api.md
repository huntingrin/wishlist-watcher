# 海纳 API 参考

本 Skill 只调用两个海纳接口：

| 用途 | 方法 | 地址 |
|---|---|---|
| 商品检索 + 价格/历史标签 | POST | `https://gw-openapi.zhidemai.com/product/v1` |
| 好价/优惠/购买步骤 | POST | `https://gw-openapi.zhidemai.com/hj-search/discount/v2` |

## 鉴权

请求头：

```http
x-api-key: <HAINA_API_KEY>
Content-Type: application/json
```

Key 只从环境变量 `HAINA_API_KEY` 读取；本地也可放在 `~/.wishlist-watcher/.env.local`。不要写进 Skill 目录、状态文件、日志或对话。

## 商品检索 Pro

### 请求

```json
{
  "product_query": "索尼 A7C2",
  "request_from": "wishlist-watcher",
  "question_id": "唯一请求 ID",
  "query_process": 1,
  "size": 10
}
```

必填：`product_query`、`request_from`、`question_id`。

可选：

- `query_process`：是否做 query 处理，默认 1。
- `size`：返回商品数，最大 20。
- `mall_id`、`brand_name`、`category_name`、`min_price`、`max_price`、`sort`、`fields`。

**只接受关键词，不接受商品 URL。** 链接输入需要先转成商品名/型号，或由用户补充商品名。

### 响应（节选）

```json
{
  "error_code": 0,
  "error_msg": "Success",
  "data": {
    "rows": [
      {
        "title": "索尼（SONY）A7C2 全画幅微单相机…",
        "url": "https://…",
        "main_picture": "https://…",
        "page_price": 10129,
        "price": "¥8531.45",
        "price_tags": [
          {"title": "常卖价", "price": "¥10783.00"},
          {"title": "历史最低", "price": "¥8609.65"},
          {"title": "30天最低", "price": "¥8609.65"},
          {"title": "618价", "price": "¥11512.20"},
          {"title": "大促价", "price": "¥11512.20"},
          {"title": "低于大促价", "price": ""}
        ],
        "mall_name": "京东",
        "brand_name": "索尼（SONY）",
        "shop_name": "索尼（SONY）影像京东自营专区"
      }
    ]
  }
}
```

### 价格口径（非常重要）

- `price`：**到手价**，用于目标价判断。
- `page_price`：**页面价**，用于展示。
- `price_tags` 里的“历史最低 / 30天最低 / 常卖价 / 大促价”：**页面价口径**，只用于展示和参考。
- **不要把 `price` 和 `price_tags` 的“历史最低”直接比较。** 到手价可能因为券/补贴低于页面价历史低点；混比会误判“创新低”。
- 自建 `lowest_seen_cents` 只记录本 Skill 观察到的到手价，用来判断“跌破自入库最低价”。

## 好价检索 Pro

### 请求

```json
{
  "product_query": "索尼 A7C2",
  "request_from": "wishlist-watcher",
  "question_id": "唯一请求 ID",
  "query_process": 1,
  "size": 5
}
```

可选 `fields` 裁剪返回字段；默认返回 5 条。

### 响应（节选）

```json
{
  "error_code": 0,
  "error_msg": "Success",
  "data": {
    "rows": [
      {
        "title": "限江浙沪粤：索尼 Alpha 7C II（A7C2）全画幅微单相机 单机身",
        "url": "https://…",
        "price": "7996.11",
        "page_price": "10699",
        "digital_price": "7996.11",
        "mall_name": "天猫精选",
        "brand_name": "SONY/索尼",
        "bl_reason": "限江浙沪粤，需叠加平台补贴",
        "product_buy_step": "领券后加购，结算页确认地区资格",
        "article_id": "184418835"
      }
    ]
  }
}
```

好价结果是**帖子/活动**，不是稳定商品主数据；同一个商品可能有多条好价。适合做提醒里的“为什么值得买”和条件说明，不适合单独作为商品 ID。

## 错误处理

| HTTP / error_code | 含义 | 处理 |
|---|---|---|
| 401 | Key 缺失/无效 | 让用户配置 `HAINA_API_KEY`，不要重试 |
| 403 | Key 未开通该能力/已失效 | 让用户到工作台开通，不要重试 |
| 422 | 参数错误 | 检查必填字段和类型 |
| 429 | 超过 QPS 或额度 | 退避重试；默认 Key 每接口 5 次/秒 |
| 502/504 | 海纳暂时不可用 | 退避重试，仍失败则如实告知 |
| `error_code != 0` | 业务错误 | 展示 `error_msg`，不编造结果 |

本 Skill 的客户端会自动对 429/5xx 做最多 2 次退避重试。

## 实测样例

2026-10-21，`product_query="索尼 A7C2"`：

- 返回 9 条商品
- 京东自营：页面价 ¥10,129，到手价 ¥8,531.45
- 页面价历史最低 ¥8,609.65，30 天最低 ¥8,609.65
- 到手价低于页面价历史最低，说明两个口径不能混比

`discount_search` 同日返回 5 条好价，第一条为天猫精选单机身 ¥7,996.11（限江浙沪粤）。

## 最小调用示例

```bash
curl -s https://gw-openapi.zhidemai.com/product/v1 \
  -H "x-api-key: $HAINA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"product_query":"索尼 A7C2","request_from":"wishlist-watcher","question_id":"demo-1","query_process":1,"size":3}'
```

但 Skill 内部统一通过 `scripts/haina.py` 调用，不要在 Skill 文档里让 Agent 直接拼 HTTP 请求。
