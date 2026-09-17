# 创建表单

#### 触发条件
用户意图匹配"创建表单"，且必填参数（`formName`、`parentModuleName`）均已提取到。
#### 步骤返回格式
**code 字段取值优先级说明：**
- 用户显式提供 formCode → 使用 `${input.formCode}`
- 用户未提供 → 系统根据 `formName` 逐字转拼音、用 `'_'` 拼接自动生成（如"防汛物品信息" → `fang_xun_wu_pin_xin_xi`）
**说明：创建表单不存在 formCode 缺失/PENDING 的情况。**模板中的 `"code": "pinyin(${input.formName})"` 是**生成记法，不是最终写法**：它表示"此处填写 `formName` 的拼音"。

**场景一：用户未提供 formCode（code 根据 formName 自动生成）**
```json
[
  {
    "stepIndex": 1,
    "description": "查询模块节点信息",
    "action": "GET",
    "url": "/online/cstformtree/list",
    "params": {
      "name": "${input.parentModuleName}"
    },
    "extractFields": {
      "moduleId": "$.result[0].id"
    }
  },
  {
    "stepIndex": 2,
    "description": "创建表单（code 将根据 formName 自动生成）",
    "action": "POST",
    "url": "/online/cgform/saveOrUpdateForm",
    "paramsType": "json",
    "params": {
      "name": "${input.formName}",
      "code": "pinyin(${input.formName})",
      "treeId": "${step1.moduleId}",
      "isFlow": "${input.isFlow}"
    }
  }
]
```
**场景二：用户提供了 formCode**
```json
[
  {
    "stepIndex": 1,
    "description": "查询模块节点信息",
    "action": "GET",
    "url": "/online/cstformtree/list",
    "params": {
      "name": "${input.parentModuleName}"
    },
    "extractFields": {
      "moduleId": "$.result[0].id"
    }
  },
  {
    "stepIndex": 2,
    "description": "创建表单",
    "action": "POST",
    "url": "/online/cgform/saveOrUpdateForm",
    "paramsType": "json",
    "params": {
      "name": "${input.formName}",
      "code": "${input.formCode}",
      "treeId": "${step1.moduleId}",
      "isFlow": "${input.isFlow}"
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
