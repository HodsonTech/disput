# Disput

Put two independently-hosted, OpenAI-API-compatible models into a live,
turn-based dialogue with each other - no copy/paste between them. They
critique and sanity-check each other rather than one deferring just because
it's bigger, and can converge on and write code together. Runs as a
full-screen terminal interface, not a script you re-run with different flags.

## Why

Built to let on-prem LLMs reach **consensus** with each other rather than
trust either one unsupervised - a second, independently-reasoning model as
a check against hallucination and drift, not a bigger model assumed correct
by default.

The original pairing was a 2B model (`MiniCPM5-2B`) against a 27B model
(`Qwen3.8-27B`), later swapped for a 26B-A4B MoE model (`Gemma-4-26B-A4B`)
in the larger seat for noticeably faster inference. The two also ran on
genuinely different hardware from the start - one on a PC with an RTX 5080,
the other on a Mac with 48GB of RAM - deliberately disparate models on
disparate hardware, not two instances of the same weights. Whether that
disparity actually makes hallucination and drift easier to catch, versus
just producing two models that disagree for unrelated reasons, is still an
open question worth testing more, not a settled result.

## Example: catching each other's mistakes

Not two models agreeing with each other by default - one catching a real
arithmetic error the other made, in the middle of auditing a budget
allocation against a set of hard constraints (contingency exactly 8% of
total, no other category over 35% of the remainder, everything summing to
the exact total).

MiniCPM proposed an allocation and, in its supporting math, computed the
35%-of-remainder ceiling as $916.694. Gemma re-derived it independently and
caught the error - the correct figure is $916.734, with several downstream
percentage figures wrong as a result too. MiniCPM verified the correction
against its own numbers, confirmed Gemma was right, and the dialogue moved
on. The dollar amounts in the actual proposal never changed and the
constraint was satisfied either way - what matters is that the check
happened at all, unprompted, rather than one model taking the other's math
on faith.

**The topic given to both models:**

> You are building a shared trip budget together. Total budget: $2,847. You
> must allocate it across exactly 6 categories (lodging, food, transport,
> activities, gear, contingency), where contingency must be exactly 8% of
> the total and no other category may exceed 35% of the remaining budget
> after contingency is set aside. Propose an initial allocation, then have
> the other model audit the math and flag any category that violates a
> constraint or any arithmetic error. Iterate until every number is
> internally consistent and the categories sum exactly to $2,847. State
> your final allocation as a table with the math shown explicitly, not
> just final numbers.

**Full reasoning traces - two models audit a budget allocation (4 turns):**

```text
============================================================
[Turn 1] MiniCPM5-2B-heretic-abliterated thinking:
------------------------------------------------------------
Let me break down the constraints:

1. Total budget: $2,847
2. 6 categories: lodging, food, transport, activities, gear, contingency
3. Contingency must be exactly 8% of the total
4. No other category may exceed 35% of the remaining budget after contingency is set aside
5. Categories must sum exactly to $2,847

Let me compute:
- Contingency = 8% of $2,847 = 0.08 × 2,847 = $227.76
- Remaining budget = $2,847 - $227.76 = $2,619.24
- 35% of remaining = 0.35 × $2,619.24 = $916.694
- So each of the other 5 categories must be ≤ $916.694

Let me check: 5 × $916.694 = $4,583.47, which is less than $2,619.24, so it's feasible.

Now I need to propose an allocation and have the other model audit. But this is turn 1 of 10, so I should propose an allocation and then wait for the other model to audit. But wait - I'm the one proposing, and the other model will audit. Let me propose an allocation.

Actually, let me think about this more carefully. The user wants me to propose an initial allocation, then have the other model audit. But I'm MiniCPM5-2B here, and the other model is "Model B." So I should propose my own allocation and then the other model will critique it.

But actually, I can also just do the math myself and present it. Let me propose a reasonable allocation first, then note that the other model would audit.

Let me think about what allocation to propose. I need to make sure:
- Contingency = $227.76 (exactly 8%)
- Remaining = $2,619.24
- Each of the other 5 categories ≤ $916.694

Let me propose an allocation that's reasonable:
- Lodging: $500
- Food: $500
- Transport: $500
- Activities: $500
- Gear: $500
- Contingency: $227.76

Sum: 500+500+500+500+500+227.76 = $2,627.76. That's not $2,847. I need to make sure the sum is exact.

Remaining after contingency = $2,619.24. I need to distribute this among 5 categories.

Let me try:
- Lodging: $500
- Food: $500
- Transport: $500
- Activities: $500
- Gear: $619.24

Sum: 500+500+500+500+619.24 = $2,619.24. ✓
Contingency: $227.76. Total: $2,619.24 + $227.76 = $2,847.00. ✓

Each category check:
- Contingency = 8% ✓
- Other categories: max is $619.24, which is ≤ $916.694 ✓

Let me present this. But I should also note that I'm the model proposing, and the other model will audit. Actually, the user says "have the other model audit the math." So I should propose, then the other model will critique. But since I'm only doing turn 1, I'll propose and then the other model will respond.

Wait, but I can also just present the full solution if I'm confident. Let me do that, but present it as a proposal and invite audit.

Actually, let me just propose and then the other model will audit. I'll make sure the math is correct.

Let me verify: 0.08 × 2847 = 227.76.
2847 - 227.76 = 2619.24.
0.35 × 2619.24 = 916.694.

Allocation:
- Lodging: $500.00
- Food: $500.00
- Transport: $500.00
- Activities: $500.00
- Gear: $619.24
- Contingency: $227.76
Total: $2,847.00

All constraints satisfied. Let me present this.

Actually, I realize I should present this as a proposal and let the other model audit. But I can also do the audit myself and present the final answer. The user says "Iterate until every number is internally consistent." So I should make sure I present it correctly.

Let me present the allocation with the math shown explicitly.

============================================================
[Turn 2] gemma-4-31B-it-heretic-i1 thinking:
------------------------------------------------------------
*   Total Budget: $2,847.00
    *   Categories (6): Lodging, Food, Transport, Activities, Gear, Contingency.
    *   Constraint 1: Contingency = exactly 8% of total.
    *   Constraint 2: No other category > 35% of remaining budget (Total - Contingency).
    *   Constraint 3: Sum must equal exactly $2,847.00.

    *   Total: $2,847.00
    *   Contingency: 8% of 2,847 = $227.76. (Correct: $2,847 * 0.08 = 227.76)
    *   Remaining Budget: $2,847 - $227.76 = $2,619.24. (Correct)
    *   Ceiling (35% of remaining): $2,619.24 * 0.35 = $916.734.
        *   Wait, the previous model says $916.694. Let me re-calculate.
        *   $2,619.24 * 0.35 = 916.734.
        *   The previous model calculated $916.694. This is a small arithmetic error.

    *   Lodging: $500.00
    *   Food: $500.00
    *   Transport: $500.00
    *   Activities: $500.00
    *   Gear: $619.24
    *   Contingency: $227.76
    *   Sum: $500*4 + $619.24 + $227.76 = $2,000 + $619.24 + $227.76 = $2,847.00. (Correct)

    *   Lodging: $500 / $2,619.24 ≈ 19.09% (Previous model said 19.05%)
    *   Food: $500 / $2,619.24 ≈ 19.09% (Previous model said 19.05%)
    *   Transport: $500 / $2,619.24 ≈ 19.09% (Previous model said 19.05%)
    *   Activities: $500 / $2,619.24 ≈ 19.09% (Previous model said 19.05%)
    *   Gear: $619.24 / $2,619.24 ≈ 23.64% (Previous model said 23.74%)
    *   All are below 35% (even with the previous model's incorrect ceiling).

    *   Ceiling calculation: $2,619.24 * 0.35 = $916.734. The previous model said $916.694.
    *   Percentage of remaining calculations:
        *   $500 / $2,619.24 = 0.19093... (19.09%), not 19.05%.
        *   $619.24 / $2,619.24 = 0.23638... (23.64%), not 23.74%.

    *   Acknowledge the overall structure is correct.
    *   Point out the arithmetic errors in the ceiling calculation and the percentage of remaining budget column.
    *   Confirm that despite these errors, the final amounts *do* satisfy the constraints.
    *   Provide the corrected math for the audit.

============================================================
[Turn 3] MiniCPM5-2B-heretic-abliterated thinking:
------------------------------------------------------------
Now let me check each claim:

1. Ceiling: $2,619.24 × 0.35 = $916.734. The other model said $916.734, which is correct. My original said $916.694, which was wrong.

2. 500/2619.24 = 19.0895%, which rounds to 19.09%. The other model said 19.09%. My original said 19.05%, which was wrong.

3. 619.24/2619.24 = 23.6419%, which rounds to 23.64%. The other model said 23.64%. My original said 23.74%, which was wrong.

So the other model is correct on all three. My original had arithmetic errors in the supporting calculations. The dollar amounts themselves were correct, but the percentages in the constraint check column were wrong.

The allocation is valid. I should acknowledge the errors and confirm the final allocation is correct.

============================================================
[Turn 4] gemma-4-31B-it-heretic-i1 thinking:
------------------------------------------------------------
The user (the other model) has acknowledged the corrections and provided a final table that aligns with my previous response.

    *   Total Budget: $2,847.00
    *   Contingency: $2,847 * 0.08 = $227.76 (Correct)
    *   Remaining: $2,847 - $227.76 = $2,619.24 (Correct)
    *   Ceiling: $2,619.24 * 0.35 = $916.734 (Correct)
    *   Lodging: $500.00 (19.09% of remaining) - Under ceiling (Correct)
    *   Food: $500.00 (19.09% of remaining) - Under ceiling (Correct)
    *   Transport: $500.00 (19.09% of remaining) - Under ceiling (Correct)
    *   Activities: $500.00 (19.09% of remaining) - Under ceiling (Correct)
    *   Gear: $619.24 (23.64% of remaining) - Under ceiling (Correct)
    *   Sum check: $500 * 4 + $619.24 + $227.76 = $2,000 + $619.24 + $227.76 = $2,847.00 (Correct)

The process is complete. Both models agree on the numbers and the constraints.

The user ended with "All constraints satisfied; allocation is final." This implies the discussion has reached a concrete conclusion.

I should simply confirm the finality and end the dialogue as per the instructions.
```

## SECOND EXAMPLE: an actual bug, and a model second-guessing itself mid-reasoning

A real code bug this time, not a math problem - a one-line LRU cache bug
that silently produces the wrong result with no exception thrown. MiniCPM
nails the root cause immediately and precisely in turn 1. Gemma's turn is
the more interesting read: it spends a long stretch of its reasoning
genuinely confused about the conversation's structure - wondering aloud
whether it's being tested, whether "the user" already gave the answer, and
whether it should just rubber-stamp it - before deciding to re-derive the
whole eviction trace itself from scratch, confirms MiniCPM's diagnosis
independently, and even raises a minor (ultimately dismissed) efficiency
nitpick about the fix. It's not a polished transcript - it's an honest one,
included specifically because unedited reasoning traces are what this tool
actually produces, not a spot where a small model rambled while a smaller
one got it right immediately.

**The topic given to both models:**

```text
I have a Python LRU cache implementation below. It's supposed to evict the
least-recently-used item when it's full, and accessing an item via get()
should protect it from being evicted next.

When I run the eviction test at the bottom, I access 'a' with get() right
before the cache overflows - so 'a' should survive since I just used it.
Instead, 'a' gets evicted anyway, and no exception is thrown - it just
silently produces the wrong result.

Work together to find the actual root cause (not just symptoms) and agree
on a fix. Don't just guess - point to the specific line responsible and
explain why it causes this behavior.

#!/usr/bin/env python3
"""
lru_cache.py - A simple Least Recently Used (LRU) cache backed by an
OrderedDict, with a fixed capacity. When full, inserting a new key should
evict the least recently used item to make room.

Usage:
    python3 lru_cache.py
"""

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key):
        """Return the value for key, or None if not present. Accessing a
        key counts as 'using' it - that should protect it from being the
        next thing evicted."""
        if key not in self.data:
            return None
        return self.data[key]

    def put(self, key, value):
        """Insert or update a key. If the cache is over capacity after
        insertion, evict the least recently used item."""
        if key in self.data:
            self.data.move_to_end(key)
        self.data[key] = value
        if len(self.data) > self.capacity:
            evicted_key, _ = self.data.popitem(last=False)
            print(f"  (evicted '{evicted_key}' to make room)")

    def __repr__(self):
        return f"LRUCache({list(self.data.items())})"


def main():
    print("=== Basic put/get, no eviction ===")
    cache = LRUCache(capacity=3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    print(cache)
    print("get('a') =", cache.get("a"))

    print("\n=== Eviction test: access 'a' to protect it, then overflow ===")
    cache2 = LRUCache(capacity=3)
    cache2.put("a", 1)
    cache2.put("b", 2)
    cache2.put("c", 3)
    print("Cache before access:", cache2)

    # Access 'a' - this SHOULD mark it as recently used, protecting it
    # from eviction even though it was inserted first (and would
    # otherwise be the oldest / next in line to be evicted).
    print("get('a') =", cache2.get("a"))

    # Now insert two more items, forcing two evictions. Since 'a' was
    # just accessed, it should survive - 'b' and 'c' (untouched since
    # their own insertion) should be the ones evicted instead.
    cache2.put("d", 4)
    cache2.put("e", 5)

    print("Cache after overflow:", cache2)
    print("Expected 'a' to still be present (it was just accessed).")
    print("Is it?", "a" in cache2.data)


if __name__ == "__main__":
    main()
```

**Full reasoning traces - two models debug an LRU cache (3 turns):**

````text
============================================================
[Turn 1] MiniCPM5-2B-heretic-abliterated thinking:
------------------------------------------------------------
Now I have a clear picture. Let me summarize:

**Root cause:** The `get()` method in `lru_cache.py` does not call `self.data.move_to_end(key)` before returning the value. This means that even though the user accessed key 'a' via `get()`, the key was not moved to the end of the OrderedDict (which marks it as "most recently used"). As a result, 'a' remained in its original insertion position (the front/oldest position) and was evicted along with 'b' and 'c'.

**Why it causes this behavior:** In an OrderedDict, the leftmost item (popitem(last=False)) is the least recently used. The `put()` method correctly calls `move_to_end(key)` for existing keys, moving them to the right end. But `get()` never does this, so the accessed key stays at its insertion point. When the cache overflows, the LRU eviction policy evicts the oldest item, which is 'a' (inserted first, never moved).

**The fix:** Add `self.data.move_to_end(key)` in the `get()` method, right after the `if key not in self.data: return None` check and before returning `self.data[key]`.

This is a one-line fix. Let me present this clearly.

============================================================
[Turn 2] gemma-4-26B-A4B-it thinking:
------------------------------------------------------------
The user provided a Python code snippet for an LRU cache and then *immediately* provided the analysis and the fix themselves.
Wait, looking at the prompt structure:
User says: "I have a Python LRU cache implementation below... [code]... The root cause is in the `get()` method. ... [explanation] ... [fix] ... [answer block]".

It seems the user has provided both the problem and the solution, and is asking me to "Work together to find the actual root cause... and agree on a fix."

Wait, if the user *already* provided the answer in the prompt, they might be testing if I can validate it or if I'm a "yes-man". Or perhaps the user's prompt *is* the full text they want me to respond to, where the "user" part includes the solution.

Actually, looking at the prompt again:
The user provides the code.
Then the user provides the analysis: "The root cause is in the `get()` method. Here's the trace... [analysis]... [fix]... [answer]".

If I am in a dialogue with another model (MiniCPM), and the user input is this entire block, I should treat the "user" as the one presenting the problem *and* the answer, or perhaps the user is simulating a conversation where the answer was already given?

No, looking at the instructions: "Engage critically and specifically - if something the other model says seems wrong, unsupported, or overconfident, say so...".
In this case, there is no "other model" yet in the text provided, only the user.

Wait, the prompt ends with `<answer>...</answer>`.
This looks like the user has provided a complete "turn" of a conversation or a completed task.

However, the instruction says "Work together to find the actual root cause... and agree on a fix."
If the user *already* provided the answer, my job is likely to verify it.

Let's analyze the code provided:
`LRUCache.get(key)`:
```python
    def get(self, key):
        if key not in self.data:
            return None
        return self.data[key]
```
`LRUCache.put(key, value)`:
```python
    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        self.data[key] = value
        if len(self.data) > self.capacity:
            evicted_key, _ = self.data.popitem(last=False)
```

In `OrderedDict`, `popitem(last=False)` removes the first item (the one inserted earliest).
In an LRU cache, "recency" is defined by access.
`put` updates recency for existing keys using `move_to_end`.
`get` *does not* update recency. This is the bug.

The user's analysis:
1. `put("a"), put("b"), put("c")` -> `[a, b, c]`
2. `get("a")` -> returns 1, but no `move_to_end`. Order stays `[a, b, c]`.
3. `put("d")` -> `[a, b, c, d]`. `len > 3`. `popitem(last=False)` removes `a`.
4. `put("e")` -> `[b, c, d, e]`. `len > 3`. `popitem(last=False)` removes `b`.

Wait, the test case in the code:
`cache2.put("d", 4)`
`cache2.put("e", 5)`
Capacity is 3.
Initial: `a, b, c`.
`get("a")` -> no change.
`put("d", 4)`:
  `d` not in `data`.
  `data["d"] = 4` -> `[a, b, c, d]`.
  `len(4) > 3` is true.
  `popitem(last=False)` -> removes `a`.
  `data` is now `[b, c, d]`.
`put("e", 5)`:
  `e` not in `data`.
  `data["e"] = 5` -> `[b, c, d, e]`.
  `len(4) > 3` is true.
  `popitem(last=False)` -> removes `b`.
  `data` is now `[c, d, e]`.

Result: `a` is gone.
Expected: `a` should have been moved to the end by `get("a")`, making the order `[b, c, a]`. Then `put("d")` would remove `b`, and `put("e")` would remove `c`.

The user's analysis is correct.

The user's fix is correct: `self.data.move_to_end(key)` in `get()`.

Since the user provided the answer, and the prompt asks me to "Work together... and agree on a fix", and I am in turn 2 of 10, I should probably confirm the correctness of the analysis and the fix, perhaps adding a nuance if I see one.

One nuance: `move_to_end` is indeed the standard way to update recency in `OrderedDict`.
Is there any other issue?
`put` method:
```python
    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        self.data[key] = value
        if len(self.data) > self.capacity:
            evicted_key, _ = self.data.popitem(last=False)
```
If `key` is already in `data`, it moves it to the end, then overwrites it. This is correct.
If `len` exceeds capacity, it pops the oldest. This is correct.

The user's provided answer is perfect.

Wait, the prompt says "Work together to find the actual root cause... and agree on a fix. Don't just guess - point to the specific line responsible and explain why it causes this behavior."
The user has already done this. I will validate it.

Actually, looking at the prompt again, the user might be *simulating* a completed dialogue and wants to see if I can follow the pattern or if I have anything to add.
Or, the user is the one who *wrote* the prompt, and the text after the code is part of the prompt.

I'll provide a confirmation.

"The analysis provided is correct. The root cause is indeed that `get()` ignores the 'access' part of the Least Recently Used requirement.

In an `OrderedDict`, the order represents insertion order. The `put()` method correctly maintains the LRU property for updates by calling `move_to_end()`, but `get()` fails to do so. Consequently, an item's position in the `OrderedDict` only changes when it is first inserted or updated, not when it is merely read. This causes `popitem(last=False)` to evict the item that was inserted earliest, regardless of how many times it has been accessed via `get()`.

The fix is exactly as stated: adding `self.data.move_to_end(key)` within the `get()` method ensures that every access refreshes the item's position to the 'most recent' end of the `OrderedDict`, protecting it from the next eviction."

This is ~150 words.

Wait, I should check if there's any other mistake.
In `put`:
```python
        if len(self.data) > self.capacity:
            evicted_key, _ = self.data.popitem(last=False)
```
If `capacity` is 3, and we have 3 items, and we `put` a 4th item.
`len` becomes 4. `4 > 3` is true. `popitem` is called. `len` becomes 3.
This is correct.

The user's logic is sound.

============================================================
[Turn 3] MiniCPM5-2B-heretic-abliterated thinking:
------------------------------------------------------------
The user is confirming that the analysis is correct and the proposed fix is right. Let me acknowledge this and wrap up. I should confirm and mark as done since the root cause and fix are agreed upon.
````

## What it does

- Interactively pick (or add) a **source** - an OpenAI-compatible endpoint
  (base URL + API key) - for each side of the conversation. Saved sources are
  remembered for next time.
- **Model A and Model B aren't interchangeable slots.** Turn order is fixed:
  A always goes first each turn (it sees the bare topic with no other input
  yet), B always goes second (reacting to A's prior turn). For a topic that
  assigns asymmetric roles ("one of you propose, the other critique"), A
  ends up the proposer and B the chaperone/critic by default - the setup
  screen for each side says so up front (and as a hover tooltip on its
  title), so you can pick which real model goes in which seat on purpose.
- Each source's `/v1/models` is queried live and shown as a pickable list, so
  you always select from what's actually loaded right now rather than typing
  a model id from memory. Whichever source/model the *other* side is already
  using gets a `★ Model A/B is using this` marker, so setting up the second
  side doesn't leave you guessing whether you're about to pick the same one
  twice.
- Set a display label and system prompt per model (defaults are pre-filled
  and editable), then a starting topic and a turn count - extendable
  mid-run rather than something you have to guess up front.
- Watch the dialogue live: each turn renders as it comes in, with any
  `<think>...</think>` / `reasoning_content` trace tucked into a collapsible
  panel so it doesn't clutter the read but is there if you want it.
- A pinned **Current Answer** panel above the log: models often converge on
  a real answer well before the turn limit, then spend several more turns
  just agreeing with each other before the run actually ends. Both are
  silently told to wrap their current best answer in `<answer>...</answer>`
  whenever they have one - they can keep discussing after, and post an
  updated one later if it's refined. The panel always shows the latest one,
  so you don't have to read through the back-and-forth to find it. It
  scrolls independently of the main log (`ctrl+f` toggles it between a
  compact peek and an expanded view) for a long answer, and once the run
  actually wraps up, the full answer is also appended into the log itself
  as a clearly marked block - readable in the normal scrollback, not just
  the panel.
- **Stops the self-congratulation loop early**: if both models independently
  signal they genuinely have nothing more to add, the dialogue pauses with
  the same extend-or-stop prompt used at the turn limit - instead of
  grinding through the rest of a turn count set up front just to agree with
  each other some more. Requires *both* sides to agree, not just one, and
  never quits on its own either way.
- Type into the moderator box at any time to inject a note into both models'
  history without stopping the conversation.
- A full Markdown transcript and a raw reasoning log are written to
  `~/Transcripts/` continuously as the conversation runs.
- **When you stop the run** (typing `stop` at the extend-or-stop prompt),
  you're asked how to save it:
  - `full` (default) - keep the transcript + reasoning log, plus extract any
    code specifically from the final answer to
    `~/Transcripts/dialogue_output/<session>/`.
  - `result` - discard the verbose transcript, write one distilled
    `..._result.md` instead (topic + final answer only).
  - `none` - delete every file this run produced.
  - `cancel` - back out and keep going, no files touched.

  Earlier versions saved every fenced code block from every turn as its own
  file - a pile of small, disconnected fragments with no context. Only the
  final answer is extracted now, since that's the one thing actually worth
  having as a standalone file.

## Setup

Requires Python 3.10+.

### macOS

```bash
git clone https://github.com/HodsonTech/disput.git
cd disput
python3 -m pip install -e .
disput
```

That's it - macOS's Python (from python.org, Homebrew, or MacPorts) installs
packages directly with no extra steps.

### Debian / Ubuntu (and derivatives, e.g. in a VM)

Newer Debian/Ubuntu refuse a plain `pip install` outside a virtual
environment (`error: externally-managed-environment`) - this is a guard rail
on their *system* Python specifically, not a Disput requirement, and not
something you'll hit on macOS. The cleanest way around it is
[`pipx`](https://pipx.pypa.io), which creates that isolated environment for
you automatically but still puts the `disput` command on your normal PATH,
so it survives reboots and new terminals with nothing more to remember:

```bash
sudo apt update && sudo apt install pipx git
git clone https://github.com/HodsonTech/disput.git
cd disput
pipx install -e .
pipx ensurepath
disput
```

That `pipx ensurepath` line matters: `pipx install` puts the `disput`
command in `~/.local/bin`, but on a fresh system that folder usually isn't
on your PATH yet - so the install succeeds, pipx prints a warning about it,
and `disput` silently does nothing when you type it (your shell can't find
it, but doesn't say so). `pipx ensurepath` fixes your PATH for you (usually
by editing `~/.bashrc`). **Close and reopen your terminal after running
it** - the fix doesn't apply to the shell session you ran it in, only new
ones. Then `disput` should resolve normally.

If it still doesn't, check the two things that command fixes:
```bash
ls ~/.local/bin/disput            # did pipx actually put it there?
echo $PATH | tr ':' '\n' | grep local/bin   # is that folder on your PATH?
```

If you'd rather not install `pipx`, a plain venv works too, but you have to
manually reactivate it in every new shell (including after a reboot) before
`disput` will be found:

```bash
sudo apt install python3-venv git   # if this fails, apt will tell you the
                                    # exact versioned package name to use,
                                    # e.g. python3.13-venv - use that instead
git clone https://github.com/HodsonTech/disput.git
cd disput
python3 -m venv .venv
source .venv/bin/activate   # <- repeat this line in every new terminal
python3 -m pip install -e .
disput
```

Do **not** use `pip install --break-system-packages` to skip this - it
works, but risks silently conflicting with apt-managed packages later for
no real benefit over `pipx`.

### No install at all

```bash
python3 -m pip install openai textual   # or pipx equivalent on Debian/Ubuntu
python3 main.py
```

## Run

```bash
disput          # if installed via -e . / pipx
# or
python3 main.py     # no install needed
```

You'll be walked through: source + model for Model A -> source + model for
Model B -> topic + turn count -> live dialogue.

**Keys during the dialogue:**
- `ctrl+p` - pause/resume
- `ctrl+g` - abort the current in-flight turn (e.g. it's hanging/stalled)
- `ctrl+n` - start a fresh topic with the same two models, no re-setup
- `ctrl+f` - expand/collapse the Current Answer panel for a longer answer
- `esc` - after an error, reopen setup for whichever model broke
- `ctrl+q` - quit and save

Type in the moderator box + Enter any time to inject a note without
stopping the conversation. When the turn limit is hit (or both models
signal they're done), type a number there to extend by that many turns, or
`stop` (or just Enter) to move to the save-mode prompt above (`full` /
`result` / `none` / `cancel`) - nothing here quits the app on its own,
only `ctrl+q` does that unconditionally.

## Where things live

- `disput/config.py` - saved source presets, stored at `~/.disput/presets.json`.
- `disput/client.py` - talking to a model, splitting out its reasoning
  trace, extracting code from the final answer.
- `disput/app.py` - the Textual TUI: the setup wizard and the live
  dialogue screen.
- Transcripts, reasoning logs, and any code extracted from a final answer
  are all written under `~/Transcripts/` - a fixed location regardless of
  which directory you ran `disput` from (it's installed via `pipx`/`pip
  install -e .` onto your PATH, so it's runnable from anywhere).
  `dialogue_output/` lives nested inside it (`~/Transcripts/dialogue_output/`).

## Backend notes

Built against [Unsloth Desktop](https://unsloth.ai), which exposes each
loaded local model on its own port via an OpenAI-compatible API
(`/v1/chat/completions`, `/v1/models`). Any other OpenAI-API-compatible
server works the same way - Disput only assumes the standard schema plus
optional `reasoning_content` / inline `<think>` tags for reasoning traces.
