// DSH lifecycle transport only. FAMES semantics remain in the shared Python core.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, renameSync, readFileSync, statSync } from 'node:fs';
import { dirname, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

export const name = 'fames-lifecycle';
export function operatorPrompt(messages) {
  // Native reminders also have role=user; only source.kind=user is an operator turn.
  return messages.filter(message => message.source?.kind === 'user')
    .flatMap(message => message.content ?? [])
    .filter(block => block.type === 'text' && typeof block.text === 'string')
    .map(block => block.text).join('\n');
}
export function invoke(config, payload, signal, spawnImpl = spawn) {
  return new Promise((accept, reject) => {
    const child = spawnImpl(config.python, [config.adapter], {
      cwd: config.seatRoot, shell: false, windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'], signal,
      env: { ...process.env, PYTHONUTF8: '1' },
    });
    let output = '';
    let exceeded = false;
    const timer = setTimeout(() => { exceeded = true; child.kill(); reject(new Error('adapter timeout')); }, 30000);
    child.stdout.on('data', data => {
      if (exceeded) return;
      output += data.toString('utf8');
      if (Buffer.byteLength(output) > 256 * 1024) {
        exceeded = true; output = ''; clearTimeout(timer); child.kill(); reject(new Error('adapter output limit'));
      }
    });
    // Never log stderr: it may contain arbitrary environment or source details.
    child.stderr.on('data', () => {});
    child.stdin.on('error', () => {});
    child.on('error', () => { clearTimeout(timer); reject(new Error('adapter transport failed')); });
    child.on('close', code => {
      clearTimeout(timer);
      if (exceeded) return;
      try {
        const result = JSON.parse(output);
        if (code !== 0 || !['PASS', 'UNKNOWN'].includes(result.state) || typeof result.context !== 'string') throw new Error();
        accept(result);
      } catch { reject(new Error('adapter result invalid')); }
    });
    const serialized = JSON.stringify(payload);
    if (Buffer.byteLength(serialized) > 1024 * 1024) { child.kill(); reject(new Error('payload too large')); return; }
    child.stdin.end(serialized);
  });
}

export async function apply(ctx, config) {
  const { createUserMessage } = await import(config.messageModule);
  ctx.on('agent/pre-step', async ({ agent, messages, turn, signal }, next) => {
    const prompt = operatorPrompt(messages);
    if (!prompt.trim()) return next();
    const cwd = agent?.session?.header?.cwd;
    try {
      if (typeof cwd !== 'string' || !cwd.trim() || !isAbsolute(cwd) || !statSync(cwd).isDirectory()) return { kind: 'reject' };
    } catch { return { kind: 'reject' }; }
    const payload = {
      hook_event_name: 'UserPromptSubmit', activation_source: 'dsh-agent-pre-step',
      session_id: agent.session.header.id, turn_id: String(turn), cwd,
      prompt,
    };
    let result;
    try { result = await invoke(config, payload, signal); }
    catch { return { kind: 'reject' }; }
    if (result.state !== 'PASS') return { kind: 'reject' };
    const downstream = await next();
    if (downstream.kind !== 'enter') return downstream;
    // Request-local projection: at most one current fragment, never a growing stack.
    const projected = downstream.messages.filter(m => !(m.source?.kind === 'plugin' && m.source?.plugin === name));
    if (!result.context.trim()) return { ...downstream, messages: projected };
    return { ...downstream, messages: [...projected, createUserMessage({
      content: [{ type: 'text', text: result.context }],
      source: { kind: 'plugin', plugin: name },
    })] };
  });
  // Module loading is readiness only; this receipt never asserts a user turn ran.
  mkdirSync(dirname(config.loadReceipt), { recursive: true });
  const temp = `${config.loadReceipt}.${process.pid}.tmp`;
  writeFileSync(temp, JSON.stringify({ schema: 1, state: 'LOADED',
    generated: new Date().toISOString(), pid: process.pid,
    adapter: config.adapter, seatRoot: config.seatRoot,
    plugin_sha256: createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),
    adapter_sha256: createHash('sha256').update(readFileSync(config.adapter)).digest('hex'),
    actual_turn_observed: false, inference_calls: 0, raw_prompt_persisted: false }));
  renameSync(temp, config.loadReceipt);
}
