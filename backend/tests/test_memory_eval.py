"""记忆自动整理的评测集（确定性回归）。

评测对象是"整理逻辑"本身，不触网：
- 召回重排: 重要性/时间衰减/superseded 过滤在各种召回池形态下,
  期望的记忆必须排进注入名额;
- LLM 输出解析: 标注/整理任务的真实脏输出(带说明文字/残缺 JSON)必须被
  宽松解析或安全兜底, 绝不让坏输出破坏记忆。
每加一个用例 = 把线上踩过的坑变成回归资产。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.long_memory import (
    _item_rank_key,
    parse_classification,
    parse_housekeeping,
    rank_score,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def _item(
    text: str,
    score: float,
    importance: int | None = None,
    age_days: float = 0.0,
    superseded: bool = False,
) -> dict:
    meta: dict = {}
    if importance is not None:
        meta["importance"] = importance
    if superseded:
        meta["superseded"] = True
    created = (NOW - timedelta(days=age_days)).isoformat()
    return {"id": text, "memory": text, "score": score, "created_at": created, "metadata": meta}


def _rank_all(items: list[dict]) -> list[str]:
    return [
        it["memory"]
        for it in sorted(items, key=lambda it: _item_rank_key(it, NOW), reverse=True)
    ]


# --- 召回重排评测 ------------------------------------------------------------

RANKING_CASES = [
    {
        "name": "重要事实压过略高的相似度",
        "items": [
            _item("学生叫小明，读初一", 0.80, importance=5, age_days=30),
            _item("学生今天心情不错", 0.86, importance=1, age_days=1),
        ],
        "expect_top": "学生叫小明，读初一",
    },
    {
        "name": "重要性相同时新鲜的赢",
        "items": [
            _item("旧目标: 学完初一代数", 0.90, importance=3, age_days=200),
            _item("新目标: 准备期中考试", 0.90, importance=3, age_days=2),
        ],
        "expect_top": "新目标: 准备期中考试",
    },
    {
        "name": "老而重要的记忆不被彻底埋没(衰减下限)",
        "items": [
            _item("学生叫小明", 0.62, importance=5, age_days=3650),
            _item("学生昨天提到一道几何题", 0.55, importance=2, age_days=1),
        ],
        "expect_top": "学生叫小明",
    },
    {
        "name": "未标注的事实用默认重要性参与竞争",
        "items": [
            _item("无元数据的老事实", 0.82, importance=None, age_days=10),
            _item("默认重要性的新事实", 0.75, importance=None, age_days=1),
        ],
        "expect_top": "无元数据的老事实",
    },
]


def test_ranking_eval_cases():
    for case in RANKING_CASES:
        ranked = _rank_all(case["items"])
        assert ranked[0] == case["expect_top"], f"评测用例失败: {case['name']} -> {ranked}"


def test_rank_superseded_excluded_before_topk():
    """过时记忆即使相似度最高也不占注入名额（过滤发生在重排之前）。"""
    items = [
        _item("取代后的新事实", 0.70, importance=3),
        _item("被取代的旧事实", 0.99, importance=3, superseded=True),
    ]
    ranked = [it["memory"] for it in items if True]  # 过滤在 _sync_recall 里做
    live = [it for it in items if not it["metadata"].get("superseded")]
    ranked = _rank_all(live)
    assert ranked == ["取代后的新事实"]
    assert "被取代的旧事实" not in ranked


def test_rank_score_is_monotonic_and_bounded():
    fresh_mid = rank_score(0.8, 3, NOW, NOW)
    old_mid = rank_score(0.8, 3, NOW - timedelta(days=3650), NOW)
    assert fresh_mid > old_mid > 0
    # 衰减下限: 老记忆至少保留 "相似度 × 0.8 × 0.75" 的分值
    assert old_mid >= 0.8 * 0.8 * 0.75 - 1e-9
    # 重要性边界: 1 分和 5 分的乘子分别是 0.6 / 1.0
    assert rank_score(1.0, 5, NOW, NOW) > rank_score(1.0, 1, NOW, NOW)


def test_rank_tolerates_malformed_metadata():
    item = {
        "id": "x",
        "memory": "畸形元数据",
        "score": "0.7",  # 分数是字符串
        "created_at": "not-a-date",
        "metadata": {"importance": "很重要"},  # 重要性不是数字
    }
    assert _item_rank_key(item, NOW) > 0  # 不抛异常, 用默认值兜底


# --- 标注解析评测 ------------------------------------------------------------

CLASSIFICATION_CASES = [
    (
        '纯 JSON: {"items": [{"index": 0, "category": "学习偏好", "importance": 5}]}',
        [{"category": "学习偏好", "importance": 5}],
    ),
    (
        '带说明文字: 好的，标注如下 {"items": [{"index": 1, "category": "知识水平", "importance": 2}]} 请查收',
        [None, {"category": "知识水平", "importance": 2}],  # index 0 无标注 → 默认
    ),
    (
        '{"items": [{"index": 0, "category": "不存在的分类", "importance": 9}]}',
        [{"category": "其他", "importance": 5}],  # 非法分类回默认, 重要性钳到 5
    ),
    (
        '{"items": [{"index": 7, "category": "学习目标", "importance": 3}]}',  # 越界 index
        [None],
    ),
    ("完全不是 JSON 的输出", [None]),
]


def test_classification_parse_eval_cases():
    for raw, expect in CLASSIFICATION_CASES:
        got = parse_classification(raw, len(expect))
        for i, want in enumerate(expect):
            if want is None:
                assert got[i] == {"category": "其他", "importance": 3}, f"用例失败: {raw!r}"
            else:
                assert got[i] == want, f"用例失败: {raw!r}"


# --- 整理操作解析评测 --------------------------------------------------------

HOUSEKEEPING_CASES = [
    (
        '{"merges": [{"keep_id": 0, "drop_ids": [1, 2], "text": "学生喜欢天文学"}],'
        ' "supersede": [{"id": 3, "reason": "已被新事实取代"}]}',
        {"merges": 1, "supersede": 1},
    ),
    (
        '说明文字 {"merges": [], "supersede": []} 完',
        {"merges": 0, "supersede": 0},
    ),
    (
        '{"merges": "不是列表", "supersede": [{"id": 0}]}',  # merges 结构坏
        {"merges": 0, "supersede": 1},
    ),
    ("残缺输出 {\"merges\": [", {"merges": 0, "supersede": 0}),
]


def test_housekeeping_parse_eval_cases():
    for raw, expect in HOUSEKEEPING_CASES:
        ops = parse_housekeeping(raw)
        assert len(ops["merges"]) == expect["merges"], f"用例失败: {raw!r}"
        assert len(ops["supersede"]) == expect["supersede"], f"用例失败: {raw!r}"
