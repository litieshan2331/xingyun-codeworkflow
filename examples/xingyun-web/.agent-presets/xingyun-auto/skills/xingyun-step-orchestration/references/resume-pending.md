# 多轮补全（resolvePending 增量指令）

## 5. 多轮补全交互协议
### 5.1 用户补充参数时的 AI 响应格式
当流程处于待补充状态（前端已暂停在某步骤），用户后续补充任意缺失参数时，AI **不要**重新返回完整的步骤数组，而是统一返回以下**增量更新指令**结构：
```json
{
  "updateType": "resolvePending",
  "targetStep": "<触发PENDING的步骤索引>",
  "resolvedParams": {
    "<参数标识>": "<用户提供的实际值>"
  },
  "instruction": "请将 Step <N> 的 params.<字段名> 替换为 '<实际值>'，清除 pendingParam 字段，然后继续执行 Step <N> 及后续步骤。"
}
```
场景示例一：补充 formCode（创建菜单）
用户输入“code是flood_supplies”时，AI 返回：
```json
{
  "updateType": "resolvePending",
  "targetStep": 2,
  "resolvedParams": {
    "formCode": "flood_supplies"
  },
  "instruction": "请将 Step 2 的 params.code 替换为 'flood_supplies'，清除 pendingParam 字段，然后继续执行 Step 2 及后续步骤。"
}
```
场景示例二：补充 appName（发布应用）
用户输入“发布防汛管理应用”时，AI 返回：
```json
{
  "updateType": "resolvePending",
  "targetStep": 2,
  "resolvedParams": {
    "appName": "防汛管理应用"
  },
  "instruction": "请将 Step 2 的 params.name 替换为 '防汛管理应用'，清除 pendingParam 字段，然后继续执行 Step 2 及后续步骤。"
}
```
### 5.2 前端处理规则（供前端开发参考）
- 收到含 ${PENDING:xxx} 的步骤时，正常执行前置步骤，到达该步骤时暂停执行链。
- 向用户展示提示信息（取自该步骤的 description 字段）。
- 监听用户后续输入，若 AI 返回 resolvePending 类型响应，则替换对应步骤参数值并恢复执行链。
- skipCondition 处理：若步骤包含 skipCondition 字段，前端需在执行前评估该表达式，结果为 true 时跳过该步骤，并使用 fallbackExtract 中的值作为后续步骤的依赖。
- recordCount = 0 中断：前端在 Step1 完成后检查 recordCount，若为 0 则中断流程并向用户提示“未找到任何应用，请先创建应用”。
- FormData 处理：当步骤的 paramsType 为 formdata 时，前端需将 params 对象转换为 FormData 实例后再发送请求。
