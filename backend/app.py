from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import uvicorn
import numpy as np
from collections import defaultdict
import calendar

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
db = None
analyzer = None
config = None


@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    global db, analyzer, config
    db = WeChatDB()
    analyzer = RelationAnalyzer()
    config = Config()
    print("RScore API 启动成功！")


class ContactResponse(BaseModel):
    user_name: str
    display_name: str
    nick_name: Optional[str]
    remark: Optional[str]


class RScoreRequest(BaseModel):
    user_name: str


class RScoreResponse(BaseModel):
    total_score: float
    dimensions: Dict[str, float]
    details: Dict
    milestones: List[Dict]
    statistics: Dict
    relationship_status: str
    freshness: float


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
                user_name=c['UserName'],
                display_name=c['DisplayName'],
                nick_name=c.get('NickName'),
                remark=c.get('Remark')
            )
            for c in contacts
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/calculate_rscore", response_model=RScoreResponse)
async def calculate_rscore(request: RScoreRequest):
    """计算关系评分"""
    try:
        messages = db.get_chat_messages(request.user_name)

        if messages.empty:
            raise HTTPException(status_code=404, detail="未找到该联系人的聊天记录")

        result = analyzer.calculate_rscore(messages)

        return RScoreResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def categorize_relationships(scores):
    """将好友关系分类"""
    categories = {
        '密友圈': [],
        '社交圈': [],
        '工作圈': [],
        '泛社交': []
    }

    for friend in scores:
        if friend['score'] >= 8:
            categories['密友圈'].append(friend)
        elif friend['score'] >= 6:
            categories['社交圈'].append(friend)
        elif friend['score'] >= 4:
            categories['工作圈'].append(friend)
        else:
            categories['泛社交'].append(friend)

    return {
        'categories': categories,
        'summary': {
            '密友圈': len(categories['密友圈']),
            '社交圈': len(categories['社交圈']),
            '工作圈': len(categories['工作圈']),
            '泛社交': len(categories['泛社交'])
        }
    }


def analyze_user_preference(all_dimensions, analyzed_count):
    """分析用户偏好（内部函数）"""
    if analyzed_count == 0:
        return {
            'user_type': '未知',
            'preferences': {},
            'description': '数据不足，无法分析',
            'analyzed_count': 0
        }

    preference = {}
    for dim, scores in all_dimensions.items():
        if scores:
            avg = np.mean(scores)
            std = np.std(scores)
            preference[dim] = {
                'average': round(avg, 2),
                'std': round(std, 2),
                'strength': round(avg / 10, 2)
            }
        else:
            preference[dim] = {
                'average': 0,
                'std': 0,
                'strength': 0
            }

    if preference:
        max_dim = max(preference.items(), key=lambda x: x[1]['average'])
        dim_names = {
            'interaction': '互动频率',
            'content': '内容质量',
            'emotion': '情感表达',
            'depth': '深度交流'
        }
        user_types = {
            'interaction': '互动型',
            'content': '深度型',
            'emotion': '情感型',
            'depth': '分享型'
        }

        return {
            'user_type': user_types[max_dim[0]],
            'preferences': preference,
            'description': f"基于{analyzed_count}位好友的分析，你是一个{user_types[max_dim[0]]}社交者，最注重{dim_names[max_dim[0]]}",
            'analyzed_count': analyzed_count
        }
    else:
        return {
            'user_type': '未知',
            'preferences': preference,
            'description': '数据不足',
            'analyzed_count': analyzed_count
        }


def analyze_time_patterns(all_time_data):
    """分析时间模式 - 用于热力图和月度分析"""
    heatmap_data = defaultdict(lambda: defaultdict(int))
    monthly_data = defaultdict(int)
    yearly_data = defaultdict(int)
    hourly_distribution = defaultdict(int)
    weekday_distribution = defaultdict(int)

    for time_entry in all_time_data:
        weekday = time_entry['weekday']
        hour = time_entry['hour']
        month_key = time_entry['month']
        year = time_entry['year']
        count = time_entry['count']

        heatmap_data[weekday][hour] += count
        monthly_data[month_key] += count
        yearly_data[year] += count
        hourly_distribution[hour] += count
        weekday_distribution[weekday] += count

    heatmap_formatted = []
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

    for weekday in range(7):
        for hour in range(24):
            heatmap_formatted.append({
                'weekday': weekday,
                'weekday_name': weekday_names[weekday],
                'hour': hour,
                'value': heatmap_data[weekday][hour]
            })

    sorted_months = sorted(monthly_data.keys())
    last_12_months = sorted_months[-12:] if len(sorted_months) > 12 else sorted_months

    monthly_trend = []
    for month in last_12_months:
        monthly_trend.append({
            'month': month,
            'count': monthly_data[month]
        })

    monthly_growth = []
    for i in range(1, len(monthly_trend)):
        prev = monthly_trend[i - 1]['count']
        curr = monthly_trend[i]['count']
        growth = ((curr - prev) / prev * 100) if prev > 0 else 0
        monthly_growth.append({
            'month': monthly_trend[i]['month'],
            'growth': round(growth, 2)
        })

    peak_hour = max(hourly_distribution.items(), key=lambda x: x[1])[0] if hourly_distribution else 12
    peak_weekday = max(weekday_distribution.items(), key=lambda x: x[1])[0] if weekday_distribution else 0

    return {
        'heatmap': heatmap_formatted,
        'monthly_trend': monthly_trend,
        'monthly_growth': monthly_growth,
        'yearly_summary': dict(yearly_data),
        'peak_hour': peak_hour,
        'peak_weekday': weekday_names[peak_weekday],
        'total_active_hours': len([h for h, count in hourly_distribution.items() if count > 0]),
        'night_owl_score': round(
            sum(hourly_distribution.get(h, 0) for h in range(0, 6)) / sum(hourly_distribution.values()) * 100,
            2) if hourly_distribution else 0
    }


def calculate_social_health(scores, all_dimensions, total_contacts):
    """计算社交健康度"""
    if not scores:
        return {
            'overall_health': 0,
            'diversity_index': 0,
            'balance_index': 0,
            'maintenance_index': 0,
            'emotional_index': 0,
            'health_level': '待改善',
            'suggestions': []
        }

    # 1. 关系多样性指数 (0-100)
    # 基于分数分布的标准差，分布越均匀越健康
    score_values = [s['score'] for s in scores]
    if len(score_values) > 1:
        std_dev = np.std(score_values)
        # 标准差在2-3之间最理想（有层次但不极端）
        diversity_index = max(0, min(100, 100 - abs(std_dev - 2.5) * 20))
    else:
        diversity_index = 50

    # 2. 社交平衡度 (0-100)
    # 基于高分好友比例和消息分布
    high_score_friends = len([s for s in scores if s['score'] >= 6])
    high_score_ratio = high_score_friends / len(scores) if scores else 0
    # 理想比例是20-30%的高分好友
    balance_index = max(0, min(100, 100 - abs(high_score_ratio - 0.25) * 200))

    # 3. 关系维护指数 (0-100)
    # 基于活跃和休眠关系的比例
    active_count = len([s for s in scores if s.get('relationship_status') == '活跃'])
    dormant_count = len([s for s in scores if s.get('relationship_status') in ['休眠', '失联']])
    maintenance_index = (active_count / len(scores) * 100) if scores else 0

    # 4. 情感表达指数 (0-100)
    # 基于情感维度的平均分
    if all_dimensions and 'emotion' in all_dimensions and all_dimensions['emotion']:
        emotion_avg = np.mean(all_dimensions['emotion'])
        emotional_index = min(100, emotion_avg * 10)
    else:
        emotional_index = 50

    # 5. 综合健康度 (0-100)
    overall_health = (
            diversity_index * 0.25 +
            balance_index * 0.25 +
            maintenance_index * 0.30 +
            emotional_index * 0.20
    )

    # 健康等级
    if overall_health >= 80:
        health_level = '优秀'
    elif overall_health >= 60:
        health_level = '良好'
    elif overall_health >= 40:
        health_level = '一般'
    else:
        health_level = '待改善'

    # 生成建议
    suggestions = []
    if diversity_index < 60:
        suggestions.append('社交圈较为单一，建议扩展不同类型的社交关系')
    if balance_index < 60:
        suggestions.append('深度关系比例偏低，建议加强与重要好友的互动')
    if maintenance_index < 60:
        suggestions.append(f'有{dormant_count}位好友长期未联系，建议主动问候')
    if emotional_index < 60:
        suggestions.append('情感表达较少，可以多使用表情和语音增加亲密度')

    return {
        'overall_health': round(overall_health, 1),
        'diversity_index': round(diversity_index, 1),
        'balance_index': round(balance_index, 1),
        'maintenance_index': round(maintenance_index, 1),
        'emotional_index': round(emotional_index, 1),
        'health_level': health_level,
        'suggestions': suggestions[:3]  # 最多3条建议
    }


def prepare_network_graph_data(scores):
    """准备关系网络图数据"""
    if not scores:
        return None

    # 只取前50个节点，避免图太复杂
    graph_scores = scores[:50] if len(scores) > 50 else scores

    nodes = []
    edges = []
    categories = []

    # 定义关系类型
    category_map = {
        '密友圈': 0,
        '社交圈': 1,
        '工作圈': 2,
        '泛社交': 3
    }

    categories = [
        {'name': '密友圈', 'itemStyle': {'color': '#52c41a'}},
        {'name': '社交圈', 'itemStyle': {'color': '#1890ff'}},
        {'name': '工作圈', 'itemStyle': {'color': '#faad14'}},
        {'name': '泛社交', 'itemStyle': {'color': '#d9d9d9'}}
    ]

    # 添加中心节点（用户自己）
    nodes.append({
        'id': 'center',
        'name': '我',
        'symbolSize': 50,
        'category': -1,
        'itemStyle': {'color': '#ff6464'},
        'x': 0,
        'y': 0,
        'fixed': True
    })

    # 添加好友节点
    for friend in graph_scores:
        # 确定类别
        if friend['score'] >= 8:
            category = 0
        elif friend['score'] >= 6:
            category = 1
        elif friend['score'] >= 4:
            category = 2
        else:
            category = 3

        # 节点大小基于消息数量
        size = min(30, max(10, np.log(friend['message_count'] + 1) * 3))

        # 距离基于评分（分数越高越近）
        distance = (10 - friend['score']) * 30
        angle = np.random.random() * 2 * np.pi

        nodes.append({
            'id': friend['user_name'],
            'name': friend['display_name'][:10],  # 限制名称长度
            'value': friend['score'],
            'symbolSize': size,
            'category': category,
            'x': distance * np.cos(angle),
            'y': distance * np.sin(angle)
        })

        # 添加边（连接线）
        edges.append({
            'source': 'center',
            'target': friend['user_name'],
            'value': friend['score'],
            'lineStyle': {
                'width': min(5, friend['score'] / 2),
                'opacity': min(1, friend['score'] / 10)
            }
        })

    return {
        'nodes': nodes,
        'edges': edges,
        'categories': categories
    }


@app.get("/api/batch_analysis")
async def batch_analysis(top_n: int = 0, limit: int = 0):
    """综合批量分析 - 包含所有分析"""
    try:
        contacts = db.get_contacts()
        scores = []

        all_dimensions = {
            'interaction': [],
            'content': [],
            'emotion': [],
            'depth': []
        }

        all_time_data = []

        if limit <= 0:
            contacts_to_analyze = contacts
        else:
            contacts_to_analyze = contacts[:limit]

        total_contacts = len(contacts_to_analyze)
        analyzed_count = 0
        failed_count = 0

        print(f"开始综合批量分析 {total_contacts} 位联系人...")

        for i, contact in enumerate(contacts_to_analyze, 1):
            try:
                if i % 10 == 0 or i == total_contacts:
                    print(f"分析进度: {i}/{total_contacts} ({i * 100 / total_contacts:.1f}%)")

                messages = db.get_chat_messages(contact['UserName'])
                if not messages.empty:
                    result = analyzer.calculate_rscore(messages)

                    scores.append({
                        'user_name': contact['UserName'],
                        'display_name': contact['DisplayName'],
                        'score': result['total_score'],
                        'message_count': result['statistics']['total_messages'],
                        'days': result['statistics'].get('total_days', 0),
                        'last_chat': result['statistics'].get('last_chat_date', ''),
                        'relationship_status': result.get('relationship_status', '未知'),
                        'freshness': result.get('freshness', 0),
                        'dimensions': result['dimensions']
                    })

                    for dim in all_dimensions:
                        all_dimensions[dim].append(result['dimensions'][dim])

                    try:
                        import pandas as pd
                        messages_df = messages
                        if 'CreateTime' not in messages_df.columns:
                            messages_df['CreateTime'] = pd.to_datetime(messages['CreateTime'], unit='s',
                                                                       errors='coerce')
                        else:
                            messages_df['CreateTime'] = pd.to_datetime(messages_df['CreateTime'], errors='coerce')

                        for _, msg in messages_df.iterrows():
                            if pd.notna(msg['CreateTime']):
                                time_entry = {
                                    'weekday': msg['CreateTime'].weekday(),
                                    'hour': msg['CreateTime'].hour,
                                    'month': msg['CreateTime'].strftime('%Y-%m'),
                                    'year': msg['CreateTime'].year,
                                    'count': 1
                                }
                                all_time_data.append(time_entry)
                    except Exception as e:
                        print(f"处理时间数据时出错: {e}")

                    analyzed_count += 1
            except Exception as e:
                print(f"分析 {contact.get('DisplayName', 'Unknown')} 时出错: {e}")
                failed_count += 1
                continue

        scores.sort(key=lambda x: x['score'], reverse=True)

        print(f"批量分析完成！成功: {analyzed_count}, 失败: {failed_count}")

        if scores:
            all_scores = [s['score'] for s in scores]
            all_scores_sorted = sorted(all_scores)
            median_index = len(all_scores_sorted) // 2

            statistics = {
                'average_score': round(sum(all_scores) / len(all_scores), 2),
                'median_score': round(all_scores_sorted[median_index], 2) if all_scores_sorted else 0,
                'score_distribution': {
                    '0-2': len([s for s in scores if s['score'] < 2]),
                    '2-4': len([s for s in scores if 2 <= s['score'] < 4]),
                    '4-6': len([s for s in scores if 4 <= s['score'] < 6]),
                    '6-8': len([s for s in scores if 6 <= s['score'] < 8]),
                    '8-10': len([s for s in scores if 8 <= s['score'] <= 10]),
                }
            }
        else:
            statistics = {
                'average_score': 0,
                'median_score': 0,
                'score_distribution': {
                    '0-2': 0,
                    '2-4': 0,
                    '4-6': 0,
                    '6-8': 0,
                    '8-10': 0,
                }
            }

        # 所有分析
        time_analysis = analyze_time_patterns(all_time_data) if all_time_data else None
        relationship_categories = categorize_relationships(scores)
        user_preference = analyze_user_preference(all_dimensions, analyzed_count)
        social_health = calculate_social_health(scores, all_dimensions, len(contacts))  # 新增
        network_graph = prepare_network_graph_data(scores)  # 新增

        return {
            'top_friends': scores[:top_n] if top_n > 0 else scores,
            'total_contacts': len(contacts),
            'total_analyzed': analyzed_count,
            'failed_count': failed_count,
            'statistics': statistics,
            'categories': relationship_categories,
            'user_preference': user_preference,
            'time_analysis': time_analysis,
            'social_health': social_health,  # 新增
            'network_graph': network_graph  # 新增
        }

    except Exception as e:
        print(f"批量分析出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user_preference_analysis")
async def user_preference_analysis(limit: int = 30):
    """独立的用户偏好分析（已废弃）"""
    try:
        result = await batch_analysis(top_n=0, limit=limit)
        return result.get('user_preference', {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export_report/{user_name}")
async def export_report(user_name: str):
    """导出关系分析报告"""
    try:
        messages = db.get_chat_messages(user_name)
        if messages.empty:
            raise HTTPException(status_code=404, detail="未找到该联系人的聊天记录")

        result = analyzer.calculate_rscore(messages)

        return {
            'type': 'json',
            'data': result,
            'export_date': datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """关闭数据库连接"""
    if db:
        db.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)