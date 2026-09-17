# 创建菜单

#### 触发条件
用户意图匹配“创建菜单”，且必填参数（`menuName`、`parentMenuName`）均已提取到。
#### 步骤返回格式（当 formCode 未提供时）
若用户未提供 `formCode`，AI 必须返回以下 JSON 数组。注意 Step 2 中的 `${PENDING:formCode}` 和 `pendingParam` 字段。
*(注：若用户首次输入已包含 formCode，则将 `${PENDING:formCode}` 替换为 `${input.formCode}`，并移除 `pendingParam` 字段)*
```json
[
  {
    "stepIndex": 1,
    "description": "查询上级菜单信息",
    "action": "GET",
    "url": "/sys/permission/list",
    "params": {
      "name": "${input.parentMenuName}"
    },
    "extractFields": {
      "parentId": "$.result[0].id"
    }
  },
  {
    "stepIndex": 2,
    "description": "查询设计表单信息（⏳ 等待用户提供表单编码）",
    "action": "GET",
    "url": "/online/cgform/page",
    "params": {
      "code": "${PENDING:formCode}"
    },
    "extractFields": {
      "cgformTreeId": "$.result.records[0].treeId",
      "component": "$.result.records[0].code",
      "cgformId": "$.result.records[0].id",
      "urlPathCode": "$.result.records[0].code"
    },
    "pendingParam": "formCode"
  },
  {
    "stepIndex": 3,
    "description": "保存菜单",
    "action": "POST",
    "url": "/sys/permission/add",
	"paramsType": "json",
    "params": {
      "menuType": 1,
      "name": "${input.menuName}",
      "parentId": "${step1.parentId}",
      "designType": 0,
      "cgformTreeId": "${step2.cgformTreeId}",
      "component": "${step2.component}",
      "cgformId": "${step2.cgformId}",
      "cstPortalId": "",
      "url": "/${step2.urlPathCode}",
      "icon": "",
      "sortNo": null,
      "route": true,
      "hidden": false,
      "keepAlive": false,
      "alwaysShow": false,
      "internalOrExternal": false,
      "appIcon": null
    }
  }
]
```
