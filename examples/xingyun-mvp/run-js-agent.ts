/** 直接运行星云 JS 增强 Agent，并输出临时 JS 文件的实际内容。 */

import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'

const [jsPath, instruction, targetVersion = '1.5.0'] = process.argv.slice(2)

if (jsPath === undefined || instruction === undefined) {
  throw new Error('usage: run-js-agent.ts <path/to/source.js> <instruction> [targetVersion]')
}

const runtimeBin = fileURLToPath(new URL('../../packages/examples/jsonrpc-demo/lib/bin.js', import.meta.url))
const configPath = fileURLToPath(new URL('./js-agent.cordis.yml', import.meta.url))
const jsSource = await readFile(jsPath, 'utf8')
const workspace = await mkdtemp(join(tmpdir(), 'xingyun-js-'))
const sourcePath = join(workspace, 'source.js')

try {
  await writeFile(sourcePath, jsSource, 'utf8')
  const request = JSON.stringify({ mode: 'js', instruction, sourcePath, targetVersion })
  await using harness = new DeepSeekHarness({
    launch: { command: process.execPath, args: [runtimeBin, configPath], cwd: workspace },
    cwd: workspace,
    provider: 'vllm',
    model: 'Qwen/Qwen3.6-27B-FP8',
  })

  const result = await harness.run(request)
  const file = await readFile(sourcePath, 'utf8')
  process.stdout.write(`${JSON.stringify({ agentResponse: result.finalResponse, file: { name: 'enhanced.js', mediaType: 'application/javascript', content: file } })}\n`)
} finally {
  await rm(workspace, { recursive: true, force: true })
}
