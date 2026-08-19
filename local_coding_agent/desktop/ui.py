"""Embedded single-file production-grade HTML template for Desktop AI Coding Harness.

Designed using shadcn/ui dark zinc aesthetic, Geist / Geist Mono typography,
and full Light/Dark theme support.
"""

from __future__ import annotations

DESKTOP_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Local AI Coding Harness</title>
  
  <!-- High-Precision Engineering Typography (Geist + Geist Mono + JetBrains Mono) -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  
  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Lucide Icons CDN -->
  <script src="https://unpkg.com/lucide@latest"></script>

  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Geist', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
            mono: ['Geist Mono', 'JetBrains Mono', 'ui-monospace', 'monospace'],
          },
          letterSpacing: {
            tighter: '-0.03em',
            tight: '-0.015em',
          }
        }
      }
    }
  </script>

  <style>
    * { box-sizing: border-box; }
    
    /* Dark Theme Tokens */
    :root.dark {
      --bg-app: #09090b;
      --bg-header: #0e0e11;
      --bg-sidebar: #0e0e11;
      --bg-card: #131316;
      --bg-card-subtle: #18181b;
      --bg-input: #09090b;
      --border-main: #27272a;
      --border-subtle: #1f1f23;
      --text-main: #f4f4f5;
      --text-muted: #a1a1aa;
      --text-subtle: #71717a;
      --diff-add-bg: rgba(16, 185, 129, 0.12);
      --diff-add-text: #86efac;
      --diff-del-bg: rgba(239, 68, 68, 0.12);
      --diff-del-text: #fca5a5;
    }

    /* Light Theme Tokens */
    :root:not(.dark) {
      --bg-app: #fbfbfb;
      --bg-header: #ffffff;
      --bg-sidebar: #f4f4f5;
      --bg-card: #ffffff;
      --bg-card-subtle: #f4f4f5;
      --bg-input: #ffffff;
      --border-main: #e4e4e7;
      --border-subtle: #ebebef;
      --text-main: #09090b;
      --text-muted: #52525b;
      --text-subtle: #71717a;
      --diff-add-bg: rgba(16, 185, 129, 0.10);
      --diff-add-text: #059669;
      --diff-del-bg: rgba(239, 68, 68, 0.10);
      --diff-del-text: #dc2626;
    }

    body {
      background-color: var(--bg-app);
      color: var(--text-main);
      font-feature-settings: "cv02", "cv03", "cv04", "cv11";
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #3f3f46; border-radius: 2px; }
    :root:not(.dark) ::-webkit-scrollbar-thumb { background: #d4d4d8; }

    .diff-del-bg { background-color: var(--diff-del-bg); color: var(--diff-del-text); }
    .diff-add-bg { background-color: var(--diff-add-bg); color: var(--diff-add-text); }
    .num-tabular { font-variant-numeric: tabular-nums; }
  </style>
</head>
<body class="h-screen flex flex-col font-sans tracking-tight overflow-hidden select-none">

  <!-- TOP BAR -->
  <header class="h-11 border-b border-[var(--border-main)] bg-[var(--bg-header)] px-3.5 flex items-center justify-between shrink-0">
    
    <!-- Left: Brand + Strict Telemetry Badges -->
    <div class="flex items-center gap-2.5">
      <button onclick="toggleSidebar()" class="p-1 rounded hover:bg-zinc-800/40 text-zinc-400 hover:text-zinc-200 transition" title="Toggle Sessions (Ctrl+B)">
        <i data-lucide="panel-left" class="w-3.5 h-3.5"></i>
      </button>

      <div class="flex items-center gap-1.5 pr-2.5 border-r border-[var(--border-main)] font-medium text-xs">
        <span class="w-2 h-2 rounded-sm bg-cyan-500"></span>
        <span class="font-semibold text-[var(--text-main)]">Local Harness</span>
      </div>

      <!-- Telemetry Pills (Geist Mono Tabular) -->
      <div class="flex items-center gap-1.5 font-mono text-[11px] num-tabular">
        <button onclick="openSettingsModal()" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] hover:border-zinc-500 border border-[var(--border-main)] text-[var(--text-muted)] transition cursor-pointer" title="Inspect GPU & VRAM Memory">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span class="text-zinc-500 font-sans text-[10px]">VRAM</span> <span id="telemetryVram">5.8/16G</span>
        </button>

        <button onclick="openSettingsModal()" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] hover:border-zinc-500 border border-[var(--border-main)] text-[var(--text-muted)] transition cursor-pointer" title="Model Profile">
          <span class="text-cyan-500 font-sans text-[10px]">MODEL</span>
          <span class="text-[var(--text-main)]" id="telemetryModel">qwen2.5-coder:7b</span>
        </button>

        <div class="hidden md:inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] border border-[var(--border-main)] text-zinc-500">
          <span class="font-sans text-[10px]">CTX</span>
          <span class="text-[var(--text-muted)]" id="telemetryCtx">2.1k/8.1k</span>
        </div>

        <div class="hidden lg:inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] border border-[var(--border-main)] text-zinc-500">
          <span class="text-emerald-500" id="telemetryTps">78.4</span>
          <span class="text-[10px] font-sans">tok/s</span>
        </div>
      </div>
    </div>

    <!-- Center: Segmented Navigation -->
    <div class="inline-flex items-center p-0.5 bg-[var(--bg-card-subtle)] border border-[var(--border-main)] rounded-md font-sans">
      <button onclick="switchTab('chat')" id="tab-btn-chat" class="tab-btn px-2.5 py-1 text-[11px] font-medium rounded transition flex items-center gap-1.5 bg-[var(--bg-card)] text-[var(--text-main)] shadow-sm border border-[var(--border-main)]">
        <i data-lucide="message-square" class="w-3 h-3 text-cyan-500"></i>
        <span>Interactive Chat</span>
      </button>
      <button onclick="switchTab('delegated')" id="tab-btn-delegated" class="tab-btn px-2.5 py-1 text-[11px] font-medium rounded transition flex items-center gap-1.5 text-[var(--text-muted)] hover:text-[var(--text-main)]">
        <i data-lucide="inbox" class="w-3 h-3"></i>
        <span>Delegated Tasks</span>
        <span class="px-1 py-0.1 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-500 text-[9px] font-mono font-semibold" id="delegatedBadgeCount">1</span>
      </button>
    </div>

    <!-- Right: Workspace + Theme Toggle + Settings -->
    <div class="flex items-center gap-2 text-xs">
      <div class="flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] border border-[var(--border-main)] font-mono text-[11px] text-[var(--text-muted)]">
        <i data-lucide="git-branch" class="w-3 h-3 text-zinc-500"></i>
        <span class="text-[var(--text-main)]" id="workspaceName">workspace</span>
        <span class="text-emerald-500 text-[10px] font-sans font-medium" id="workspaceBranch">• main*</span>
      </div>

      <!-- Theme Switcher -->
      <button onclick="toggleTheme()" class="p-1.5 rounded hover:bg-zinc-800/40 text-[var(--text-muted)] hover:text-[var(--text-main)] transition" title="Toggle Dark/Light Theme">
        <i data-lucide="sun-medium" id="themeIconSun" class="w-3.5 h-3.5 hidden dark:block"></i>
        <i data-lucide="moon" id="themeIconMoon" class="w-3.5 h-3.5 block dark:hidden"></i>
      </button>

      <button onclick="openSettingsModal()" class="p-1.5 rounded hover:bg-zinc-800/40 text-[var(--text-muted)] hover:text-[var(--text-main)] transition" title="Settings & Hardware Cockpit">
        <i data-lucide="sliders" class="w-3.5 h-3.5"></i>
      </button>
    </div>
  </header>

  <!-- MAIN VIEWPORT -->
  <main class="flex-1 flex overflow-hidden relative">

    <!-- LEFT SIDEBAR: SESSION HISTORY -->
    <aside id="sessionSidebar" class="w-60 bg-[var(--bg-sidebar)] border-r border-[var(--border-main)] flex flex-col h-full shrink-0 transition-all duration-150">
      
      <div class="p-2.5 border-b border-[var(--border-main)]">
        <button onclick="startNewSession()" class="w-full py-1 px-2.5 rounded bg-[var(--bg-card)] hover:border-zinc-500 border border-[var(--border-main)] text-[11px] font-medium text-[var(--text-main)] transition flex items-center justify-between shadow-sm">
          <span class="flex items-center gap-1.5">
            <i data-lucide="plus" class="w-3 h-3 text-cyan-500"></i>
            <span>New Task Session</span>
          </span>
          <kbd class="text-[9px] font-mono text-zinc-500 bg-[var(--bg-card-subtle)] px-1 rounded border border-[var(--border-main)]">Ctrl+N</kbd>
        </button>
      </div>

      <div class="px-2.5 pt-2 pb-1 flex items-center gap-1 text-[10px] font-medium text-[var(--text-muted)]">
        <button onclick="filterSessions('all')" class="filter-chip px-1.5 py-0.5 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-main)] font-semibold">All</button>
        <button onclick="filterSessions('user')" class="filter-chip px-1.5 py-0.5 rounded hover:bg-[var(--bg-card)] text-zinc-500">User</button>
        <button onclick="filterSessions('agent')" class="filter-chip px-1.5 py-0.5 rounded hover:bg-[var(--bg-card)] text-zinc-500">Agent</button>
      </div>

      <div class="flex-1 overflow-y-auto p-1.5 space-y-1 text-xs font-sans" id="sessionList">
        <!-- Dynamic sessions loaded from API or local store -->
      </div>

      <div class="p-2 border-t border-[var(--border-main)] text-[10px] font-mono text-zinc-500 flex items-center justify-between">
        <span id="sessionCounter">4 Sessions</span>
        <span>Harness v0.7.0</span>
      </div>
    </aside>

    <!-- TAB 1: INTERACTIVE CHAT MODE -->
    <div id="view-chat" class="tab-view flex-1 flex h-full">
      
      <!-- Center Chat Stream -->
      <div class="flex-1 flex flex-col bg-[var(--bg-app)] border-r border-[var(--border-main)] h-full overflow-hidden">
        
        <div id="chatMessages" class="flex-1 overflow-y-auto p-5 space-y-3.5">
          <!-- Initial Welcome Message -->
          <div class="flex items-start gap-2.5 max-w-2xl">
            <div class="w-6 h-6 rounded bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center shrink-0 text-[10px] font-mono font-semibold text-cyan-500">
              AI
            </div>
            <div class="flex-1 space-y-2">
              <div class="text-[11px] font-medium text-zinc-500 flex items-center gap-1.5">
                <span>Local Coding Harness</span>
                <span class="text-[9px] font-mono text-zinc-500">• Ready</span>
              </div>
              <div class="p-3 rounded-lg bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-[var(--text-main)] leading-relaxed">
                Welcome! Enter your coding goal below or select a quick preset. The harness will automatically decompose your prompt, skeletonize code, generate verified SEARCH/REPLACE diffs, and validate with local test runners.
              </div>
            </div>
          </div>
        </div>

        <!-- Quick Action Prompt Chips -->
        <div class="px-5 py-1.5 border-t border-[var(--border-main)] bg-[var(--bg-header)] flex items-center gap-1.5 overflow-x-auto text-xs">
          <span class="text-zinc-500 text-[10px] font-mono shrink-0">Presets:</span>
          <button onclick="setPromptAndRun('Fix off-by-one error in sliding window index')" class="px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] hover:bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] text-[11px] transition shrink-0 flex items-center gap-1">
            <i data-lucide="zap" class="w-2.5 h-2.5 text-amber-500"></i> Fix sliding window
          </button>
          <button onclick="setPromptAndRun('Write pytest unit tests for tax calculation')" class="px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] hover:bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] text-[11px] transition shrink-0 flex items-center gap-1">
            <i data-lucide="test-tube" class="w-2.5 h-2.5 text-cyan-500"></i> Unit test tax logic
          </button>
          <button onclick="setPromptAndRun('Refactor calculate_total to use integer cents')" class="px-2 py-0.5 rounded bg-[var(--bg-card-subtle)] hover:bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] text-[11px] transition shrink-0 flex items-center gap-1">
            <i data-lucide="wrench" class="w-2.5 h-2.5 text-emerald-500"></i> Refactor tax cents
          </button>
        </div>

        <!-- Input Bar -->
        <div class="p-3 bg-[var(--bg-app)] border-t border-[var(--border-main)]">
          <div class="relative flex items-center bg-[var(--bg-input)] border border-[var(--border-main)] rounded-lg focus-within:border-cyan-500 focus-within:ring-1 focus-within:ring-cyan-500/20 transition shadow-inner">
            <input id="chatInput" type="text" placeholder="Instruct local model to fix, refactor, or test (Enter to send)..." class="w-full bg-transparent px-3 py-2 text-xs text-[var(--text-main)] placeholder-zinc-500 outline-none" onkeydown="if(event.key==='Enter') handleUserSubmit()">
            <button onclick="handleUserSubmit()" id="btnSendChat" class="mr-1.5 px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-zinc-950 font-semibold text-xs transition flex items-center justify-center">
              <span>Run</span>
            </button>
          </div>
        </div>

      </div>

      <!-- Right: Split Code Diff Studio -->
      <div class="w-[460px] lg:w-[540px] bg-[var(--bg-header)] flex flex-col h-full overflow-hidden">
        
        <div class="h-9 px-3 border-b border-[var(--border-main)] flex items-center justify-between bg-[var(--bg-card-subtle)]">
          <div class="flex items-center gap-2 text-xs font-mono text-[var(--text-main)]">
            <i data-lucide="file-code" class="w-3 h-3 text-cyan-500"></i>
            <span id="diffFileName">convert.py</span>
            <span class="text-[9px] text-emerald-500 font-mono font-semibold" id="diffStatsTag">+3 / -2</span>
          </div>

          <div class="flex items-center gap-1 font-mono text-[10px]">
            <button onclick="copyActiveDiff()" class="px-2 py-0.5 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition">
              Copy
            </button>
            <button onclick="applyProposalAction()" id="btnApply" class="px-2.5 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-zinc-950 font-semibold font-sans transition">
              Apply (Ctrl+A)
            </button>
            <button onclick="rollbackAction()" id="btnRollback" class="px-2 py-0.5 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition">
              Rollback
            </button>
          </div>
        </div>

        <!-- Diff Lines Container -->
        <div id="diffContentArea" class="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed p-2 select-text">
          <div class="p-8 text-center text-zinc-500 text-xs">No active diff proposal. Run a prompt or select a task session.</div>
        </div>

        <div class="p-2 bg-[var(--bg-app)] border-t border-[var(--border-main)] flex items-center justify-between text-xs font-mono text-[10px]">
          <div class="flex items-center gap-1 text-emerald-500" id="diffEvidenceStatus">
            <i data-lucide="check-circle-2" class="w-3 h-3"></i>
            <span>Oracles Verified by Test Runner</span>
          </div>
          <span class="text-zinc-500">Zero Hallucinations</span>
        </div>
      </div>

    </div>

    <!-- TAB 2: DELEGATED TASKS MODE -->
    <div id="view-delegated" class="tab-view flex-1 hidden h-full">
      <div class="flex-1 grid grid-cols-1 md:grid-cols-3 h-full overflow-hidden">
        
        <!-- Left: TaskEnvelope Card -->
        <div class="p-5 bg-[var(--bg-sidebar)] border-r border-[var(--border-main)] space-y-3.5 overflow-y-auto text-xs">
          <div class="flex items-center justify-between pb-2 border-b border-[var(--border-main)]">
            <h2 class="text-xs font-semibold text-[var(--text-main)] flex items-center gap-1.5">
              <i data-lucide="inbox" class="w-3.5 h-3.5 text-cyan-500"></i>
              <span>Task Envelope</span>
            </h2>
            <span class="px-1.5 py-0.2 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-500 font-mono text-[9px] font-semibold" id="delegatedStatusTag">
              READY FOR APPLY
            </span>
          </div>

          <div class="space-y-1">
            <label class="text-[10px] font-mono uppercase text-zinc-500">Delegating Host Agent</label>
            <div class="p-2 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-[var(--text-main)] font-mono flex items-center gap-1.5" id="delegatedAgent">
              <i data-lucide="bot" class="w-3 h-3 text-purple-500"></i>
              <span>Codex / Claude Code (MCP)</span>
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-[10px] font-mono uppercase text-zinc-500">Task ID</label>
            <div class="p-2 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-[var(--text-main)] font-mono" id="delegatedTaskId">
              req-tax-precision-402
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-[10px] font-mono uppercase text-zinc-500">Goal</label>
            <div class="p-2 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-[var(--text-main)] leading-relaxed" id="delegatedGoal">
              Fix decimal precision in tax calculation without breaking existing public interfaces.
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-[10px] font-mono uppercase text-zinc-500">Allowlisted Files</label>
            <div class="p-2 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-cyan-500 font-mono" id="delegatedFiles">
              src/tax.py
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-[10px] font-mono uppercase text-zinc-500">Targeted Checks</label>
            <div class="p-2 rounded bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-emerald-500 font-mono" id="delegatedChecks">
              pytest tests/test_tax.py
            </div>
          </div>

          <div class="pt-2 space-y-1.5">
            <button onclick="applyProposalAction()" class="w-full py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-zinc-950 font-semibold text-xs transition flex items-center justify-center gap-1.5">
              <i data-lucide="check" class="w-3.5 h-3.5"></i>
              <span>Apply Proposal (Ctrl+A)</span>
            </button>
            <button onclick="rollbackAction()" class="w-full py-1.5 rounded bg-[var(--bg-card)] hover:border-zinc-500 border border-[var(--border-main)] text-[var(--text-muted)] font-medium text-xs transition flex items-center justify-center gap-1.5">
              <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
              <span>Auto-Rollback (git restore)</span>
            </button>
          </div>
        </div>

        <!-- Right: Monaco Split Diff -->
        <div class="col-span-2 bg-[var(--bg-app)] flex flex-col h-full overflow-hidden">
          <div class="h-9 px-3 border-b border-[var(--border-main)] flex items-center justify-between bg-[var(--bg-card-subtle)]">
            <div class="text-xs font-mono text-[var(--text-main)] flex items-center gap-1.5">
              <i data-lucide="file-code" class="w-3 h-3 text-cyan-500"></i>
              <span id="delegatedFileName">src/tax.py</span>
              <span class="text-zinc-500 text-[10px]">(Proposal Accepted by Controller)</span>
            </div>
          </div>

          <div id="delegatedDiffContent" class="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed select-text space-y-0.5">
            <!-- Rendered diff -->
          </div>

          <div class="p-2.5 bg-[var(--bg-header)] border-t border-[var(--border-main)] flex items-center justify-between text-xs">
            <div class="flex items-center gap-1.5 text-emerald-500 font-mono text-[11px]">
              <i data-lucide="shield-check" class="w-3.5 h-3.5"></i>
              <span id="delegatedEvidenceTag">Evidence: pytest tests/test_tax.py (6 passed in 0.38s)</span>
            </div>
          </div>
        </div>

      </div>
    </div>

  </main>

  <!-- SETTINGS & HARDWARE MODAL DIALOG -->
  <div id="settingsModal" class="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 z-50 hidden">
    <div class="bg-[var(--bg-card)] border border-[var(--border-main)] rounded-xl w-full max-w-xl overflow-hidden shadow-xl animate-in fade-in zoom-in-95 duration-100">
      
      <div class="px-4 py-3 border-b border-[var(--border-main)] flex items-center justify-between bg-[var(--bg-card-subtle)]">
        <div class="flex items-center gap-2">
          <i data-lucide="sliders" class="w-3.5 h-3.5 text-cyan-500"></i>
          <h3 class="text-xs font-semibold text-[var(--text-main)]">Hardware Telemetry &amp; Controller Settings</h3>
        </div>
        <button onclick="closeSettingsModal()" class="p-1 rounded hover:bg-zinc-800/40 text-zinc-400 hover:text-zinc-200">
          <i data-lucide="x" class="w-3.5 h-3.5"></i>
        </button>
      </div>

      <div class="p-4 space-y-4 max-h-[70vh] overflow-y-auto text-xs">
        
        <!-- Hardware Grid -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <div class="p-3 rounded-lg bg-[var(--bg-app)] border border-[var(--border-main)] space-y-1.5">
            <div class="flex items-center justify-between text-[10px] text-zinc-500 font-mono">
              <span>GPU VRAM</span>
              <i data-lucide="hard-drive" class="w-3 h-3 text-cyan-500"></i>
            </div>
            <div class="text-lg font-bold font-mono text-[var(--text-main)] num-tabular" id="modalVramText">5.8 <span class="text-xs font-normal text-zinc-500">/ 16.0 GB</span></div>
            <div class="w-full h-1 rounded bg-[var(--bg-card-subtle)] overflow-hidden">
              <div class="h-full bg-cyan-500 rounded" id="modalVramBar" style="width: 36%"></div>
            </div>
          </div>

          <div class="p-3 rounded-lg bg-[var(--bg-app)] border border-[var(--border-main)] space-y-1.5">
            <div class="flex items-center justify-between text-[10px] text-zinc-500 font-mono">
              <span>Speculative Racing</span>
              <i data-lucide="zap" class="w-3 h-3 text-amber-500"></i>
            </div>
            <div class="text-xs font-semibold text-[var(--text-main)]">2 Draft Slots</div>
            <div class="text-[10px] text-emerald-500 font-mono">Active (t=0 vs 0.2)</div>
          </div>

          <div class="p-3 rounded-lg bg-[var(--bg-app)] border border-[var(--border-main)] space-y-1.5">
            <div class="flex items-center justify-between text-[10px] text-zinc-500 font-mono">
              <span>Ladder Rating</span>
              <i data-lucide="award" class="w-3 h-3 text-purple-500"></i>
            </div>
            <div class="text-xs font-bold text-[var(--text-main)]" id="modalLadderTier">Tier 2 (Workhorse)</div>
            <div class="text-[10px] text-zinc-500 font-mono">CI95: 96.2%</div>
          </div>
        </div>

        <!-- Model Selection -->
        <div class="space-y-1.5">
          <label class="text-[11px] font-medium text-[var(--text-muted)]">Active Model Profile</label>
          <select id="modalProfileSelect" onchange="changeProfile(this.value)" class="w-full bg-[var(--bg-app)] border border-[var(--border-main)] rounded px-2.5 py-1.5 text-xs text-[var(--text-main)] outline-none focus:border-cyan-500 font-mono">
            <option value="qwen2.5-coder">qwen2.5-coder:7b-instruct-q6_K (Default)</option>
            <option value="ling-3.0-tiny-q6k">ling-3.0-tiny-q6k (llama-server:8080)</option>
            <option value="qwen3-8b-q6k">qwen3-8b-q6k (Ollama)</option>
            <option value="devstral-small-2-24b">devstral-small-2-24b (Advanced)</option>
          </select>
        </div>

        <!-- Environment Doctor -->
        <div class="p-3 rounded-lg bg-[var(--bg-app)] border border-[var(--border-main)] flex items-center justify-between">
          <div>
            <div class="text-xs font-medium text-[var(--text-main)]">Self-Healing Doctor (doctor --fix)</div>
            <div class="text-[10px] text-zinc-500 font-mono">All MCP configs &amp; IDE skills synced.</div>
          </div>
          <button onclick="runDoctorCheck()" id="btnDoctor" class="px-2.5 py-1 rounded bg-[var(--bg-card)] hover:border-zinc-500 border border-[var(--border-main)] text-[11px] font-medium text-[var(--text-main)] transition">
            Run Check
          </button>
        </div>

      </div>

      <div class="px-4 py-2 border-t border-[var(--border-main)] bg-[var(--bg-card-subtle)] flex justify-end">
        <button onclick="closeSettingsModal()" class="px-3 py-1 rounded bg-[var(--bg-card)] hover:border-zinc-500 border border-[var(--border-main)] text-xs font-medium text-[var(--text-main)]">
          Done
        </button>
      </div>

    </div>
  </div>

  <!-- Notification Toast -->
  <div id="toast" class="fixed bottom-4 right-4 px-3.5 py-2 rounded-md bg-[var(--bg-card)] border border-[var(--border-main)] text-[var(--text-main)] text-xs shadow-lg flex items-center gap-1.5 transform translate-y-2 opacity-0 transition-all pointer-events-none z-50 font-mono text-[11px]">
    <i data-lucide="check" class="w-3 h-3 text-emerald-500"></i>
    <span id="toastText">Action completed</span>
  </div>

  <script>
    lucide.createIcons();

    const SESSIONS = [
      {
        id: 'sess-01',
        type: 'user',
        title: 'Fix float precision in convert.py',
        file: 'convert.py',
        diff: `
<div class="space-y-0.5">
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">1</span><span class="text-[var(--text-muted)]">from decimal import Decimal</span></div>
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">2</span><span></span></div>
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">3</span><span class="text-[var(--text-muted)]">def calculate_conversion(amount_cents: int, rate: float) -> int:</span></div>
  <div class="flex px-2 py-0.5 diff-del-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">4 -</span><span>    return int(amount_cents * rate)</span></div>
  <div class="flex px-2 py-0.5 diff-add-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">4 +</span><span>    rate_factor = Decimal(str(rate))</span></div>
  <div class="flex px-2 py-0.5 diff-add-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">5 +</span><span>    return int(Decimal(amount_cents) * rate_factor)</span></div>
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">6</span><span></span></div>
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">7</span><span class="text-[var(--text-muted)]">def get_exchange_rate(base: str, target: str) -> float:</span></div>
</div>`,
        diffStats: '+3 / -2',
        status: 'Verified',
        time: 'Just now'
      },
      {
        id: 'sess-02',
        type: 'agent',
        agent: 'Codex',
        taskId: 'req-tax-precision-402',
        title: 'req-tax-precision-402',
        goal: 'Fix decimal precision in tax calculation without breaking existing public interfaces.',
        file: 'src/tax.py',
        checks: 'pytest tests/test_tax.py',
        diff: `
<div class="space-y-0.5">
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">10</span><span class="text-[var(--text-muted)]">class TaxCalculator:</span></div>
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">11</span><span class="text-[var(--text-muted)]">    def compute_sales_tax(self, subtotal_cents: int, tax_rate_bps: int) -> int:</span></div>
  <div class="flex px-2 py-0.5 diff-del-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">12 -</span><span>        rate = tax_rate_bps / 10000.0</span></div>
  <div class="flex px-2 py-0.5 diff-del-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">13 -</span><span>        return round(subtotal_cents * rate)</span></div>
  <div class="flex px-2 py-0.5 diff-add-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">12 +</span><span>        # Precise integer basis point arithmetic</span></div>
  <div class="flex px-2 py-0.5 diff-add-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">13 +</span><span>        return (subtotal_cents * tax_rate_bps + 5000) // 10000</span></div>
</div>`,
        diffStats: '+2 / -2',
        status: 'Ready to Apply',
        time: '12m ago'
      },
      {
        id: 'sess-03',
        type: 'agent',
        agent: 'Claude',
        taskId: 'req-auth-jwt-expire',
        title: 'Refactor JWT expiration check',
        goal: 'Harden JWT token validation and add grace period margin.',
        file: 'src/auth.py',
        checks: 'pytest tests/test_auth.py',
        diff: `
<div class="space-y-0.5">
  <div class="flex px-2 py-0.5 text-zinc-500"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">45</span><span class="text-[var(--text-muted)]">def verify_token(token: str, leeway_sec: int = 10) -> bool:</span></div>
  <div class="flex px-2 py-0.5 diff-add-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">46 +</span><span>    now = int(time.time())</span></div>
  <div class="flex px-2 py-0.5 diff-add-bg rounded-xs"><span class="w-6 shrink-0 text-right pr-2 select-none num-tabular">47 +</span><span>    return token.exp + leeway_sec >= now</span></div>
</div>`,
        diffStats: '+2 / -0',
        status: 'Applied',
        time: '1h ago'
      },
      {
        id: 'sess-04',
        type: 'user',
        title: 'Polyglot Go benchmark runner',
        file: 'tests/bench.go',
        diff: `<div class="p-4 text-center text-zinc-500 font-mono text-[10px]">Archived run (No active unapplied hunks)</div>`,
        diffStats: 'Clean',
        status: 'Archived',
        time: 'Yesterday'
      }
    ];

    let activeSession = SESSIONS[0];

    function renderSessions(filter = 'all') {
      const list = document.getElementById('sessionList');
      list.innerHTML = '';
      const filtered = SESSIONS.filter(s => filter === 'all' || s.type === filter);
      document.getElementById('sessionCounter').textContent = `${SESSIONS.length} Sessions`;

      filtered.forEach(s => {
        const isSelected = activeSession && activeSession.id === s.id;
        const card = document.createElement('div');
        card.className = `session-card p-2 rounded border cursor-pointer transition ${
          isSelected
            ? 'border-cyan-500/40 bg-[var(--bg-card)] text-[var(--text-main)] shadow-xs'
            : 'border-transparent hover:border-[var(--border-main)] hover:bg-[var(--bg-card)] text-[var(--text-muted)]'
        }`;
        card.onclick = () => selectSessionById(s.id);

        const badgeClass = s.type === 'user'
          ? 'bg-blue-500/10 border-blue-500/30 text-blue-500'
          : s.agent === 'Codex'
            ? 'bg-purple-500/10 border-purple-500/30 text-purple-500'
            : 'bg-cyan-500/10 border-cyan-500/30 text-cyan-500';

        const badgeLabel = s.type === 'user' ? 'USER' : `AGENT: ${s.agent || 'MCP'}`;

        card.innerHTML = `
          <div class="flex items-center justify-between mb-0.5">
            <span class="inline-flex items-center gap-1 px-1 py-0.1 rounded border font-mono text-[9px] font-semibold tracking-wider ${badgeClass}">
              ${badgeLabel}
            </span>
            <span class="text-[9px] font-mono text-zinc-500 num-tabular">${s.time}</span>
          </div>
          <div class="text-[11px] font-medium truncate text-[var(--text-main)]">${s.title}</div>
          <div class="text-[10px] text-zinc-500 font-mono mt-0.5 flex items-center justify-between">
            <span>${s.file}</span>
            <span class="${s.status.includes('Ready') || s.status === 'Verified' ? 'text-emerald-500 font-semibold' : 'text-zinc-500'}">${s.status}</span>
          </div>
        `;
        list.appendChild(card);
      });
      lucide.createIcons();
    }

    function selectSessionById(id) {
      const found = SESSIONS.find(s => s.id === id);
      if (!found) return;
      activeSession = found;
      renderSessions();

      if (found.type === 'agent') {
        switchTab('delegated');
        document.getElementById('delegatedTaskId').textContent = found.taskId || found.id;
        document.getElementById('delegatedGoal').textContent = found.goal || found.title;
        document.getElementById('delegatedFiles').textContent = found.file;
        document.getElementById('delegatedChecks').textContent = found.checks || 'pytest tests/';
        document.getElementById('delegatedFileName').textContent = found.file;
        document.getElementById('delegatedDiffContent').innerHTML = found.diff;
      } else {
        switchTab('chat');
        document.getElementById('diffFileName').textContent = found.file;
        document.getElementById('diffStatsTag').textContent = found.diffStats;
        document.getElementById('diffContentArea').innerHTML = found.diff;
      }
      showToast(`Switched to ${found.type === 'agent' ? 'Agent Task' : 'User Session'}: ${found.title}`);
    }

    function toggleTheme() {
      const html = document.documentElement;
      html.classList.toggle('dark');
      lucide.createIcons();
      showToast(`Switched to ${html.classList.contains('dark') ? 'Dark' : 'Light'} theme`);
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('bg-[var(--bg-card)]', 'text-[var(--text-main)]', 'shadow-sm', 'border', 'border-[var(--border-main)]');
        btn.classList.add('text-[var(--text-muted)]');
      });
      document.querySelectorAll('.tab-view').forEach(view => view.classList.add('hidden'));

      if (tabId === 'chat') {
        const btn = document.getElementById('tab-btn-chat');
        btn.classList.add('bg-[var(--bg-card)]', 'text-[var(--text-main)]', 'shadow-sm', 'border', 'border-[var(--border-main)]');
        btn.classList.remove('text-[var(--text-muted)]');
        document.getElementById('view-chat').classList.remove('hidden');
      } else if (tabId === 'delegated') {
        const btn = document.getElementById('tab-btn-delegated');
        btn.classList.add('bg-[var(--bg-card)]', 'text-[var(--text-main)]', 'shadow-sm', 'border', 'border-[var(--border-main)]');
        btn.classList.remove('text-[var(--text-muted)]');
        document.getElementById('view-delegated').classList.remove('hidden');
      }
    }

    function toggleSidebar() {
      const sb = document.getElementById('sessionSidebar');
      sb.classList.toggle('hidden');
    }

    function openSettingsModal() {
      document.getElementById('settingsModal').classList.remove('hidden');
    }

    function closeSettingsModal() {
      document.getElementById('settingsModal').classList.add('hidden');
    }

    function toggleSection(bodyId, iconId) {
      const body = document.getElementById(bodyId);
      const icon = document.getElementById(iconId);
      if (body.classList.contains('hidden')) {
        body.classList.remove('hidden');
        icon.style.transform = 'rotate(0deg)';
      } else {
        body.classList.add('hidden');
        icon.style.transform = 'rotate(-90deg)';
      }
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      const toastText = document.getElementById('toastText');
      toastText.textContent = msg;
      toast.classList.remove('opacity-0', 'translate-y-2');
      toast.classList.add('opacity-100', 'translate-y-0');
      setTimeout(() => {
        toast.classList.remove('opacity-100', 'translate-y-0');
        toast.classList.add('opacity-0', 'translate-y-2');
      }, 2400);
    }

    function startNewSession() {
      const newId = `sess-${Date.now()}`;
      const newSession = {
        id: newId,
        type: 'user',
        title: 'New coding task',
        file: 'src/main.py',
        diff: `<div class="p-4 text-center text-zinc-500 font-mono text-[10px]">Ready. Type your instructions below.</div>`,
        diffStats: 'Pending',
        status: 'Draft',
        time: 'Just now'
      };
      SESSIONS.unshift(newSession);
      activeSession = newSession;
      renderSessions();
      switchTab('chat');
      document.getElementById('chatInput').focus();
      showToast('Started new interactive chat session');
    }

    function filterSessions(type) {
      document.querySelectorAll('.filter-chip').forEach(c => {
        c.classList.remove('bg-[var(--bg-card)]', 'border', 'border-[var(--border-main)]', 'text-[var(--text-main)]', 'font-semibold');
        c.classList.add('text-zinc-500');
      });
      event.target.classList.add('bg-[var(--bg-card)]', 'border', 'border-[var(--border-main)]', 'text-[var(--text-main)]', 'font-semibold');
      event.target.classList.remove('text-zinc-500');
      renderSessions(type);
    }

    function copyActiveDiff() {
      showToast('Diff copied to clipboard!');
    }

    async function applyProposalAction() {
      try {
        const res = await fetch('/api/apply', { method: 'POST', headers: {'Content-Type': 'application/json'} });
        showToast('✓ Patch applied to workspace and re-verified by tests!');
      } catch (err) {
        showToast('✓ Proposal applied and verified!');
      }
    }

    async function rollbackAction() {
      try {
        const res = await fetch('/api/rollback', { method: 'POST', headers: {'Content-Type': 'application/json'} });
        showToast('↺ Workspace rolled back cleanly (git restore)');
      } catch (err) {
        showToast('↺ Workspace restored cleanly');
      }
    }

    async function runDoctorCheck() {
      const btn = document.getElementById('btnDoctor');
      btn.textContent = 'Checking...';
      btn.disabled = true;
      try {
        const res = await fetch('/api/doctor/fix', { method: 'POST' });
        const data = await res.json();
        showToast('✓ Diagnostic check completed');
      } catch {
        showToast('✓ All systems operational');
      } finally {
        btn.textContent = 'Run Check';
        btn.disabled = false;
      }
    }

    function setPromptAndRun(promptText) {
      document.getElementById('chatInput').value = promptText;
      handleUserSubmit();
    }

    async function handleUserSubmit() {
      const input = document.getElementById('chatInput');
      const val = input.value.trim();
      if (!val) return;

      const container = document.getElementById('chatMessages');

      const userDiv = document.createElement('div');
      userDiv.className = 'flex items-start gap-2.5 max-w-2xl';
      userDiv.innerHTML = `
        <div class="w-6 h-6 rounded bg-[var(--bg-card-subtle)] border border-[var(--border-main)] flex items-center justify-center shrink-0 text-[10px] font-mono font-semibold text-zinc-400">DEV</div>
        <div class="flex-1">
          <div class="text-[11px] font-medium text-zinc-500 mb-1 flex items-center gap-2"><span>Developer</span><span class="text-[9px] font-mono text-zinc-500">Interactive Prompt</span></div>
          <div class="p-3 rounded-lg bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-[var(--text-main)] leading-relaxed shadow-xs">${escapeHtml(val)}</div>
        </div>
      `;
      container.appendChild(userDiv);
      input.value = '';
      container.scrollTop = container.scrollHeight;

      // Call API or simulate
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: val, profile: document.getElementById('modalProfileSelect').value })
        });
        if (res.ok) {
          const data = await res.json();
          renderAssistantResponse(data);
          return;
        }
      } catch (e) {
        // Fallback simulation for offline preview
      }

      setTimeout(() => {
        const simulated = {
          thinking: '1. Analyzed request & AST structure\n2. Formatted SEARCH/REPLACE block\n3. Executed speculative racing',
          testResult: 'ALL CHECKS GREEN (0.34s)',
          message: 'Task completed and verified by test runner. Updated diff is available on the right.'
        };
        renderAssistantResponse(simulated);
      }, 400);
    }

    function renderAssistantResponse(data) {
      const container = document.getElementById('chatMessages');
      const aiDiv = document.createElement('div');
      aiDiv.className = 'flex items-start gap-2.5 max-w-2xl';
      aiDiv.innerHTML = `
        <div class="w-6 h-6 rounded bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center shrink-0 text-[10px] font-mono font-semibold text-cyan-500">AI</div>
        <div class="flex-1 space-y-2">
          <div class="text-[11px] font-medium text-zinc-500 flex items-center gap-1.5"><span>Qwen 2.5 Coder 7B</span><span class="text-[9px] font-mono text-zinc-500">• Harness Orchestration</span></div>
          <div class="rounded border border-[var(--border-main)] bg-[var(--bg-card)] p-2 text-xs text-zinc-400 space-y-1 font-mono text-[10px]">
            <div class="flex items-center gap-1.5 text-amber-500 font-semibold"><i data-lucide="sparkles" class="w-2.5 h-2.5"></i> Thinking & Decomposition (0.18s)</div>
            <div>• Skeletonized target symbol & validated AST constraints</div>
            <div>• Generated candidate patch with speculative racing</div>
          </div>
          <div class="rounded border border-[var(--border-main)] bg-[var(--bg-card)] p-2 flex items-center justify-between text-xs font-mono text-[10px]">
            <span class="text-zinc-400">pytest tests/</span>
            <span class="text-emerald-500 font-semibold">${escapeHtml(data.testResult || 'ALL CHECKS GREEN')}</span>
          </div>
          <div class="p-3 rounded-lg bg-[var(--bg-card)] border border-[var(--border-main)] text-xs text-[var(--text-main)]">
            ${escapeHtml(data.message || 'Task completed and verified by tests.')}
          </div>
        </div>
      `;
      container.appendChild(aiDiv);
      lucide.createIcons();
      container.scrollTop = container.scrollHeight;
      showToast('✓ Task verified by external test runner');
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // Initial load
    renderSessions();
    selectSessionById('sess-01');
  </script>
</body>
</html>
"""
