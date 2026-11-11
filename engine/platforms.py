"""Generators that turn the plugin's Claude-format agents and skills into Codex and Gemini CLI files.

Used by `gmh setup agents --tool codex|gemini` and by the build. Standard library only. Codex and Gemini support
is experimental and untested (neither CLI is installed where this was written).

  codex_agent(md_text)      subagents/<x>.md -> .codex/agents/<x>.toml text
  gemini_agent(md_text)     subagents/<x>.md -> Gemini subagent .md text
  gemini_command(skill_dir) skills/<x>/ -> commands/<x>.toml text
  command_files(repo)       {'commands/<skill>.toml': text} for every skill (`gmh setup platform-files` writes them)
  write_all(repo, out)      writes all of them under `out` (codex/agents, gemini/agents, gemini/commands)
"""
import json
import os
import re

# Claude model -> Codex reasoning effort. An explicit `effort:` in the frontmatter wins.
EFFORT = {'opus': 'high', 'sonnet': 'medium', 'haiku': 'low'}
GEMINI_TOOLS = {'read': 'read_file', 'websearch': 'google_web_search', 'webfetch': 'web_fetch',
                'grep': 'grep_search', 'glob': 'glob', 'write': 'write_file', 'edit': 'replace', 'bash': 'run_shell_command'}


def parse_frontmatter(text):
    """(fields, body). Handles `key: value` lines, double- or single-quoted values, and nothing fancier."""
    text = text.replace('\r\n', '\n').lstrip('﻿')
    m = re.match(r'---\n(.*?)\n---[ \t]*\n?(.*)\Z', text, re.S)
    if not m:
        return {}, text
    fields = {}
    for line in m.group(1).split('\n'):
        k = re.match(r'([A-Za-z_][\w-]*)\s*:\s*(.*)\Z', line)
        if not k:
            continue
        v = k.group(2).strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = re.sub(r'\\(["\\])', r'\1', v[1:-1])
        elif len(v) >= 2 and v[0] == "'" and v[-1] == "'":
            v = v[1:-1].replace("''", "'")
        fields[k.group(1)] = v
    return fields, m.group(2).lstrip('\n')


def toml_str(s):
    """A TOML basic string on one line (JSON string escapes are valid TOML)."""
    return json.dumps(s, ensure_ascii=False)


def toml_multiline(s):
    s = s.replace('\r\n', '\n').replace('\r', '\n').replace('\\', '\\\\').replace('"""', '""\\"')
    s = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', s)
    return '"""\n' + s.rstrip('\n') + '\n"""'


def _need(fields, key, what):
    if not fields.get(key):
        raise ValueError(what + ' has no ' + key + ' in its frontmatter')
    return fields[key]


def codex_agent(md_text):
    f, body = parse_frontmatter(md_text)
    name, desc = _need(f, 'name', 'agent'), _need(f, 'description', 'agent')
    effort = f.get('effort', '').lower()
    if effort not in ('low', 'medium', 'high'):
        effort = EFFORT.get(f.get('model', '').lower(), '')
    out = ['name = ' + toml_str(name), 'description = ' + toml_str(desc)]
    if effort:
        out.append('model_reasoning_effort = ' + toml_str(effort))
    out.append('developer_instructions = ' + toml_multiline(body))
    return '\n'.join(out) + '\n'


# The plugin names its Playwright server, so an installed plugin's agents see mcp__plugin_get-me-hired_playwright__*.
# A copy in .claude/agents (a checkout run without the plugin installed) may instead have the Playwright plugin
# (mcp__plugin_playwright_playwright__*) or a plain MCP server named playwright (mcp__playwright__*). Claude Code skips
# tool names that don't exist, so the copy lists all three and the agent gets whichever this machine has.
PLUGIN_PLAYWRIGHT = 'mcp__plugin_get-me-hired_playwright__'
LOCAL_PLAYWRIGHT = (PLUGIN_PLAYWRIGHT, 'mcp__plugin_playwright_playwright__', 'mcp__playwright__')


def claude_local_agent(md_text):
    """An agent file for <folder>/.claude/agents: the plugin's text with each Playwright tool listed under every
    server name a checkout may have (LOCAL_PLAYWRIGHT). Agents without Playwright tools are unchanged."""
    m = re.match(r'(---\n.*?\n)(tools:[^\n]*)(\n.*)\Z', md_text, re.S)
    if not m or PLUGIN_PLAYWRIGHT not in m.group(2):
        return md_text
    tools = [t for t in re.split(r'[,\s]+', m.group(2)[len('tools:'):]) if t]
    out = []
    for t in tools:
        names = [p + t[len(PLUGIN_PLAYWRIGHT):] for p in LOCAL_PLAYWRIGHT] if t.startswith(PLUGIN_PLAYWRIGHT) else [t]
        out += [n for n in names if n not in out]
    return m.group(1) + 'tools: ' + ', '.join(out) + m.group(3)


def _gemini_tool(t):
    t = t.strip()
    m = re.match(r'mcp__(?:plugin_[A-Za-z0-9_-]+_)?([A-Za-z0-9-]+?)__(.+)\Z', t)
    if m:  # Claude mcp__playwright__browser_click -> Gemini mcp_playwright_browser_click
        return 'mcp_%s_%s' % (m.group(1), m.group(2))
    return GEMINI_TOOLS.get(t.lower(), t)


def gemini_agent(md_text):
    f, body = parse_frontmatter(md_text)
    name, desc = _need(f, 'name', 'agent'), _need(f, 'description', 'agent')
    lines = ['---', 'name: ' + name, 'description: ' + toml_str(desc)]  # a JSON string is a valid YAML string
    tools = [_gemini_tool(t) for t in re.split(r'[,\s]+', f.get('tools', '')) if t]
    if tools:
        lines.append('tools:')
        lines += ['  - ' + t for t in tools]
    lines += ['model: inherit', '---', '']
    return '\n'.join(lines) + '\n' + body.rstrip('\n') + '\n'


def gemini_command(skill_dir):
    with open(os.path.join(skill_dir, 'SKILL.md'), encoding='utf-8') as fh:
        f, _ = parse_frontmatter(fh.read())
    name = f.get('name') or os.path.basename(os.path.normpath(skill_dir))
    desc = _need(f, 'description', 'skill ' + name)
    prompt = 'Use the get-me-hired %s skill. {{args}}' % name
    return 'description = %s\nprompt = %s\n' % (toml_str(desc), toml_str(prompt))


def command_files(repo):
    """{'commands/<skill>.toml': text} for every skills/<name>/SKILL.md: the Gemini CLI commands the extension ships."""
    out = {}
    sdir = os.path.join(repo, 'skills')
    for d in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        if os.path.isfile(os.path.join(sdir, d, 'SKILL.md')):
            out['commands/%s.toml' % d] = gemini_command(os.path.join(sdir, d))
    return out


def write_all(repo, out):
    """Write every generated file under `out`; returns the list of paths written."""
    written = []

    def put(rel, text):
        p = os.path.join(out, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        written.append(p)

    adir = os.path.join(repo, 'subagents')
    for fn in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        if not fn.endswith('.md'):
            continue
        with open(os.path.join(adir, fn), encoding='utf-8') as fh:
            text = fh.read()
        stem = fn[:-3]
        put('codex/agents/%s.toml' % stem, codex_agent(text))
        put('gemini/agents/%s.md' % stem, gemini_agent(text))
    sdir = os.path.join(repo, 'skills')
    for d in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        if os.path.isfile(os.path.join(sdir, d, 'SKILL.md')):
            put('gemini/commands/%s.toml' % d, gemini_command(os.path.join(sdir, d)))
    return written
