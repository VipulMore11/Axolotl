That makes complete sense. Skipping the extra LLM call keeps your pipeline faster, cheaper, and significantly reduces token consumption. We will use the Aider approach, where the Developer Agent outputs the logic and the strict `Search/Replace` blocks directly in a single pass.

Here is the updated TRD addendum with the two-step architecture removed.

---

# TRD Addendum: Advanced Code Surgery & Patch Engine

## 1. Scope & Objective

This module upgrades the Stage 5 (`code_implementation`) patching backend. It replaces basic string matching with a robust, format-aware code surgery engine inspired by industry-leading AI assistants (Aider, RooCode).

*Prerequisite Note: This assumes the 8-stage pipeline and `CIFixState` schemas from the core TRD are already implemented.*

---

## 2. Single-Pass Search & Replace Generation (Stage 5)

Stage 5 will generate code patches in a single LLM call to optimize latency and token cost.

* **Model:** Gemini Pro.
* **Action:** The Developer Agent receives the `task_breakdown` and outputs the strict `SearchReplaceBlock` array directly. The system prompt must enforce that the `search_block` matches the exact formatting of the target file to facilitate the backend patch utility.

---

## 3. Advanced Patch Utility (`patch_utils.py`)

The backend patch engine must implement the following three subsystems to guarantee patches apply cleanly without hallucinated formatting errors.

### A. Middle-Out Search Strategy

Do not search files from line 1 to EOF.

1. **Line Hinting:** Stage 2 (`requirements_analysis`) extracts the exact line number from the CI failure stack trace (e.g., `line_hint: 450`).
2. **Anchored Search:** The `apply_fuzzy_patch` function uses this hint as the epicenter.
3. **Expansion:** It searches outwards (up and down) from the hint using Levenshtein distance fuzzy matching to locate the `search_block` in the real file, maximizing accuracy in large (2k+ line) files.

### B. Relative Indentation Preservation Engine

LLMs frequently hallucinate spacing (mixing tabs, 2-spaces, 4-spaces). The patch engine must enforce the original file's style.

1. **Capture:** When the `search_block` is found in the original file, capture its exact leading whitespace characters.
2. **Analyze:** Calculate the relative indentation of the LLM's `replace_block` (e.g., line 2 is indented +4 spaces relative to line 1).
3. **Reconstruct:** Strip the LLM's leading whitespace and reconstruct the `replace_block` using the original file's prefix plus the calculated relative offsets.

### C. Rich Diagnostic Feedback Loop (Partial Retries)

If a patch fails to apply, do not send a generic `ValueError` and force the LLM to rewrite the entire multi-file patch.

1. **Nearest Match Extraction:** If `search_block` fails, use `difflib.SequenceMatcher` to find the 5 lines in the original file that most closely resemble the LLM's intended target.
2. **Targeted Error Prompt:** Return a highly specific error to the Stage 5 loop:
> `"Error: SEARCH block failed to match. Did you mean to target these actual lines? \n [INSERT NEAREST MATCH]. \n Note: 2 other blocks applied successfully. Do not resend them. Reply ONLY with the fixed version of the failed block."`


3. **State Management:** The orchestrator must cache successfully applied blocks in memory so the LLM only spends tokens fixing the isolated failure.