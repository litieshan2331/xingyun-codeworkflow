/** Run one JavaScript enhancement request through the official SDK subagent provider. */

import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'

const [jsPath, instruction, targetVersion = '1.5.0'] = process.argv.slice(2)

if (jsPath === undefined || instruction === undefined) {
  throw new Error('usage: run-js-through-root.ts <path/to/source.js> <instruction> [targetVersion]')
}

const runtimeBin = fileURLToPath(new URL('../../packages/examples/jsonrpc-demo/lib/bin.js', import.meta.url))
const listConfig = fileURLToPath(new URL('./list-agent.cordis.yml', import.meta.url))
const formConfig = fileURLToPath(new URL('./form-agent.cordis.yml', import.meta.url))
const childConfig = fileURLToPath(new URL('./js-agent.cordis.yml', import.meta.url))
const rootConfig = fileURLToPath(new URL('./root.cordis.yml', import.meta.url))
const jsSource = await readFile(jsPath, 'utf8')
const inherited = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
)
const workspace = await mkdtemp(join(tmpdir(), 'xingyun-js-'))
const sourcePath = join(workspace, 'source.js')

try {
  await writeFile(sourcePath, jsSource, 'utf8')
  const request = JSON.stringify({ mode: 'js', instruction, sourcePath, targetVersion })
  await using harness = new DeepSeekHarness({
    launch: {
      command: process.execPath,
      args: [runtimeBin, rootConfig],
      cwd: workspace,
      env: {
        ...inherited,
        // The root composition loads all three provider rows. Only the
        // provider selected by the root agent starts a child process.
        XINGYUN_LIST_AGENT_COMMAND: process.execPath,
        XINGYUN_LIST_AGENT_ARGS: JSON.stringify([runtimeBin, listConfig]),
        XINGYUN_FORM_AGENT_COMMAND: process.execPath,
        XINGYUN_FORM_AGENT_ARGS: JSON.stringify([runtimeBin, formConfig]),
        XINGYUN_JS_AGENT_COMMAND: process.execPath,
        XINGYUN_JS_AGENT_ARGS: JSON.stringify([runtimeBin, childConfig]),
      },
    },
    cwd: workspace,
    provider: 'vllm',
    model: 'Qwen/Qwen3.6-27B-FP8',
  })

  const result = await harness.run(
    `将下面完整的星云 JS 增强请求委托给 xingyun_js_agent，并原样返回它的输出。\n${request}`,
  )
  const file = await readFile(sourcePath, 'utf8')
  process.stdout.write(`${JSON.stringify({ agentResponse: result.finalResponse, file: { name: 'enhanced.js', mediaType: 'application/javascript', content: file } })}\n`)
} finally {
  await rm(workspace, { recursive: true, force: true })
}
