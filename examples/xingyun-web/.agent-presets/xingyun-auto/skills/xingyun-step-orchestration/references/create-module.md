# 创建模块

#### 触发条件
用户意图匹配"创建模块"，且必填参数（`moduleName`、`parentModuleName`）均已提取到。并且需要把必填参数（`moduleName`、`parentModuleName`）填入到下面的 JSON 中，替换掉 ${input.moduleName} 和 ${input.parentModuleName}。
#### 步骤返回格式
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
    "description": "创建模块",
    "action": "GET",
    "url": "/online/cstformtree/add",
    "params": {
      "name": "${input.moduleName}",
      "pid": "${step1.moduleId}"
    }
  }
]
```
