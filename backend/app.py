from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import uvicorn
import numpy as np
from collections import defaultdict
import calendar
import pandas as pd
import re

from database import WeChatDB
from analyzer import RelationAnalyzer
from config import Config

app = FastAPI(title="RScore API", version="1.0.0")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局变量
db: Optional[WeChatDB] = None
analyzer: Optional[RelationAnalyzer] = None
config: Optional[Config] = None


@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    global db, analyzer, config
    db = WeChatDB()
    analyzer = RelationAnalyzer()
    config = Config()
    print("RScore API 启动成功！")


# =========================
# Pydantic 数据模型
# =========================
class ContactResponse(BaseModel):
    user_name: str
    display_name: str
    nick_name: Optional[str]
    remark: Optional[str]


class RScoreRequest(BaseModel):
    user_name: str


class RScoreResponse(BaseModel):
    # 原有字段（与你仓库一致）
    total_score: float
    dimensions: Dict[str, float]
    details: Dict
    milestones: List[Dict]
    statistics: Dict
    relationship_status: str
    freshness: float
    # 新增字段（本次需求）
    interaction_analysis: Dict
    achievements: List[Dict]


# =========================
# 互动模式分析 & 成就计算（新增）
# =========================
_EMOJI_RE = re.compile(
    r"["
    r"\U0001F300-\U0001F5FF"
    r"\U0001F600-\U0001F64F"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F700-\U0001F77F"
    r"\U0001F780-\U0001F7FF"
    r"\U0001F800-\U0001F8FF"
    r"\U0001F900-\U0001F9FF"
    r"\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF"
    r"\u2600-\u26FF"
    r"\u2700-\u27BF"
    r"]",
    re.UNICODE,
)


def _count_emojis(s: str) -> int:
    if not isinstance(s, str):
        return 0
    return len(_EMOJI_RE.findall(s))


def _ensure_datetime_series(series: pd.Series) -> pd.Series:
    """CreateTime 可能是秒/毫秒或已是 datetime，统一转为 pandas datetime"""
    if np.issubdtype(series.dtype, np.datetime64):
        return pd.to_datetime(series)
    numeric = pd.to_numeric(series, errors="coerce")
    unit = "ms" if (pd.notna(numeric).any() and numeric.max() > 1e12) else "s"
    return pd.to_datetime(numeric, unit=unit, errors="coerce")


def _compute_interaction_analysis(messages: pd.DataFrame) -> Dict:
    """
    互动模式分析：
    - 对话发起者（按 45min 会话切分）
    - 回复延迟分布（仅统计身份切换时相邻两条）
    - 会话长度分布
    - 单向/双向交流比例
    """
    if messages is None or len(messages) == 0:
        return {}

    df = messages.copy()

    # 时间列 / 发送方列（多名字兜底）
    ts_col = next((c for c in ["CreateTime", "create_time", "Timestamp", "Datetime", "dt", "time"] if c in df.columns), None)
    if ts_col is None:
        return {}

    is_self_col = next((c for c in ["IsSender", "is_sender", "IsSend", "is_send", "is_self"] if c in df.columns), None)
    is_self = df[is_self_col].astype(int) if is_self_col in df.columns else pd.Series(np.zeros(len(df), dtype=int), index=df.index)

    dt = _ensure_datetime_series(df[ts_col])
    df = df.assign(_dt=dt, _is_self=is_self).dropna(subset=["_dt"]).sort_values("_dt").reset_index(drop=True)

    # 以 45 分钟切分会话
    SESSION_GAP = pd.Timedelta(minutes=45)
    gap = df["_dt"].diff()
    session_id = (gap.isna() | (gap > SESSION_GAP)).cumsum()
    df["_session"] = session_id

    # 发起者：各会话首条消息
    firsts = df.groupby("_session").first(numeric_only=False)
    self_sessions = int((firsts["_is_self"] == 1).sum())
    friend_sessions = int((firsts["_is_self"] == 0).sum())
    total_sessions = self_sessions + friend_sessions
    self_rate = (self_sessions / total_sessions) if total_sessions > 0 else 0.0

    # 回复延迟（仅统计身份翻转处）
    flip = df["_is_self"].ne(df["_is_self"].shift(1))
    delays = (df.loc[flip, "_dt"] - df.loc[flip, "_dt"].shift(1)).dropna().dt.total_seconds()
    bins = [0, 60, 300, 600, 1800, 3600, 10800, float("inf")]
    labels = ["<1m", "1-5m", "5-10m", "10-30m", "30-60m", "1-3h", ">3h"]
    if len(delays) > 0:
        cats = pd.cut(delays, bins=bins, labels=labels, right=False)
        delay_counts = cats.value_counts().reindex(labels, fill_value=0)
        median_delay = float(np.median(delays))
        p90_delay = float(np.percentile(delays, 90))
    else:
        delay_counts = pd.Series(0, index=labels)
        median_delay = 0.0
        p90_delay = 0.0

    # 会话长度分布
    session_sizes = df.groupby("_session").size()
    len_bins = [1, 2, 4, 7, 11, float("inf")]
    len_labels = ["1", "2-3", "4-6", "7-10", ">10"]
    if len(session_sizes) > 0:
        len_cats = pd.cut(session_sizes, bins=len_bins, labels=len_labels, right=False, include_lowest=True)
        len_counts = len_cats.value_counts().reindex(len_labels, fill_value=0)
    else:
        len_counts = pd.Series(0, index=len_labels)

    # 单向/双向
    session_self_speak = df.groupby("_session")["_is_self"].agg(["min", "max"])
    one_way = int((session_self_speak["min"] == session_self_speak["max"]).sum())
    two_way = int(total_sessions - one_way)
    one_way_rate = (one_way / total_sessions) if total_sessions > 0 else 0.0

    return {
        "initiator": {
            "self_sessions": self_sessions,
            "friend_sessions": friend_sessions,
            "total_sessions": int(total_sessions),
            "self_rate": round(self_rate, 4),
        },
        "reply_delay": {
            "bins": [{"range": lab, "count": int(delay_counts[lab])} for lab in labels],
            "median_seconds": round(median_delay, 2),
            "p90_seconds": round(p90_delay, 2),
            "pairs": int(len(delays)),
        },
        "conversation_length": {
            "bins": [{"range": lab, "count": int(len_counts[lab])} for lab in len_labels],
            "mean": float(session_sizes.mean()) if len(session_sizes) > 0 else 0.0,
            "median": float(session_sizes.median()) if len(session_sizes) > 0 else 0.0,
            "sessions": int(total_sessions),
        },
        "directionality": {
            "one_way_sessions": one_way,
            "two_way_sessions": two_way,
            "one_way_rate": round(one_way_rate, 4),
        },
    }


def _compute_achievements(messages: pd.DataFrame, inter: Dict) -> List[Dict]:
    """
    8 枚成就（含你指定的3枚）：
    - 深夜守护者：深夜(0~5点)消息≥100
    - 情感大师：表情使用率≥15%
    - 长情守护：最长连续聊天天数≥30
    - 开场达人：我方发起≥60% 且会话数≥30
    - 秒回达人：回复延迟中位数≤60s 且会话数≥30
    - 话痨模式：平均每条≥30字 且消息总数≥500
    - 多媒体玩家：非文本占比≥20% 且非文本条数≥50
    - 双向均衡：我方发送占比在 40%~60% 且总消息≥200
    """
    if messages is None or len(messages) == 0:
        return []

    df = messages.copy()

    ts_col = next((c for c in ["CreateTime", "create_time", "Timestamp", "Datetime", "dt", "time"] if c in df.columns), None)
    if ts_col is None:
        return []

    dt = _ensure_datetime_series(df[ts_col])
    df = df.assign(_dt=dt).dropna(subset=["_dt"]).sort_values("_dt")

    text_col = next((c for c in ["Content", "StrContent", "content", "text"] if c in df.columns), None)
    type_col = next((c for c in ["Type", "type"] if c in df.columns), None)
    subtype_col = next((c for c in ["SubType", "sub_type", "SubTypeInt"] if c in df.columns), None)
    is_self_col = next((c for c in ["IsSender", "is_sender", "IsSend", "is_send", "is_self"] if c in df.columns), None)
    is_self = df[is_self_col].astype(int) if is_self_col in df.columns else pd.Series(np.zeros(len(df), dtype=int), index=df.index)
    df["_is_self"] = is_self

    # 指标
    deep_night_count = int(((df["_dt"].dt.hour >= 0) & (df["_dt"].dt.hour <= 5)).sum())

    total_msgs = len(df)
    if text_col:
        emoji_counts = df[text_col].apply(_count_emojis)
        emoji_rate = float(emoji_counts.sum() / total_msgs) if total_msgs > 0 else 0.0
        avg_len = float(df[text_col].astype(str).str.len().mean())
    else:
        emoji_rate = 0.0
        avg_len = 0.0

    # 最长连续聊天天数
    days = df["_dt"].dt.normalize().drop_duplicates().sort_values()
    if len(days) == 0:
        max_streak = 0
    else:
        streak = 1
        max_streak = 1
        for i in range(1, len(days)):
            if (days.iloc[i] - days.iloc[i - 1]).days == 1:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 1

    # 从互动分析中拿派生指标
    sessions = inter.get("conversation_length", {}).get("sessions", 0) if inter else 0
    initiator_self_rate = inter.get("initiator", {}).get("self_rate", 0.0) if inter else 0.0
    median_delay = inter.get("reply_delay", {}).get("median_seconds", 0.0) if inter else 0.0

    # 非文本占比（按你的约定：Type=1 文本；Type=49 & SubType=57 视作“带引用文本”）
    if type_col:
        if subtype_col:
            is_text = (df[type_col] == 1) | ((df[type_col] == 49) & (df[subtype_col] == 57))
        else:
            is_text = (df[type_col] == 1)
        non_text_ratio = float((~is_text).sum() / len(df)) if len(df) > 0 else 0.0
        non_text_count = int((~is_text).sum())
    else:
        non_text_ratio = 0.0
        non_text_count = 0

    send_ratio = float((df["_is_self"] == 1).sum() / total_msgs) if total_msgs > 0 else 0.0

    def mk(name, key, cond, progress, desc):
        return {
            "key": key,
            "name": name,
            "achieved": bool(cond),
            "progress": float(max(0.0, min(1.0, progress))),
            "description": desc,
        }

    return [
        mk("深夜守护者", "night_guard", deep_night_count >= 100, deep_night_count / 100, f"深夜聊天 {deep_night_count}/100 次"),
        mk("情感大师", "emoji_master", emoji_rate >= 0.15, (emoji_rate / 0.15) if 0.15 > 0 else 0.0, f"表情使用率 {emoji_rate:.1%}"),
        mk("长情守护", "long_streak", max_streak >= 30, max_streak / 30, f"最长连续聊天 {max_streak}/30 天"),
        mk("开场达人", "initiator", (initiator_self_rate >= 0.6 and sessions >= 30), (initiator_self_rate / 0.6) * min(1, sessions / 30), f"你发起 {initiator_self_rate:.1%} 的对话"),
        mk("秒回达人", "fast_reply", (median_delay <= 60 and sessions >= 30), min(1.0, 60 / max(1, median_delay)), f"回复延迟中位数 {int(median_delay)} 秒"),
        mk("话痨模式", "long_text", (avg_len >= 30 and total_msgs >= 500), min(1.0, avg_len / 30) * min(1, total_msgs / 500), f"平均每条 {avg_len:.0f} 字"),
        mk("多媒体玩家", "multimedia", (non_text_ratio >= 0.2 and non_text_count >= 50), min(1.0, non_text_ratio / 0.2) * min(1, non_text_count / 50), f"多媒体占比 {non_text_ratio:.1%}"),
        mk("双向均衡", "balanced", (abs(send_ratio - 0.5) <= 0.1 and total_msgs >= 200), (1 - abs(send_ratio - 0.5) / 0.1) * min(1, total_msgs / 200), f"你发送占比 {send_ratio:.1%}"),
    ]


# =========================
# 其余分析（来自你原始实现）
# =========================
def categorize_relationships(scores):
    """将好友关系分类"""
    categories = {"密友圈": [], "社交圈": [], "工作圈": [], "泛社交": []}
    for friend in scores:
        if friend["score"] >= 8:
            categories["密友圈"].append(friend)
        elif friend["score"] >= 6:
            categories["社交圈"].append(friend)
        elif friend["score"] >= 4:
            categories["工作圈"].append(friend)
        else:
            categories["泛社交"].append(friend)
    return {
        "categories": categories,
        "summary": {
            "密友圈": len(categories["密友圈"]),
            "社交圈": len(categories["社交圈"]),
            "工作圈": len(categories["工作圈"]),
            "泛社交": len(categories["泛社交"]),
        },
    }


def analyze_user_preference(all_dimensions, analyzed_count):
    """分析用户偏好（内部函数）"""
    if analyzed_count == 0:
        return {"user_type": "未知", "preferences": {}, "description": "数据不足，无法分析", "analyzed_count": 0}

    preference = {}
    for dim, scores in all_dimensions.items():
        if scores:
            avg = np.mean(scores)
            std = np.std(scores)
            preference[dim] = {"average": round(avg, 2), "std": round(std, 2), "strength": round(avg / 10, 2)}
        else:
            preference[dim] = {"average": 0, "std": 0, "strength": 0}

    if preference:
        max_dim = max(preference.items(), key=lambda x: x[1]["average"])
        dim_names = {"interaction": "互动频率", "content": "内容质量", "emotion": "情感表达", "depth": "深度交流"}
        user_types = {"interaction": "互动型", "content": "深度型", "emotion": "情感型", "depth": "分享型"}
        return {
            "user_type": user_types[max_dim[0]],
            "preferences": preference,
            "description": f"基于{analyzed_count}位好友的分析，你是一个{user_types[max_dim[0]]}社交者，最注重{dim_names[max_dim[0]]}",
            "analyzed_count": analyzed_count,
        }
    else:
        return {"user_type": "未知", "preferences": preference, "description": "数据不足", "analyzed_count": analyzed_count}


def analyze_time_patterns(all_time_data):
    """分析时间模式 - 用于热力图和月度分析"""
    heatmap_data = defaultdict(lambda: defaultdict(int))
    monthly_data = defaultdict(int)
    yearly_data = defaultdict(int)
    hourly_distribution = defaultdict(int)
    weekday_distribution = defaultdict(int)

    for time_entry in all_time_data:
        weekday = time_entry["weekday"]
        hour = time_entry["hour"]
        month_key = time_entry["month"]
        year = time_entry["year"]
        count = time_entry["count"]
        heatmap_data[weekday][hour] += count
        monthly_data[month_key] += count
        yearly_data[year] += count
        hourly_distribution[hour] += count
        weekday_distribution[weekday] += count

    heatmap_formatted = []
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for weekday in range(7):
        for hour in range(24):
            heatmap_formatted.append(
                {"weekday": weekday, "weekday_name": weekday_names[weekday], "hour": hour, "value": heatmap_data[weekday][hour]}
            )

    sorted_months = sorted(monthly_data.keys())
    last_12_months = sorted_months[-12:] if len(sorted_months) > 12 else sorted_months
    monthly_trend = [{"month": month, "count": monthly_data[month]} for month in last_12_months]

    monthly_growth = []
    for i in range(1, len(monthly_trend)):
        prev = monthly_trend[i - 1]["count"]
        curr = monthly_trend[i]["count"]
        growth = ((curr - prev) / prev * 100) if prev > 0 else 0
        monthly_growth.append({"month": monthly_trend[i]["month"], "growth": round(growth, 2)})

    peak_hour = max(hourly_distribution.items(), key=lambda x: x[1])[0] if hourly_distribution else 12
    peak_weekday = max(weekday_distribution.items(), key=lambda x: x[1])[0] if weekday_distribution else 0

    return {
        "heatmap": heatmap_formatted,
        "monthly_trend": monthly_trend,
        "monthly_growth": monthly_growth,
        "yearly_summary": dict(yearly_data),
        "peak_hour": peak_hour,
        "peak_weekday": weekday_names[peak_weekday],
        "total_active_hours": len([h for h, count in hourly_distribution.items() if count > 0]),
        "night_owl_score": round(
            (sum(hourly_distribution.get(h, 0) for h in range(0, 6)) / sum(hourly_distribution.values()) * 100), 2
        )
        if hourly_distribution
        else 0,
    }


def calculate_social_health(scores, all_dimensions, total_contacts):
    """计算社交健康度"""
    if not scores:
        return {
            "overall_health": 0,
            "diversity_index": 0,
            "balance_index": 0,
            "maintenance_index": 0,
            "emotional_index": 0,
            "health_level": "待改善",
            "suggestions": [],
        }

    # 1. 多样性指数
    score_values = [s["score"] for s in scores]
    if len(score_values) > 1:
        std_dev = np.std(score_values)
        diversity_index = max(0, min(100, 100 - abs(std_dev - 2.5) * 20))
    else:
        diversity_index = 50

    # 2. 平衡度
    high_score_friends = len([s for s in scores if s["score"] >= 6])
    high_score_ratio = high_score_friends / len(scores) if scores else 0
    balance_index = max(0, min(100, 100 - abs(high_score_ratio - 0.25) * 200))

    # 3. 维护指数
    active_count = len([s for s in scores if s.get("relationship_status") == "活跃"])
    dormant_count = len([s for s in scores if s.get("relationship_status") in ["休眠", "失联"]])
    maintenance_index = (active_count / len(scores) * 100) if scores else 0

    # 4. 情感表达
    if all_dimensions and "emotion" in all_dimensions and all_dimensions["emotion"]:
        emotion_avg = np.mean(all_dimensions["emotion"])
        emotional_index = min(100, emotion_avg * 10)
    else:
        emotional_index = 50

    overall_health = diversity_index * 0.25 + balance_index * 0.25 + maintenance_index * 0.30 + emotional_index * 0.20

    suggestions = []
    if diversity_index < 60:
        suggestions.append("社交圈较为单一，建议扩展不同类型的社交关系")
    if balance_index < 60:
        suggestions.append("深度关系比例偏低，建议加强与重要好友的互动")
    if maintenance_index < 60:
        suggestions.append(f"有{dormant_count}位好友长期未联系，建议主动问候")
    if emotional_index < 60:
        suggestions.append("情感表达较少，可以多使用表情和语音增加亲密度")

    if overall_health >= 80:
        health_level = "优秀"
    elif overall_health >= 60:
        health_level = "良好"
    elif overall_health >= 40:
        health_level = "一般"
    else:
        health_level = "待改善"

    return {
        "overall_health": round(overall_health, 1),
        "diversity_index": round(diversity_index, 1),
        "balance_index": round(balance_index, 1),
        "maintenance_index": round(maintenance_index, 1),
        "emotional_index": round(emotional_index, 1),
        "health_level": health_level,
        "suggestions": suggestions[:3],
    }


def prepare_network_graph_data(scores):
    """准备关系网络图数据"""
    if not scores:
        return None

    graph_scores = scores[:50] if len(scores) > 50 else scores
    nodes = []
    edges = []
    categories = [
        {"name": "密友圈", "itemStyle": {"color": "#52c41a"}},
        {"name": "社交圈", "itemStyle": {"color": "#1890ff"}},
        {"name": "工作圈", "itemStyle": {"color": "#faad14"}},
        {"name": "泛社交", "itemStyle": {"color": "#d9d9d9"}},
    ]

    # 中心节点
    nodes.append({"id": "center", "name": "我", "symbolSize": 50, "category": -1, "itemStyle": {"color": "#ff6464"}, "x": 0, "y": 0, "fixed": True})

    # 好友节点 + 边
    for friend in graph_scores:
        if friend["score"] >= 8:
            category = 0
        elif friend["score"] >= 6:
            category = 1
        elif friend["score"] >= 4:
            category = 2
        else:
            category = 3

        size = min(30, max(10, np.log(friend["message_count"] + 1) * 3))
        distance = (10 - friend["score"]) * 30
        angle = np.random.random() * 2 * np.pi

        nodes.append(
            {
                "id": friend["user_name"],
                "name": friend["display_name"][:10],
                "value": friend["score"],
                "symbolSize": size,
                "category": category,
                "x": distance * np.cos(angle),
                "y": distance * np.sin(angle),
            }
        )

        edges.append(
            {
                "source": "center",
                "target": friend["user_name"],
                "value": friend["score"],
                "lineStyle": {"width": min(5, friend["score"] / 2), "opacity": min(1, friend["score"] / 10)},
            }
        )

    return {"nodes": nodes, "edges": edges, "categories": categories}


# =========================
# 路由
# =========================
@app.get("/")
async def root():
    """根路径"""
    return {"message": "RScore API is running", "version": "1.0.0"}


@app.get("/api/contacts", response_model=List[ContactResponse])
async def get_contacts():
    """获取所有联系人列表"""
    try:
        contacts = db.get_contacts()
        return [
            ContactResponse(
                user_name=c["UserName"],
                display_name=c["DisplayName"],
                nick_name=c.get("NickName"),
                remark=c.get("Remark"),
            )
            for c in contacts
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/calculate_rscore", response_model=RScoreResponse)
async def calculate_rscore(request: RScoreRequest):
    """计算关系评分 + 互动分析 + 成就系统"""
    try:
        messages = db.get_chat_messages(request.user_name)
        if messages.empty:
            raise HTTPException(status_code=404, detail="未找到该联系人的聊天记录")

        result = analyzer.calculate_rscore(messages)

        # 新增：互动分析 + 成就
        inter = _compute_interaction_analysis(messages)
        result["interaction_analysis"] = inter
        result["achievements"] = _compute_achievements(messages, inter)

        return RScoreResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batch_analysis")
async def batch_analysis(top_n: int = 0, limit: int = 0):
    """综合批量分析 - 包含所有分析"""
    try:
        contacts = db.get_contacts()

        scores = []
        all_dimensions = {"interaction": [], "content": [], "emotion": [], "depth": []}
        all_time_data = []

        contacts_to_analyze = contacts if limit <= 0 else contacts[:limit]
        total_contacts = len(contacts_to_analyze)
        analyzed_count = 0
        failed_count = 0

        print(f"开始综合批量分析 {total_contacts} 位联系人...")

        for i, contact in enumerate(contacts_to_analyze, 1):
            try:
                if i % 10 == 0 or i == total_contacts:
                    print(f"分析进度: {i}/{total_contacts} ({i * 100 / total_contacts:.1f}%)")

                messages = db.get_chat_messages(contact["UserName"])
                if not messages.empty:
                    result = analyzer.calculate_rscore(messages)
                    scores.append(
                        {
                            "user_name": contact["UserName"],
                            "display_name": contact["DisplayName"],
                            "score": result["total_score"],
                            "message_count": result["statistics"]["total_messages"],
                            "days": result["statistics"].get("total_days", 0),
                            "last_chat": result["statistics"].get("last_chat_date", ""),
                            "relationship_status": result.get("relationship_status", "未知"),
                            "freshness": result.get("freshness", 0),
                            "dimensions": result["dimensions"],
                        }
                    )

                    for dim in all_dimensions:
                        all_dimensions[dim].append(result["dimensions"][dim])

                    # 时间数据（热力图/趋势）
                    try:
                        msgs = messages.copy()
                        if "CreateTime" not in msgs.columns:
                            msgs["CreateTime"] = pd.to_datetime(messages["CreateTime"], unit="s", errors="coerce")
                        else:
                            msgs["CreateTime"] = pd.to_datetime(msgs["CreateTime"], errors="coerce")

                        for _, msg in msgs.iterrows():
                            if pd.notna(msg["CreateTime"]):
                                all_time_data.append(
                                    {
                                        "weekday": msg["CreateTime"].weekday(),
                                        "hour": msg["CreateTime"].hour,
                                        "month": msg["CreateTime"].strftime("%Y-%m"),
                                        "year": msg["CreateTime"].year,
                                        "count": 1,
                                    }
                                )
                    except Exception as e:
                        print(f"处理时间数据时出错: {e}")

                    analyzed_count += 1

            except Exception as e:
                print(f"分析 {contact.get('DisplayName', 'Unknown')} 时出错: {e}")
                failed_count += 1
                continue

        scores.sort(key=lambda x: x["score"], reverse=True)
        print(f"批量分析完成！成功: {analyzed_count}, 失败: {failed_count}")

        if scores:
            all_scores = [s["score"] for s in scores]
            all_scores_sorted = sorted(all_scores)
            median_index = len(all_scores_sorted) // 2
            statistics = {
                "average_score": round(sum(all_scores) / len(all_scores), 2),
                "median_score": round(all_scores_sorted[median_index], 2) if all_scores_sorted else 0,
                "score_distribution": {
                    "0-2": len([s for s in scores if s["score"] < 2]),
                    "2-4": len([s for s in scores if 2 <= s["score"] < 4]),
                    "4-6": len([s for s in scores if 4 <= s["score"] < 6]),
                    "6-8": len([s for s in scores if 6 <= s["score"] < 8]),
                    "8-10": len([s for s in scores if 8 <= s["score"] <= 10]),
                },
            }
        else:
            statistics = {
                "average_score": 0,
                "median_score": 0,
                "score_distribution": {"0-2": 0, "2-4": 0, "4-6": 0, "6-8": 0, "8-10": 0},
            }

        time_analysis = analyze_time_patterns(all_time_data) if all_time_data else None
        relationship_categories = categorize_relationships(scores)
        user_preference = analyze_user_preference(all_dimensions, analyzed_count)
        social_health = calculate_social_health(scores, all_dimensions, len(contacts))
        network_graph = prepare_network_graph_data(scores)

        return {
            "top_friends": scores[:top_n] if top_n > 0 else scores,
            "total_contacts": len(contacts),
            "total_analyzed": analyzed_count,
            "failed_count": failed_count,
            "statistics": statistics,
            "categories": relationship_categories,
            "user_preference": user_preference,
            "time_analysis": time_analysis,
            "social_health": social_health,
            "network_graph": network_graph,
        }
    except Exception as e:
        print(f"批量分析出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user_preference_analysis")
async def user_preference_analysis(limit: int = 30):
    """独立的用户偏好分析（保持兼容）"""
    try:
        result = await batch_analysis(top_n=0, limit=limit)
        return result.get("user_preference", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export_report/{user_name}")
async def export_report(user_name: str):
    """导出关系分析报告（包含本次新增两个字段）"""
    try:
        messages = db.get_chat_messages(user_name)
        if messages.empty:
            raise HTTPException(status_code=404, detail="未找到该联系人的聊天记录")

        result = analyzer.calculate_rscore(messages)
        inter = _compute_interaction_analysis(messages)
        achievements = _compute_achievements(messages, inter)
        result["interaction_analysis"] = inter
        result["achievements"] = achievements

        return {"type": "json", "data": result, "export_date": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """关闭数据库连接"""
    if db:
        db.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
