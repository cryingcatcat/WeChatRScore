import React, { useState, useEffect } from 'react';
import { Layout, Card, Select, Button, Spin, message, Row, Col, Statistic, Tag, Timeline, Table, Progress, Tabs } from 'antd';
import { UserOutlined, MessageOutlined, CalendarOutlined, TrophyOutlined, HeartOutlined, TeamOutlined, ExportOutlined, SyncOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import axios from 'axios';
import dayjs from 'dayjs';
import 'antd/dist/reset.css';
import './App.css';

const { Header, Content } = Layout;
const { Option } = Select;
const { TabPane } = Tabs;

const API_BASE_URL = 'http://localhost:8000';

function App() {
  const [contacts, setContacts] = useState([]);
  const [selectedContact, setSelectedContact] = useState(null);
  const [scoreData, setScoreData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [batchAnalysis, setBatchAnalysis] = useState(null);
  const [userPreference, setUserPreference] = useState(null);
  const [loadingPreference, setLoadingPreference] = useState(false);

  // 获取联系人列表
  useEffect(() => {
    fetchContacts();
  }, []);

  const fetchContacts = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/contacts`);
      setContacts(response.data);
    } catch (error) {
      message.error('获取联系人列表失败');
      console.error(error);
    }
  };

  // 计算关系评分
  const calculateScore = async (userName) => {
    setLoading(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/api/calculate_rscore`, {
        user_name: userName
      });
      setScoreData(response.data);
      message.success('评分计算完成！');
    } catch (error) {
      message.error('计算评分失败：' + (error.response?.data?.detail || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  // 批量分析
  const runBatchAnalysis = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/batch_analysis`);
      setBatchAnalysis(response.data);
      
      // 同时获取用户偏好分析
      fetchUserPreference();
      
      message.success('批量分析完成！');
    } catch (error) {
      message.error('批量分析失败');
    } finally {
      setLoading(false);
    }
  };

  // 获取用户偏好分析
  const fetchUserPreference = async () => {
    setLoadingPreference(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/user_preference_analysis`);
      setUserPreference(response.data);
    } catch (error) {
      console.error('获取用户偏好失败', error);
    } finally {
      setLoadingPreference(false);
    }
  };

  // 导出报告
  const exportReport = async () => {
    if (!selectedContact) {
      message.warning('请先选择联系人');
      return;
    }
    try {
      const response = await axios.get(`${API_BASE_URL}/api/export_report/${selectedContact}`);
      const dataStr = JSON.stringify(response.data, null, 2);
      const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
      const exportFileDefaultName = `rscore_report_${selectedContact}_${dayjs().format('YYYYMMDD')}.json`;
      
      const linkElement = document.createElement('a');
      linkElement.setAttribute('href', dataUri);
      linkElement.setAttribute('download', exportFileDefaultName);
      linkElement.click();
      
      message.success('报告导出成功！');
    } catch (error) {
      message.error('导出失败');
    }
  };

  // 雷达图配置
  const getRadarOption = () => {
    if (!scoreData) return {};
    
    return {
      title: {
        text: '关系维度分析',
        left: 'center',
        top: 10,
        textStyle: {
          fontSize: 16,
          fontWeight: 'normal'
        }
      },
      tooltip: {},
      radar: {
        center: ['50%', '55%'],
        radius: '65%',
        indicator: [
          { name: '互动频率', max: 10 },
          { name: '内容质量', max: 10 },
          { name: '情感表达', max: 10 },
          { name: '深度交流', max: 10 }
        ],
        name: {
          textStyle: {
            fontSize: 12,
            color: '#333'
          }
        }
      },
      series: [{
        type: 'radar',
        data: [{
          value: [
            scoreData.dimensions.interaction,
            scoreData.dimensions.content,
            scoreData.dimensions.emotion,
            scoreData.dimensions.depth
          ],
          name: '关系评分',
          areaStyle: {
            color: 'rgba(24, 144, 255, 0.2)'
          },
          lineStyle: {
            color: '#1890ff',
            width: 2
          },
          itemStyle: {
            color: '#1890ff'
          }
        }]
      }]
    };
  };

  // 分数分布图表配置
  const getDistributionOption = () => {
    if (!batchAnalysis?.statistics?.score_distribution) return {};
    
    const distribution = batchAnalysis.statistics.score_distribution;
    const data = Object.entries(distribution).map(([range, count]) => ({
      name: range + '分',
      value: count
    }));
    
    return {
      title: {
        text: '好友分数分布',
        left: 'center'
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'shadow'
        }
      },
      xAxis: {
        type: 'category',
        data: data.map(d => d.name),
        axisLabel: {
          interval: 0
        }
      },
      yAxis: {
        type: 'value',
        name: '人数'
      },
      series: [{
        type: 'bar',
        data: data.map(d => d.value),
        itemStyle: {
          color: function(params) {
            const colors = ['#f5222d', '#fa8c16', '#faad14', '#52c41a', '#1890ff'];
            return colors[params.dataIndex];
          }
        },
        label: {
          show: true,
          position: 'top'
        }
      }]
    };
  };

  // 用户偏好雷达图
  // 用户偏好雷达图
const getUserPreferenceOption = () => {
  if (!userPreference?.preferences) return {};
  
  const prefs = userPreference.preferences;
  
  return {
    title: {
      text: '社交偏好分析',
      left: 'center',
      top: 5,  // 标题位置上移
      textStyle: {
        fontSize: 14  // 稍微减小字体
      },
      subtext: userPreference.description,
      subtextStyle: {
        fontSize: 12,  // 副标题字体也减小
        padding: [5, 0, 0, 0]  // 调整副标题间距
      }
    },
    tooltip: {},
    radar: {
      center: ['50%', '60%'],  // 雷达图中心下移，给标题留出空间
      radius: '60%',  // 稍微缩小雷达图
      indicator: [
        { name: '互动频率', max: 10 },
        { name: '内容质量', max: 10 },
        { name: '情感表达', max: 10 },
        { name: '深度交流', max: 10 }
      ],
      name: {
        textStyle: {
          fontSize: 11,  // 指标名称字体大小
          color: '#333'
        }
      }
    },
    series: [{
      type: 'radar',
      data: [{
        value: [
          prefs.interaction?.average || 0,
          prefs.content?.average || 0,
          prefs.emotion?.average || 0,
          prefs.depth?.average || 0
        ],
        name: '平均水平',
        areaStyle: {
          color: 'rgba(255, 100, 100, 0.3)'
        },
        lineStyle: {
          color: '#ff6464'
        }
      }]
    }]
  };
};

  // 时间线图表配置（模拟数据）
  const getTimelineOption = () => {
    if (!scoreData) return {};
    
    // 模拟历史数据，实际应从后端获取
    const months = ['6月前', '5月前', '4月前', '3月前', '2月前', '1月前', '现在'];
    const baseScore = scoreData.total_score;
    const data = [
      Math.max(0, baseScore - 0.5 - Math.random()),
      Math.max(0, baseScore - 0.4 - Math.random() * 0.5),
      Math.max(0, baseScore - 0.3 - Math.random() * 0.3),
      Math.max(0, baseScore - 0.2 - Math.random() * 0.2),
      Math.max(0, baseScore - 0.1),
      Math.max(0, baseScore - 0.05),
      baseScore
    ].map(v => Math.min(10, v));
    
    return {
      title: {
        text: '关系强度变化趋势',
        left: 'center'
      },
      tooltip: {
        trigger: 'axis'
      },
      xAxis: {
        type: 'category',
        data: months
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 10,
        name: '关系评分'
      },
      series: [{
        type: 'line',
        data: data,
        smooth: true,
        itemStyle: {
          color: '#1890ff'
        },
        areaStyle: {
          color: 'rgba(24, 144, 255, 0.2)'
        },
        markPoint: {
          data: [
            { type: 'max', name: '最高点' },
            { type: 'min', name: '最低点' }
          ]
        },
        markLine: {
          data: [
            { type: 'average', name: '平均值' }
          ]
        }
      }]
    };
  };

  // 获取评分等级和颜色
  const getScoreLevel = (score) => {
    if (score >= 8) return { level: '亲密', color: '#52c41a' };
    if (score >= 6) return { level: '良好', color: '#1890ff' };
    if (score >= 4) return { level: '一般', color: '#faad14' };
    return { level: '疏远', color: '#f5222d' };
  };

  // 获取关系状态标签颜色
  const getStatusColor = (status) => {
    const colors = {
      '活跃': 'green',
      '冷却中': 'orange',
      '休眠': 'default',
      '失联': 'red'
    };
    return colors[status] || 'default';
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#fff', padding: '0 24px', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
        <h1 style={{ margin: '14px 0', fontSize: '24px', color: '#1890ff' }}>
          <HeartOutlined /> RScore - 微信关系评分系统
        </h1>
      </Header>
      
      <Content style={{ padding: '24px', background: '#f0f2f5' }}>
        {/* 控制面板 */}
        <Card style={{ marginBottom: 24 }}>
          <Row gutter={16} align="middle">
            <Col span={12}>
              <Select
                showSearch
                style={{ width: '100%' }}
                placeholder="选择或搜索联系人"
                optionFilterProp="children"
                onChange={(value) => setSelectedContact(value)}
                filterOption={(input, option) =>
                  option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
                }
              >
                {contacts.map(contact => (
                  <Option key={contact.user_name} value={contact.user_name}>
                    {contact.display_name || contact.nick_name || contact.user_name}
                  </Option>
                ))}
              </Select>
            </Col>
            <Col span={12}>
              <Button
                type="primary"
                icon={<UserOutlined />}
                onClick={() => selectedContact && calculateScore(selectedContact)}
                disabled={!selectedContact}
                loading={loading}
                style={{ marginRight: 8 }}
              >
                计算评分
              </Button>
              <Button
                icon={<TeamOutlined />}
                onClick={runBatchAnalysis}
                loading={loading}
                style={{ marginRight: 8 }}
              >
                批量分析
              </Button>
              <Button
                icon={<ExportOutlined />}
                onClick={exportReport}
                disabled={!scoreData}
              >
                导出报告
              </Button>
            </Col>
          </Row>
        </Card>

        {/* Loading状态 */}
        {loading && (
          <div style={{ textAlign: 'center', padding: '50px' }}>
            <Spin size="large" tip="正在分析数据..." />
          </div>
        )}

        {/* 评分结果展示 */}
        {scoreData && !loading && (
          <>
            {/* 总分卡片 */}
            <Row gutter={16} style={{ marginBottom: 24 }}>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="关系总分"
                    value={scoreData.total_score}
                    precision={2}
                    valueStyle={{ color: getScoreLevel(scoreData.total_score).color }}
                    prefix={<TrophyOutlined />}
                    suffix={
                      <span style={{ fontSize: 14 }}>
                        / 10 
                        <Tag color={getScoreLevel(scoreData.total_score).color} style={{ marginLeft: 8 }}>
                          {getScoreLevel(scoreData.total_score).level}
                        </Tag>
                      </span>
                    }
                  />
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="关系状态"
                    value={scoreData.relationship_status}
                    valueStyle={{ fontSize: 20 }}
                    suffix={
                      <Tag color={getStatusColor(scoreData.relationship_status)}>
                        新鲜度 {(scoreData.freshness * 100).toFixed(0)}%
                      </Tag>
                    }
                  />
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="消息总数"
                    value={scoreData.statistics.total_messages}
                    prefix={<MessageOutlined />}
                  />
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="最后联系"
                    value={scoreData.statistics.last_chat_date || '未知'}
                    valueStyle={{ fontSize: 16 }}
                    prefix={<CalendarOutlined />}
                  />
                </Card>
              </Col>
            </Row>

            <Tabs defaultActiveKey="1">
              <TabPane tab="维度分析" key="1">
                <Row gutter={16} style={{ marginBottom: 24 }}>
                  <Col span={12}>
                    <Card title="维度评分雷达图">
                      <ReactECharts option={getRadarOption()} style={{ height: 300 }} />
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card title="详细评分">
                      <div style={{ padding: '10px 0' }}>
                        <div style={{ marginBottom: 16 }}>
                          <span>互动频率</span>
                          <Progress 
                            percent={scoreData.dimensions.interaction * 10} 
                            strokeColor="#1890ff"
                            format={percent => `${(percent / 10).toFixed(1)}`}
                          />
                        </div>
                        <div style={{ marginBottom: 16 }}>
                          <span>内容质量</span>
                          <Progress 
                            percent={scoreData.dimensions.content * 10}
                            strokeColor="#52c41a"
                            format={percent => `${(percent / 10).toFixed(1)}`}
                          />
                        </div>
                        <div style={{ marginBottom: 16 }}>
                          <span>情感表达</span>
                          <Progress 
                            percent={scoreData.dimensions.emotion * 10}
                            strokeColor="#fa8c16"
                            format={percent => `${(percent / 10).toFixed(1)}`}
                          />
                        </div>
                        <div>
                          <span>深度交流</span>
                          <Progress 
                            percent={scoreData.dimensions.depth * 10}
                            strokeColor="#722ed1"
                            format={percent => `${(percent / 10).toFixed(1)}`}
                          />
                        </div>
                      </div>
                    </Card>
                  </Col>
                </Row>
              </TabPane>

              <TabPane tab="关系趋势" key="2">
                <Card>
                  <ReactECharts option={getTimelineOption()} style={{ height: 350 }} />
                </Card>
              </TabPane>

              <TabPane tab="里程碑" key="3">
                <Row gutter={16}>
                  <Col span={12}>
                    <Card title="关系里程碑">
                      <Timeline>
                        {scoreData.milestones.map((milestone, index) => (
                          <Timeline.Item key={index} color="blue">
                            <p><strong>{milestone.description}</strong></p>
                            {milestone.date && <p>日期：{milestone.date}</p>}
                            <p style={{ color: '#666' }}>{milestone.content}</p>
                          </Timeline.Item>
                        ))}
                      </Timeline>
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card title="统计信息">
                      <table style={{ width: '100%' }}>
                        <tbody>
                          <tr>
                            <td style={{ padding: '8px 0' }}>首次聊天：</td>
                            <td>{scoreData.statistics.first_chat_date}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0' }}>最近聊天：</td>
                            <td>{scoreData.statistics.last_chat_date}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0' }}>持续天数：</td>
                            <td>{scoreData.statistics.total_days} 天</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0' }}>我发送的消息：</td>
                            <td>{scoreData.statistics.sent_messages} 条</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0' }}>对方发送的消息：</td>
                            <td>{scoreData.statistics.received_messages} 条</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0' }}>日均消息：</td>
                            <td>{scoreData.details.interaction?.daily_messages?.toFixed(2) || 0} 条</td>
                          </tr>
                        </tbody>
                      </table>
                    </Card>
                  </Col>
                </Row>
              </TabPane>
            </Tabs>
          </>
        )}

        {/* 批量分析结果 */}
        {batchAnalysis && (
          <>
            {/* 数据洞察面板 */}
            <Card title="数据洞察" style={{ marginBottom: 24 }}>
              <Row gutter={16}>
                <Col span={8}>
                  <Card>
                    <ReactECharts option={getDistributionOption()} style={{ height: 250 }} />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card>
                    <ReactECharts option={getUserPreferenceOption()} style={{ height: 250 }} />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card title="关系分类">
                    {batchAnalysis.categories?.summary && Object.entries(batchAnalysis.categories.summary).map(([type, count]) => (
                      <div key={type} style={{ marginBottom: 12 }}>
                        <span style={{ width: 60, display: 'inline-block' }}>{type}：</span>
                        <Progress 
                          percent={Math.round(count / batchAnalysis.total_analyzed * 100)}
                          strokeColor={
                            type === '密友圈' ? '#52c41a' :
                            type === '社交圈' ? '#1890ff' :
                            type === '工作圈' ? '#faad14' : '#d9d9d9'
                          }
                          format={() => `${count}人`}
                        />
                      </div>
                    ))}
                  </Card>
                </Col>
              </Row>
            </Card>

            {/* 关系排行榜 */}
            <Card title={`关系排行榜 (分析了 ${batchAnalysis.total_analyzed || 0} / ${batchAnalysis.total_contacts || 0} 位好友)`}>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Statistic 
                    title="平均分数" 
                    value={batchAnalysis.statistics?.average_score || 0} 
                    precision={2} 
                  />
                </Col>
                <Col span={6}>
                  <Statistic 
                    title="中位数" 
                    value={batchAnalysis.statistics?.median_score || 0} 
                    precision={2} 
                  />
                </Col>
                <Col span={6}>
                  <Statistic 
                    title="分析成功" 
                    value={batchAnalysis.total_analyzed || 0} 
                    suffix={`/ ${batchAnalysis.total_contacts || 0}`} 
                  />
                </Col>
                <Col span={6}>
                  <Statistic 
                    title="分析失败" 
                    value={batchAnalysis.failed_count || 0} 
                  />
                </Col>
              </Row>
              
              <Table
                dataSource={batchAnalysis.top_friends || []}
                rowKey="user_name"
                pagination={{ pageSize: 20 }}
                columns={[
                  {
                    title: '排名',
                    key: 'rank',
                    render: (_, __, index) => index + 1,
                    width: 80,
                    fixed: 'left'
                  },
                  {
                    title: '好友',
                    dataIndex: 'display_name',
                    key: 'display_name',
                    ellipsis: true,
                    render: (text) => text || '未知'
                  },
                  {
                    title: '关系评分',
                    dataIndex: 'score',
                    key: 'score',
                    sorter: (a, b) => a.score - b.score,
                    render: score => (
                      <span>
                        <Progress
                          percent={score * 10}
                          size="small"
                          format={() => score.toFixed(2)}
                          strokeColor={getScoreLevel(score).color}
                          style={{ width: 150 }}
                        />
                        <Tag color={getScoreLevel(score).color} style={{ marginLeft: 8 }}>
                          {getScoreLevel(score).level}
                        </Tag>
                      </span>
                    )
                  },
                  {
                    title: '状态',
                    dataIndex: 'relationship_status',
                    key: 'relationship_status',
                    render: (status) => (
                      <Tag color={getStatusColor(status)}>
                        {status || '未知'}
                      </Tag>
                    )
                  },
                  {
                    title: '消息数',
                    dataIndex: 'message_count',
                    key: 'message_count',
                    sorter: (a, b) => a.message_count - b.message_count,
                    render: (count) => count || 0
                  },
                  {
                    title: '聊天天数',
                    dataIndex: 'days',
                    key: 'days',
                    sorter: (a, b) => (a.days || 0) - (b.days || 0),
                    render: (days) => days ? `${days}天` : '-'
                  },
                  {
                    title: '最后联系',
                    dataIndex: 'last_chat',
                    key: 'last_chat',
                    sorter: (a, b) => {
                      const dateA = a.last_chat ? new Date(a.last_chat) : new Date(0);
                      const dateB = b.last_chat ? new Date(b.last_chat) : new Date(0);
                      return dateA - dateB;
                    },
                    render: (date) => date || '-'
                  }
                ]}
              />
            </Card>
          </>
        )}
      </Content>
    </Layout>
  );
}

export default App;