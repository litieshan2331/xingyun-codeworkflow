# 发布应用

#### 触发条件
用户意图匹配“发布应用”。无需任何初始参数即可触发。
业务逻辑说明
- 首次查询应用列表时不传 name 参数。
- 若返回记录数 "recordCount" = 0，中断流程并提示用户先创建应用。
- 若返回记录数 "recordCount" = 1，直接使用 records[0].id 进入 step3。
- 若返回记录数 "recordCount" > 1，暂停流程并通过 PENDING 机制追问用户具体应用名称，用户补充后重新查询。
- 获取应用详情后，**必须请求完整菜单树**（不传 name），并通过 `postProcess` 二次加工提取发布所需的菜单数据。
- 使用应用详情中的字段和菜单树数据组装 FormData 并发布。
- fallbackExtract 说明：当步骤被 skipCondition 跳过时，前端应从 fallbackExtract 中获取替代值。例如 Step3 被跳过时，appId 回退使用 Step1 提取的值。 例如：若Step2 可能被跳过，Step3 应使用 ${step1.appId} 而非 ${step2.appId}。
#### 步骤返回格式
```json
[
  {
    "stepIndex": 1,
    "description": "查询应用列表",
    "action": "GET",
    "url": "/online/app/page",
    "params": {},
    "extractFields": {
      "appId": "$.result.records[0].id",
      "recordCount": "$.result.records.length"
    },
    "abortCondition": {
    "expression": "${step1.recordCount} == 0",
    "userMessage": "当前未找到任何可发布的应用，请先创建应用后再尝试发布。",
    "feedbackToAI": "NO_APP_FOUND: 用户环境下没有可用应用，流程已终止。"
    }
  },
  {
    "stepIndex": 2,
    "description": "精确查询应用（⏳ 存在多个应用，等待用户指定应用名称）",
    "action": "GET",
    "url": "/online/app/page",
    "params": {
      "name": "${PENDING:appName}"
    },
    "extractFields": {
      "appId": "$.result.records[0].id"
    },
    "skipCondition": "${step1.recordCount} <= 1",
    "pendingParam": "appName"
  },
  {
    "stepIndex": 3,
    "description": "获取应用详情",
    "action": "GET",
    "url": "/online/app/queryById",
    "params": {
      "id": "${step2.appId}"
    },
    "extractFields": {
      "appDetail": "$.result.app",
      "menuIds": "$.result.menuIds"
    },
    "fallbackExtract": {
      "appId": "${step1.appId}"
    }
  },
  {
    "stepIndex": 4,
    "description": "获取完整菜单树",
    "action": "GET",
    "url": "/sys/permission/list",
    "params": {},
	"postProcess": "extractPublishMenuInfo",
    "extractFields": {
      "menuId": "$.menuId",
      "menuIds": "$.menuIds"
    }
  },
  {
    "stepIndex": 5,
    "description": "发布应用",
    "action": "POST",
    "paramsType": "formdata",
    "url": "/online/packpc/app/build",
    "params": {
      "id": "${step3.appDetail.id}",
      "menuId": "${step4.menuId}",
      "distDirectory": "${step3.appDetail.distDirectory}",
      "themeType": "${step3.appDetail.themeType}",
      "themeTypes": "${step3.appDetail.themeTypes}",
      "layoutItem": "${step3.appDetail.layoutItem}",
      "tablePageSize": "${step3.appDetail.tablePageSize}",
      "layout": "${step3.appDetail.layout}",
      "name": "${step3.appDetail.name}",
      "port": "${step3.appDetail.port}",
      "sysMenuRoleId": "",
      "picture_16481buid37812": "",
      "picture_16481buid37810": "",
      "menuIds": "${step4.menuIds}.join(',')",
      "modelIds": "${step3.appDetail.modelIds}",
      "describe": "${step3.appDetail.describe}",
      "type": "${step3.appDetail.type}",
      "navigationshow": "${step3.appDetail.navigationshow}",
      "menushow": "${step3.appDetail.menushow}",
      "headshow": "${step3.appDetail.headshow}",
      "fullyVersion": "${step3.appDetail.fullyVersion}",
      "isIteration": "Y",
      "releaseMode": "${step3.appDetail.releaseMode}"
    }
  }
]
```
extractFields 路径说明：使用简化的 JSONPath，$ 代表接口返回的 res.data。
- $.result.records[0].id → res.data.result.records[0].id
- $.result.records.length → res.data.result.records 数组的长度
- $.result.menuIds → res.data.result.menuIds（数组类型）
$.menuId / $.menuIds → 当步骤包含 postProcess 时，$ 代表后置处理方法返回的对象，而非原始接口响应
fallbackExtract 说明：当步骤被 skipCondition 跳过时，前端应从 fallbackExtract 中获取替代值。例如 Step3 被跳过时，appId 回退使用 Step1 提取的值。
postProcess 说明：当步骤包含 postProcess 字段时，前端需在获取接口原始响应后，调用对应的内置处理方法对数据进行二次加工。extractFields 中的路径基于加工后的返回结果进行提取。例如 Step 4 中 extractPublishMenuInfo 返回 { menuId, menuIds }，则提取路径为 $.menuId 和 $.menuIds
