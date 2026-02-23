---
name: packaging
description: Helps with pyproject.toml, setup.py, PyInstaller spec files, and release tasks. Use for packaging or build issues.
tools: Read, Write, Bash
---

You are an expert in Python packaging, PyInstaller, and GitHub releases.
When invoked:
1. Read pyproject.toml, setup.py, and neoview.spec
2. Check for missing dependencies or metadata
3. Validate the build steps in publish.sh
4. Suggest improvements for cross-platform compatibility (Linux + Windows)
```

---

### Step 4 — Your Final Folder Structure
```
neoview/
├── .codex/
│   └── skills/
│       ├── python-reviewer.md   ✅
│       ├── test-writer.md       ✅
│       ├── bug-finder.md        ✅
│       └── packaging.md         ✅
├── AGENTS.md                    ✅ (already exists)
├── CLAUDE.md                    ✅ (already exists)
├── src/neoview/
├── tests/
└── ...
```

---

### Step 5 — Use Your Skills in Codex

Open terminal in VS Code, run `codex`, then try:
```
$python-reviewer review src/neoview/main.py
```
```
$test-writer write tests for the crop/measure tool
```
```
$bug-finder why does auto-reload sometimes miss file changes?
```
```
$packaging check if pyproject.toml is ready for a new release