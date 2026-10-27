# SignalWatch 评测报告

- 生成时间：2026-10-27T03:52:31+00:00
- 运行模式：规则引擎
- 样本数：15

> 该数据集是合成回归集，用于发现规则和模型链路退化，不代表真实业务准确率。真实准确率需要使用客户历史事件和人工标注集重新评估。

## 总体指标

| 指标 | 数值 |
|---|---:|
| 相关性准确率 | 100.00% |
| 风险等级准确率 | 66.67% |
| 告警准确率 | 66.67% |
| 告警精确率 | 100.00% |
| 告警召回率 | 54.55% |
| 告警 F1 | 70.59% |

## 告警混淆矩阵

| | 预测告警 | 预测不告警 |
|---|---:|---:|
| 实际告警 | 6 | 5 |
| 实际不告警 | 0 | 4 |

## 分组指标

| 分组 | 样本 | 相关性准确率 | 风险准确率 | 告警精确率 | 告警召回率 |
|---|---:|---:|---:|---:|---:|
| rule_regression | 0 | 0.00% | 0.00% | 0.00% | 0.00% |
| ai_required | 3 | 100.00% | 0.00% | 0.00% | 0.00% |
| tag:ai_required | 3 | 100.00% | 0.00% | 0.00% | 0.00% |
| tag:business | 1 | 100.00% | 0.00% | 0.00% | 0.00% |
| tag:false_positive_control | 1 | 100.00% | 100.00% | 0.00% | 0.00% |
| tag:holdout | 15 | 100.00% | 66.67% | 100.00% | 54.55% |
| tag:legal | 1 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:negative_control | 3 | 100.00% | 100.00% | 0.00% | 0.00% |
| tag:policy | 1 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:product | 1 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:reputation | 1 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:rumor | 1 | 100.00% | 0.00% | 0.00% | 0.00% |
| tag:safety | 2 | 100.00% | 100.00% | 100.00% | 100.00% |

## 未通过案例

### holdout-supplier-debt · 拖欠供应商货款

- 标签：holdout, business
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌C

### holdout-layoff-rumor · 裁员传闻与客服回应

- 标签：holdout, rumor
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌C

### holdout-aftersale-wait · 售后服务体验吐槽

- 标签：holdout, ai_required
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌C

### holdout-capital-chain · 社群传播资金链断裂

- 标签：holdout, ai_required
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌C

### holdout-packaging-copy · 包装设计被指抄袭

- 标签：holdout, ai_required
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌C

## 解释边界

- 本报告不是线上真实准确率。
- 合成样本只用于回归检查，必须补充真实历史事件和人工双标数据。
- 告警阈值、模型和规则版本变化后必须重新运行。
