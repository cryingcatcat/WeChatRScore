from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
import uvicorn
import numpy as np

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

    # 计算各维度的平均值和标准差
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

    # 判断用户类型
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


@app.get("/api/batch_analysis")
async def batch_analysis(top_n: int = 0, limit: int = 0):
    """
    综合批量分析 - 一次性完成所有分析
    参数：
    - top_n: 返回前N名，0表示返回全部
    - limit: 分析数量限制，0表示分析全部，默认30
    """
    try:
        contacts = db.get_contacts()
        scores = []

        # 收集所有维度数据（用于用户偏好分析）
        all_dimensions = {
            'interaction': [],
            'content': [],
            'emotion': [],
            'depth': []
        }

        # 确定要分析的联系人数量
        if limit <= 0:
            contacts_to_analyze = contacts  # 分析全部
        else:
            contacts_to_analyze = contacts[:limit]  # 分析指定数量

        total_contacts = len(contacts_to_analyze)
        analyzed_count = 0
        failed_count = 0

        print(f"开始综合批量分析 {total_contacts} 位联系人...")

        # 一次遍历，同时完成评分计算和维度数据收集
        for i, contact in enumerate(contacts_to_analyze, 1):
            try:
                # 打印进度
                if i % 10 == 0 or i == total_contacts:
                    print(f"分析进度: {i}/{total_contacts} ({i * 100 / total_contacts:.1f}%)")

                messages = db.get_chat_messages(contact['UserName'])
                if not messages.empty:
                    result = analyzer.calculate_rscore(messages)

                    # 收集评分数据
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

                    # 同时收集维度数据用于偏好分析
                    for dim in all_dimensions:
                        all_dimensions[dim].append(result['dimensions'][dim])

                    analyzed_count += 1
            except Exception as e:
                print(f"分析 {contact.get('DisplayName', 'Unknown')} 时出错: {e}")
                failed_count += 1
                continue

        # 按分数排序
        scores.sort(key=lambda x: x['score'], reverse=True)

        print(f"批量分析完成！成功: {analyzed_count}, 失败: {failed_count}")

        # 计算统计数据
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

        # 关系分类
        relationship_categories = categorize_relationships(scores)

        # 用户偏好分析（使用已收集的维度数据）
        user_preference = analyze_user_preference(all_dimensions, analyzed_count)

        # 返回综合结果
        return {
            'top_friends': scores[:top_n] if top_n > 0 else scores,
            'total_contacts': len(contacts),
            'total_analyzed': analyzed_count,
            'failed_count': failed_count,
            'statistics': statistics,
            'categories': relationship_categories,
            'user_preference': user_preference  # 新增：直接包含用户偏好
        }

    except Exception as e:
        print(f"批量分析出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 保留独立的用户偏好分析接口（为了兼容性，但实际不再使用）
@app.get("/api/user_preference_analysis")
async def user_preference_analysis(limit: int = 0):
    """
    独立的用户偏好分析（已废弃，建议使用batch_analysis）
    """
    # 直接调用batch_analysis并只返回用户偏好部分
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