# 星云 Web preset

[English](README.md) | 中文

本示例为 DSH Web 增加星云 Agent Preset，不修改独立星云接口脚本及其 Cordis 组合。

## 启动 Web

完成项目构建后，从仓库根目录运行：

```powershell
pnpm run build
$env:DSH_HOME = (Resolve-Path ".\examples\xingyun-web").Path
pnpm dsh web --patch ".\examples\xingyun-web\xingyun-web.cordis.yml" --no-open
```

Web 进程会从 `$DSH_HOME/.agent-presets` 发现 preset。请在新建对话前选择 preset；对话启动后会固定使用创建时选择的 preset。

此 overlay 启用官方 `compaction-basic`、`tool-result-pruner` 和 `command-compact`。自动压缩和工具结果剪枝独立作用于每个 Web 会话，不会在不同 preset 或会话之间混合历史；空闲时可输入 `/compact` 手动压缩当前会话。

## Preset
- `xingyun-js` 检索 JS 知识库，并修改当前工作区中的一个 JavaScript 文件。
- `xingyun-auto` 是一个同时拥有三组带前缀 WeKnora 工具的 Agent。它根据用户文字和图片选择 list 或 form，只使用选中的页面知识库；只有用户明确要求 JavaScript 行为时才使用 JS 知识库。

Web preset 组合负责面向模型的 persona 和工具。overlay 负责共享 vLLM 路由、preset 名单以及宿主侧 JS 子 runtime provider。Web UI 及其 Host API 继续负责会话状态、工作区访问和文件展示。


## 环境变量

模型和 WeKnora 凭据从 DSH 的正常环境或 `.env` 文件读取。overlay 需要 `VLLM_BASE_URL`、`VLLM_API_KEY`、`WEKNORA_BASE_URL`、`WEKNORA_API_KEY` 以及三个 `XINGYUN_*_KB_ID` 变量。
