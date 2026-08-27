/** 直接运行星云列表 Agent，并输出其最终文本和生成文件内容。 */

import { copyFile, mkdtemp, readFile, rm } from 'node:fs/promises'
import { extname, join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'

const argument = process.argv[2]

if (argument === undefined) {
  throw new Error('usage: run-list-agent.ts <request.json | JSON string | ->')
}

async function readStandardInput(): Promise<string> {
  let result = ''
  for await (const chunk of process.stdin) result += String(chunk)
  return result
}

const raw = argument.trimStart().startsWith('{')
  ? argument
  : argument === '-' ? await readStandardInput() : await readFile(argument, 'utf8')
const request = JSON.parse(raw) as Record<string, unknown>
const workspace = await mkdtemp(join(tmpdir(), 'xingyun-list-'))
const outputPath = join(workspace, 'generated.json')

try {
  request.outputPath = outputPath
  if (typeof request.imagePath === 'string') {
    const imagePath = join(workspace, `input-image${extname(request.imagePath).toLowerCase()}`)
    await copyFile(resolve(request.imagePath), imagePath)
    request.imagePath = imagePath
  }

  const runtimeBin = fileURLToPath(new URL('../../packages/examples/jsonrpc-demo/lib/bin.js', import.meta.url))
  const configPath = fileURLToPath(new URL('./list-agent.cordis.yml', import.meta.url))
  const jsConfig = fileURLToPath(new URL('./js-agent.cordis.yml', import.meta.url))
  await using harness = new DeepSeekHarness({
    launch: {
      command: process.execPath,
      args: [runtimeBin, configPath],
      cwd: workspace,
      env: {
        ...Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined)),
        XINGYUN_JS_AGENT_COMMAND: process.execPath,
        XINGYUN_JS_AGENT_ARGS: JSON.stringify([runtimeBin, jsConfig]),
      },
    },
    cwd: workspace,
    provider: 'vllm',
    model: 'Qwen/Qwen3.6-27B-FP8',
  })

  const result = await harness.run(JSON.stringify(request))
  const file = await readFile(outputPath, 'utf8')
  process.stdout.write(`${JSON.stringify({ agentResponse: result.finalResponse, file: { name: 'generated-list.json', mediaType: 'application/json', content: file } })}\n`)
} finally {
  await rm(workspace, { recursive: true, force: true })
}
