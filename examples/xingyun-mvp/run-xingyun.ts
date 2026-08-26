/**
 * Drive the official root JSON-RPC runtime for one Xingyun request.
 *
 * The script owns only the file adapter and process lifecycle. Routing,
 * WeKnora calls, PTC execution, and list/form-to-JS delegation stay in the
 * runtime compositions.
 */

import { copyFile, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { extname, join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'

type XingyunMode = 'auto' | 'list' | 'form' | 'js'
type XingyunType = 'list' | 'form' | 'js'

/**
 * 调用方传给统一入口的请求体。
 *
 * 前端或中台 BFF 可以将同名字段组装为 JSON 后传给本脚本；图片和 JS
 * 文件字段当前是运行脚本机器可访问的本地路径。
 */
interface RequestInput {
  /** `auto` 由根 Agent 路由；其余值直接选择目标 Agent。 */
  mode: XingyunMode
  /** 用户的自然语言需求，也是列表或表单 Agent 生成字段和 funText 的依据。 */
  instruction: string
  /** 可选 UI 截图本地路径；根或列表/表单 Agent 通过 read_image 读取。 */
  imagePath?: string
  /** 仅适用于 `js` 或 `auto` 的原始 JS 文件本地路径，不能与 jsSource 同时提供。 */
  jsPath?: string
  /** 仅适用于 `js` 或 `auto` 的原始 JS 文本，不能与 jsPath 同时提供。 */
  jsSource?: string | null
  /** 可选星云目标版本；省略时 JS Agent 按自身默认版本处理。 */
  targetVersion?: string
}

interface PreparedRequest {
  request: Record<string, unknown>
  sourcePath: string | undefined
  outputPath: string
}

/**
 * 判断未知值是否为普通 JSON 对象。
 * @param value - 需要判断的未知值。
 * @returns 值为非数组对象时返回 true。
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * 读取可选字符串字段，并在字段类型不正确时中止请求。
 * @param value - JSON 请求中的字段值。
 * @param name - 用于报错的字段名称。
 * @returns 字段未提供时为 undefined，否则为原始字符串。
 */
function optionalString(value: unknown, name: string): string | undefined {
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'string') throw new Error(name + ' must be a string')
  return value
}

/**
 * 解析并检查调用方传入的统一星云请求。
 * @param raw - JSON 文本。
 * @returns 供统一入口使用的已检查请求字段。
 */
function parseRequest(raw: string): RequestInput {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch (error: unknown) {
    throw new Error('request must be valid JSON', { cause: error })
  }
  if (!isRecord(value)) throw new Error('request must be a JSON object')

  const mode = value.mode
  if (mode !== 'auto' && mode !== 'list' && mode !== 'form' && mode !== 'js') {
    throw new Error('request.mode must be auto, list, form, or js')
  }
  const instruction = value.instruction
  if (typeof instruction !== 'string' || instruction.trim().length === 0) {
    throw new Error('request.instruction must be a non-empty string')
  }

  const imagePath = optionalString(value.imagePath, 'request.imagePath')
  const jsPath = optionalString(value.jsPath, 'request.jsPath')
  const jsSource = value.jsSource === null || value.jsSource === undefined
    ? undefined
    : optionalString(value.jsSource, 'request.jsSource')
  const targetVersion = optionalString(value.targetVersion, 'request.targetVersion')
  if (jsPath !== undefined && jsSource !== undefined) {
    throw new Error('request.jsPath and request.jsSource are mutually exclusive')
  }
  return {
    mode,
    instruction,
    ...imagePath === undefined ? {} : { imagePath },
    ...jsPath === undefined ? {} : { jsPath },
    ...jsSource === undefined ? {} : { jsSource },
    ...targetVersion === undefined ? {} : { targetVersion },
  }
}

/**
 * 从标准输入完整读取 JSON 请求文本。
 * @returns 标准输入中的全部文本。
 */
async function readStandardInput(): Promise<string> {
  let result = ''
  for await (const chunk of process.stdin) result += String(chunk)
  return result
}

/**
 * 从命令行 JSON、请求文件或标准输入读取统一请求。
 * @param argument - JSON 字符串、JSON 文件路径，或表示标准输入的 -。
 * @returns 已检查的统一星云请求。
 */
async function readRequestArgument(argument: string): Promise<RequestInput> {
  const raw = argument.trimStart().startsWith('{')
    ? argument
    : argument === '-' ? await readStandardInput() : await readFile(argument, 'utf8')
  return parseRequest(raw)
}

/**
 * 创建本次调用的文件工作区，并将可选 JS 和图片复制为 Agent 可访问的临时文件。
 * @param input - 已检查的统一星云请求。
 * @param workspace - 本次调用独占的临时工作区。
 * @returns 传给根 Agent 的请求对象，以及最终文件的预期路径。
 */
async function prepareRequest(input: RequestInput, workspace: string): Promise<PreparedRequest> {
  const request: Record<string, unknown> = {
    mode: input.mode,
    instruction: input.instruction,
  }
  const outputPath = join(workspace, 'generated.json')
  const sourceText = input.jsPath === undefined
    ? input.jsSource
    : await readFile(resolve(input.jsPath), 'utf8')
  let sourcePath: string | undefined

  if ((input.mode === 'list' || input.mode === 'form') && sourceText !== undefined && sourceText !== null) {
    throw new Error('mode list or form does not accept request.jsPath or request.jsSource; its Agent creates funText')
  }
  if (sourceText !== undefined && sourceText !== null) {
    sourcePath = join(workspace, 'source.js')
    await writeFile(sourcePath, sourceText, 'utf8')
    request.sourcePath = sourcePath
  }
  if (input.mode === 'js' && sourcePath === undefined) {
    throw new Error('mode js requires request.jsSource or request.jsPath')
  }

  if (input.imagePath !== undefined) {
    const extension = extname(input.imagePath).toLowerCase()
    const imagePath = join(workspace, 'input-image' + extension)
    await copyFile(resolve(input.imagePath), imagePath)
    request.imagePath = imagePath
  }
  if (input.mode === 'list' || input.mode === 'form' || input.mode === 'auto') {
    request.outputPath = outputPath
  }
  if (input.targetVersion !== undefined && input.targetVersion.trim().length > 0) {
    request.targetVersion = input.targetVersion
  }

  return { request, sourcePath, outputPath }
}

/**
 * 从 JSON 文本中尝试解析一个对象或字符串形式的 JSON 对象。
 * @param text - 候选 JSON 文本。
 * @returns 解析出的 JSON 对象；无法解析时为 undefined。
 */
function parseJsonObject(text: string): Record<string, unknown> | undefined {
  try {
    const value: unknown = JSON.parse(text)
    if (isRecord(value)) return value
    if (typeof value === 'string' && value !== text) return parseJsonObject(value)
  } catch {
    // 候选文本可能只是模型说明的一部分，继续尝试其他候选范围。
  }
  return undefined
}

/**
 * 扫描文本中的平衡 JSON 对象范围，并避开字符串中的大括号。
 * @param text - 包含 JSON 或说明文字的文本。
 * @returns 从外层对象到内层对象的候选文本。
 */
function balancedJsonCandidates(text: string): string[] {
  const candidates: string[] = []
  for (let start = 0; start < text.length; start += 1) {
    if (text[start] !== '{') continue
    let depth = 0
    let inString = false
    let escaped = false
    for (let index = start; index < text.length; index += 1) {
      const char = text[index]
      if (inString) {
        if (escaped) escaped = false
        else if (char === '\\') escaped = true
        else if (char === '"') inString = false
        continue
      }
      if (char === '"') {
        inString = true
        continue
      }
      if (char === '{') depth += 1
      else if (char === '}') {
        depth -= 1
        if (depth === 0) {
          candidates.push(text.slice(start, index + 1))
          break
        }
      }
    }
  }
  return candidates
}

/**
 * 从模型文本中提取所有可解析 JSON 对象，兼容说明文字和被再次转义的 JSON。
 * @param text - Agent 返回的文本。
 * @returns 按文本出现顺序排列的 JSON 对象。
 */
function jsonObjectsFromText(text: string): Record<string, unknown>[] {
  const candidates = [text, ...balancedJsonCandidates(text)]
  const objects: Record<string, unknown>[] = []
  const seen = new Set<string>()
  for (const candidate of candidates) {
    const value = parseJsonObject(candidate.trim())
    if (value === undefined) continue
    const key = JSON.stringify(value)
    if (seen.has(key)) continue
    seen.add(key)
    objects.push(value)
  }
  return objects
}

/**
 * 按官方 dsh-tool-subagent 的前台结果约定提取子 Agent 最终文本。
 *
 * 官方前台结果为 { kind: "foreground", runId, output: JsonValue[] }；
 * 与该工具自身的 render 逻辑一致，只拼接 output 中 type 为 text 的块，
 * 不向调用方暴露 runId 或 reasoning 块。
 * @param value - 根 Agent 或 PTC 程序返回的 JSON 对象。
 * @returns 前台子 Agent 的最终文本；不是该官方包装对象时为 undefined。
 * @throws 前台结果不包含文本块时抛出。
 */
function foregroundSubagentText(value: Record<string, unknown>): string | undefined {
  if (value.kind !== 'foreground' || typeof value.runId !== 'string' || !Array.isArray(value.output)) {
    return undefined
  }
  const text = value.output
    .filter((block): block is Record<string, unknown> => isRecord(block))
    .filter(block => block.type === 'text' && typeof block.text === 'string')
    .map(block => block.text as string)
    .join('')
  if (text.length === 0) {
    throw new Error('foreground subagent result contained no text output')
  }
  return text
}

/**
 * 判断 JSON 对象是否符合星云对外响应语义。
 * @param value - 从模型文本提取的 JSON 对象。
 * @returns 对象是 completed、needs_input 或 processing 响应时返回 true。
 */
function isBusinessResponse(value: Record<string, unknown>): boolean {
  if (value.status === 'completed') {
    return value.type === 'list' || value.type === 'form' || value.type === 'js'
  }
  return value.status === 'needs_input' || value.status === 'processing'
}

/**
 * 从一个文本中提取业务响应，必要时解包官方前台子 Agent 结果。
 * @param text - 根 Agent 或子 Agent 的最终文本。
 * @returns 解析出的业务 JSON 对象；不存在时为 undefined。
 */
function businessResponseFromText(text: string): Record<string, unknown> | undefined {
  for (const response of jsonObjectsFromText(text)) {
    const childText = foregroundSubagentText(response)
    if (childText === undefined) {
      if (isBusinessResponse(response)) return response
      continue
    }
    const childResponse = businessResponseFromText(childText)
    if (childResponse !== undefined) return childResponse
  }
  return undefined
}

/**
 * 从官方 SDK 通知中的 assistant/message 事件提取最终文本。
 * @param notification - SDK 收集的服务端通知。
 * @returns 该事件的文本块拼接结果；不是 assistant/message 时为 undefined。
 */
function assistantTextFromNotification(notification: unknown): string | undefined {
  if (!isRecord(notification) || notification.method !== 'session.event' || !isRecord(notification.params)) {
    return undefined
  }
  const event = notification.params.event
  if (!isRecord(event) || event.type !== 'assistant/message' || !isRecord(event.data)) return undefined
  const message = event.data.message
  if (!isRecord(message) || !Array.isArray(message.content)) return undefined
  return message.content
    .filter((block): block is Record<string, unknown> => isRecord(block))
    .filter(block => block.type === 'text' && typeof block.text === 'string')
    .map(block => block.text as string)
    .join('')
}

/**
 * 从根回复和官方 SDK session 事件中确定本次请求的业务响应。
 * @param mode - 调用方请求的路由模式。
 * @param rootText - 根 Agent 的最终文本。
 * @param notifications - 官方 SDK 收集的根及后代通知。
 * @returns 业务 JSON 响应。
 * @throws 根及后代 session 都没有可解析的业务 JSON 时抛出。
 */
function resolveBusinessResponse(
  mode: XingyunMode,
  rootText: string,
  notifications: readonly unknown[],
): Record<string, unknown> {
  const expected = mode === 'list' || mode === 'form' || mode === 'js' ? mode : undefined
  const direct = businessResponseFromText(rootText)
  const candidates = direct === undefined ? [] : [direct]
  const childTexts: string[] = []
  for (const notification of notifications) {
    const text = assistantTextFromNotification(notification)
    if (text !== undefined && text.length > 0) childTexts.push(text)
  }
  for (const text of childTexts.toReversed()) {
    const response = businessResponseFromText(text)
    if (response !== undefined) candidates.push(response)
  }
  const matched = candidates.find(response => expected === undefined || response.type === expected)
  if (matched !== undefined) return matched
  const needsInput = candidates.find(response => response.status === 'needs_input')
  if (needsInput !== undefined) return needsInput
  if (direct !== undefined) return direct
  const preview = rootText.trim().replace(/\s+/g, ' ').slice(0, 500)
  throw new Error('root Agent did not return a JSON object; final response begins with: ' + JSON.stringify(preview))
}

/**
 * 确认已完成响应对应的业务文件类型。
 * @param value - Agent 响应中的 type 字段。
 * @returns list、form 或 js。
 */
function responseType(value: unknown): XingyunType {
  if (value === 'list' || value === 'form' || value === 'js') return value
  throw new Error('completed Agent response has no valid type')
}

/**
 * 根据业务类型确定统一入口应从工作区读取的最终文件。
 * @param type - 已完成响应的业务类型。
 * @param sourcePath - JS 模式使用的临时源码文件路径。
 * @param outputPath - 列表或表单 Agent 写入的 JSON 文件路径。
 * @returns 最终文件路径、返回文件名和媒体类型。
 */
function outputFile(type: XingyunType, sourcePath: string | undefined, outputPath: string): {
  path: string
  name: string
  mediaType: string
} {
  if (type === 'js') {
    if (sourcePath === undefined) throw new Error('JS response has no source.js workspace file')
    return { path: sourcePath, name: 'enhanced.js', mediaType: 'application/javascript' }
  }
  return {
    path: outputPath,
    name: type === 'list' ? 'generated-list.json' : 'generated-form.json',
    mediaType: 'application/json',
  }
}

/**
 * 生成 dsh-subagent-dsh-sdk provider 所需的 JSON 命令参数。
 * @param runtimeBin - JSON-RPC runtime 的可执行入口。
 * @param configPath - 目标子 runtime 的 cordis.yml 路径。
 * @returns 可写入 XINGYUN_*_AGENT_ARGS 的 JSON 字符串。
 */
function childArgs(runtimeBin: string, configPath: string): string {
  return JSON.stringify([runtimeBin, configPath])
}

/**
 * 执行一次完整的星云请求，并向标准输出写入统一 JSON 响应。
 * @returns 在根 runtime 及其子进程关闭、临时工作区删除后完成。
 */
async function main(): Promise<void> {
  const argument = process.argv[2]
  if (argument === undefined) {
    throw new Error('usage: run-xingyun.ts <request.json | JSON string | ->')
  }

  const input = await readRequestArgument(argument)
  const workspace = await mkdtemp(join(tmpdir(), 'xingyun-request-'))
  try {
    const prepared = await prepareRequest(input, workspace)
    const runtimeBin = fileURLToPath(new URL('../../packages/examples/jsonrpc-demo/lib/bin.js', import.meta.url))
    const rootConfig = fileURLToPath(new URL('./root.cordis.yml', import.meta.url))
    const listConfig = fileURLToPath(new URL('./list-agent.cordis.yml', import.meta.url))
    const formConfig = fileURLToPath(new URL('./form-agent.cordis.yml', import.meta.url))
    const jsConfig = fileURLToPath(new URL('./js-agent.cordis.yml', import.meta.url))
    const inherited = Object.fromEntries(
      Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
    )

    /**
     * 统一入口写入 stdout 的响应体，每次调用只输出一个 JSON 对象：
     *
     * completed:
     * {
     *   type: "list" | "form" | "js",
     *   status: "completed",
     *   file: {
     *     name: "generated-list.json" | "generated-form.json" | "enhanced.js",
     *     mediaType: "application/json" | "application/javascript",
     *     content: "最终 JSON 或 JS 文本",
     *     sha256: "最终文本的 SHA-256 十六进制摘要"
     *   }
     * }
     *
     * needs_input 或 processing 等非 completed 状态时，不读取工作区文件，
     * 而是原样透传根 Agent 返回的 JSON，例如
     * { status: "needs_input", message: "需要补充的信息" }。
     *
     * 根 Agent 若直接返回说明文字或官方前台子 Agent 包装对象，
     * resolveBusinessResponse 会从根或子会话的业务 JSON 恢复结果。
     */
    let response: Record<string, unknown>
    await using harness = new DeepSeekHarness({
      launch: {
        command: process.execPath,
        args: [runtimeBin, rootConfig],
        cwd: workspace,
        env: {
          ...inherited,
          XINGYUN_LIST_AGENT_COMMAND: process.execPath,
          XINGYUN_LIST_AGENT_ARGS: childArgs(runtimeBin, listConfig),
          XINGYUN_FORM_AGENT_COMMAND: process.execPath,
          XINGYUN_FORM_AGENT_ARGS: childArgs(runtimeBin, formConfig),
          XINGYUN_JS_AGENT_COMMAND: process.execPath,
          XINGYUN_JS_AGENT_ARGS: childArgs(runtimeBin, jsConfig),
        },
      },
      cwd: workspace,
      provider: 'vllm',
      model: 'Qwen/Qwen3.6-27B-FP8',
    })

    const run = await harness.run(
      '请根据请求中的 mode 选择一个目标 Agent，只调用一个目标 Agent。'
      + '必须将下面的完整请求 JSON 原样传给目标 Agent，并原样返回目标 Agent 的最终 JSON 响应。\n'
      + JSON.stringify(prepared.request),
    )
    response = resolveBusinessResponse(input.mode, run.finalResponse, run.notifications)

    if (response.status === 'completed') {
      const resultType = responseType(response.type)
      const file = outputFile(resultType, prepared.sourcePath, prepared.outputPath)
      const content = await readFile(file.path, 'utf8')
      response = {
        type: resultType,
        status: 'completed',
        file: {
          name: file.name,
          mediaType: file.mediaType,
          content,
          sha256: createHash('sha256').update(content, 'utf8').digest('hex'),
        },
      }
    }

    process.stdout.write(JSON.stringify(response) + '\n')
  } finally {
    await rm(workspace, { recursive: true, force: true })
  }
}

await main().catch((error: unknown) => {
  process.stderr.write((error instanceof Error ? error.stack ?? error.message : String(error)) + '\n')
  process.exitCode = 1
})
