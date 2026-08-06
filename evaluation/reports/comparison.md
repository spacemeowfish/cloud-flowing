# Agent Platform 模型对比评测报告

评测日期：2026-07-28
评测用例：50 条固定中文评测集
差距列统一按“Qwen - DeepSeek”计算。准确率使用百分点，延迟使用毫秒。

## 总览

| 指标 | DeepSeek V4 Flash | Qwen2.5-3B 本地 | 差距 |
|---|---:|---:|---:|
| 意图准确率 | 96.0% | 94.0% | -2.0 个百分点 |
| 参数提取准确率 | 96.0% | 68.0% | -28.0 个百分点 |
| 工具选择准确率 | 96.0% | 94.0% | -2.0 个百分点 |
| Schema 合规率 | 100.0% | 100.0% | +0.0 个百分点 |
| P50 延迟 | 1549.1 ms | 532.8 ms | -1016.3 ms |
| P95 延迟 | 3852.0 ms | 641.6 ms | -3210.4 ms |
| P99 延迟 | 4809.0 ms | 1121.7 ms | -3687.3 ms |
| 失败用例数 | 2 | 16 | +14 |

## 分意图准确率

| 意图 | DeepSeek | Qwen | 差距 |
|---|---:|---:|---:|
| file_open | 100.0% | 90.0% | -10.0 个百分点 |
| knowledge_query | 100.0% | 100.0% | +0.0 个百分点 |
| meeting_process | 90.0% | 100.0% | +10.0 个百分点 |
| reminder_create | 90.0% | 80.0% | -10.0 个百分点 |
| text_polish | 100.0% | 100.0% | +0.0 个百分点 |

## 延迟与异常指标

- Qwen2.5-3B 参数提取准确率低于 80%（68.0%）

## 失败用例分析

| 用例 ID | 输入文本 | 期望意图 | DeepSeek 实际 | Qwen 实际 |
|---|---|---|---|---|
| file-04 | 找会议记录 | file_open | 通过 | meeting_process（intent, arguments, tool） |
| file-06 | 打开 readme.md | file_open | 通过 | file_open（arguments） |
| knowledge-01 | 查询产品保修期 | knowledge_query | 通过 | knowledge_query（arguments） |
| knowledge-03 | 告诉我设备重启方法 | knowledge_query | 通过 | knowledge_query（arguments） |
| knowledge-04 | 公司报销标准是什么 | knowledge_query | 通过 | knowledge_query（arguments） |
| knowledge-05 | 知识库里有安全规范吗 | knowledge_query | 通过 | knowledge_query（arguments） |
| knowledge-06 | 查询售后联系电话 | knowledge_query | 通过 | knowledge_query（arguments） |
| knowledge-07 | 查一下版本发布流程 | knowledge_query | 通过 | knowledge_query（arguments） |
| meeting-01 | 整理会议纪要 C:\demo\m1.txt | meeting_process | 通过 | meeting_process（arguments） |
| meeting-03 | 会议文稿在 C:\docs\周会.txt | meeting_process | file_open（intent, arguments, tool） | 通过 |
| meeting-06 | 请整理会议记录 C:\data\销售会.md | meeting_process | 通过 | meeting_process（arguments） |
| reminder-04 | 查看未来7天待办 | reminder_create | 通过 | reminder_create（arguments） |
| reminder-06 | 取消提醒 12 | reminder_create | 通过 | reminder_create（arguments） |
| reminder-08 | 日程：后天下午2点客户拜访 | reminder_create | 通过 | meeting_process（intent, arguments, tool） |
| reminder-09 | 查看我的日程 | reminder_create | file_open（intent, arguments, tool） | knowledge_query（intent, arguments, tool） |
| text-04 | 缩写：这是一段需要压缩的长文本 | text_polish | 通过 | text_polish（arguments） |
| text-05 | 总结这段：本季度完成了三个项目 | text_polish | 通过 | text_polish（arguments） |

## 结论与建议

- 本地 Qwen 意图准确率 94.0%，云端 DeepSeek 96.0%，差距 -2.0 个百分点。
- DeepSeek P95 延迟 3852.0 ms；Qwen P95 延迟 641.6 ms。
- Qwen 可承担本地意图识别，但仍应保留云端回退与 Schema 校验。
- 生产决策仍需在目标 RK3588 板卡上复测吞吐、内存、温升和并发；本报告仅代表当前 Windows/Ollama 环境。
