# SignalWatch 评测报告

- 生成时间：2026-10-27T03:32:20+00:00
- 运行模式：规则引擎
- 样本数：23

> 该数据集是合成回归集，用于发现规则和模型链路退化，不代表真实业务准确率。真实准确率需要使用客户历史事件和人工标注集重新评估。

## 总体指标

| 指标 | 数值 |
|---|---:|
| 相关性准确率 | 100.00% |
| 风险等级准确率 | 86.96% |
| 告警准确率 | 86.96% |
| 告警精确率 | 100.00% |
| 告警召回率 | 80.00% |
| 告警 F1 | 88.89% |

## 告警混淆矩阵

| | 预测告警 | 预测不告警 |
|---|---:|---:|
| 实际告警 | 12 | 3 |
| 实际不告警 | 0 | 8 |

## 分组指标

| 分组 | 样本 | 相关性准确率 | 风险准确率 | 告警精确率 | 告警召回率 |
|---|---:|---:|---:|---:|---:|
| rule_regression | 19 | 100.00% | 100.00% | 100.00% | 100.00% |
| ai_required | 4 | 100.00% | 25.00% | 0.00% | 0.00% |
| tag:ai_required | 4 | 100.00% | 25.00% | 0.00% | 0.00% |
| tag:business | 1 | 100.00% | 100.00% | 0.00% | 0.00% |
| tag:false_positive_control | 2 | 100.00% | 100.00% | 0.00% | 0.00% |
| tag:legal | 2 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:negative_control | 5 | 100.00% | 100.00% | 0.00% | 0.00% |
| tag:policy | 2 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:product | 3 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:prompt_injection | 1 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:reputation | 2 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:rule_regression | 19 | 100.00% | 100.00% | 100.00% | 100.00% |
| tag:rumor | 2 | 100.00% | 50.00% | 100.00% | 50.00% |
| tag:safety | 3 | 100.00% | 66.67% | 100.00% | 66.67% |
| tag:sarcasm | 1 | 100.00% | 0.00% | 0.00% | 0.00% |

## 未通过案例

### sarcasm-complaint · 讽刺表达隐含售后投诉

- 标签：ai_required, sarcasm
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌A

### implicit-safety · 未使用明确事故词的安全隐患

- 标签：ai_required, safety
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌A

### unverified-collapse · 社群传播的未证实倒闭消息

- 标签：ai_required, rumor
- 预期：relevance=True, risk=medium, alert=True
- 实际：relevance=True, risk=low, alert=False
- 匹配词：品牌A

## 解释边界

- 本报告不是线上真实准确率。
- 合成样本只用于回归检查，必须补充真实历史事件和人工双标数据。
- 告警阈值、模型和规则版本变化后必须重新运行。
