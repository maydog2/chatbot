# State Model

## 1. Overview

The chat bot is not a single-turn prompt: it keeps **persistent, per-relationship state** so replies can reflect how the conversation has been going, not only the latest user message. That state is **heuristic and product-shaped**—numeric bands, mood labels, and rules tuned for continuity and tone—not a clinical or learned model of the user.

Compared with a plain “system prompt + history” chatbot, this stack **feeds relationship-style signals into every turn’s instructions** (and into **initiative**: how much the bot steers or extends the thread). The model still generates the actual words; state **does not** substitute for generation—it **narrows how** the backend asks the model to behave.

## 2. Goals and Scope

### Goals

- Make replies feel **more continuous** across turns and visits.
- Keep behavior **companion-specific** (per bot persona and per user–bot relationship).
- Support **lightweight personalization** without per-user trained models.
- Keep the **backend** authoritative for how state is interpreted and applied.

### Scope

- State is **application-controlled** and **rule-based** (plus a small LLM step that only **classifies** turns into discrete trigger ids—see §5).
- State **influences** system prompt text, initiative instructions, and light **post-processing** of the assistant reply—not direct token-level control.
- Relationship-style metrics are **persistent** across sessions and reloads (for the same account and bot).

### Non-goals

- **Not** a real-time emotion detector or psychological instrument.
- **Not** a psychologically validated user model.
- **Not** learned personalization (no fine-tuned companion model from user data).
- **Not** long-term **semantic** memory (no RAG / vector recall of “everything we ever said” in this design).
- **Not** guaranteed consistency across different LLM providers or model versions—wording and compliance still vary.

## 3. State Dimensions

Each dimension below is a **design handle** for the product. Numbers are **bounded** (typically 0–100) and **clamped** in code; they are not calibrated to real-world units.

### 3.1 Trust

- **What it is:** How much the bot **assumes good intent** and relaxes guardrails in tone—more direct vs. more cautious.
- **What it is not:** Legal trust, real-world safety, or a score you should treat as “objectively correct.”
- **Use:** Reflected in the system instructions as lower → more guarded/formal; higher → more direct and willing to assume good intent.

### 3.2 Resonance

- **What it is:** How **aligned or “in sync”** the exchange feels—emotional availability and responsiveness of the voice.
- **What it is not:** Chat quality metrics or user satisfaction scores.
- **Use:** Lower → cooler or more reserved; higher → warmer, more attuned phrasing in instructions.

### 3.3 Affection

- **What it is:** **Warmth and care** in the relational layer—softer, gentler stance when high.
- **What it is not:** Romance or attachment as a formal mode; still bounded by character direction and safety lines in prompts.
- **Use:** Higher → instructions bias toward gentleness and comfort when appropriate.

### 3.4 Openness

- **What it is:** How much the character **shares inner thoughts / vulnerability** vs. stays private.
- **What it is not:** User openness; it models the **bot’s** expressive stance.
- **Use:** Higher → prompt asks for more self-disclosure from the character; lower → more reserved.

### 3.5 Mood

- **What it is:** A **short list** of discrete **interaction stances**: Calm, Quiet, Happy, Irritated, Playful, Tired (enforced as a small closed set by the application).
- **What it is not:** Free-form emotion tags or continuous valence/arousal from the user’s face/voice.
- **Use:** Each label maps to a **mood playbook** paragraph in the system prompt (pacing, warmth, irritability, brevity). Special case: **Irritated** also **dampens** positive bumps from triggers for trust/resonance/affection/openness that turn.

**Supporting machinery (not shown in the UI as first-class sliders):** the backend keeps **internal mood axes** (e.g. energy, irritation, outwardness) that **drift toward baselines over wall-clock time** between updates. The **stored mood label** is **not** recomputed from those axes on every read; label moves come mainly from **trigger-driven** override/nudge plus inertia rules (see §5).

### 3.6 Interests (bot profile)

- **What it is:** **Primary** and **secondary** interest tags on the bot—used to bias **topic framing**, examples, and a per-turn **interest nudge** block when the user’s message seems on-topic.
- **What it is not:** A full user hobby graph or crawling the web for hobbies.
- **Use:** Shapes prompt content and feeds **initiative** (interest match can raise effective initiative score).

### 3.7 Initiative (bot setting + effective score)

- **What it is:** **Base initiative** is a bot setting: `low` / `medium` / `high`. At runtime the app computes an **effective score** from base + **trust**, **resonance**, **recent user behavior** (e.g. short or passive turns), **interest match**, and optional **tone hints** from a small classifier (hostile/warm)—then maps that to a **band** (very_low → very_high).
- **What it is not:** “Ask a question every turn”; it modulates **momentum** (follow-ups, extensions, how hard the bot pushes the thread).
- **Use:** Appends a **“Conversational initiative”** instruction block to the system prompt and can **post-process** the assistant reply (e.g. constraints on closing questions when initiative is low). **Tired** / **Irritated** moods in the playbook already push toward **less** proactive behavior; initiative stacks on top of that framing.

### 3.8 Related configuration (persona, naming, addressing)

These are **not** the numeric relationship metrics, but they **ship on the same turn** as them: **character direction**, **in-app name**, and **form of address** on the **bot** (with user profile fallback for how to address the user). They change when the user **edits the bot or profile**, not from turn triggers; together with §3.1–3.7 they shape what the model is asked to do.

## 4. Storage and Ownership

- **User** — account and profile fields (e.g. display name) used when the bot has no explicit form of address.
- **Bot** — persona text, name, avatar, **interests**, **initiative** setting, **form of address**, **direction**; each bot has its own **chat transcript** (messages) in a dedicated session.
- **Relationship state** — **one row per (user, bot)** for trust, resonance, affection, openness, mood label, plus internal mood axes and bookkeeping (bias, previous turn’s triggers for decay rules). This is what people usually mean by “how we’re doing with *this* bot.”
- **Messages** — ordered turns (user/assistant); **not** the same object as relationship state, but both are read when building a reply.

**Boundary:** Clients may send **small optional deltas** for trust/resonance on a chat turn; the server still applies its own **trigger-based** updates afterward. The **backend remains the source of truth** for how those combine and clamp.

## 5. Update Model

**Summary (high level):** Each chat turn is a loop—**read current state → optionally apply explicit adjustments → build and run generation → fold the completed exchange back into stored state**—so the next turn sees an updated baseline.

**Summary (mechanism):** Updates are **heuristic** and **owned by application code**. Nothing here is learned from gradients. A **separate LLM call** may assign **trigger ids** to a turn; those ids map through a **fixed table** to numeric deltas and optional mood override/nudge—not free-form “reasoning” into state.

### 5.1 When things run (chat turn, conceptual order)

1. **Optional client deltas** — If the client sends trust/resonance adjustments with the message, the server applies them first (and, on that path, keeps affection/openness **in sync** with those deltas in the current implementation).
2. **User message persisted** — Transcript used for context and for later classification.
3. **Pre-reply relationship pass** — Applies **time-based drift** on internal mood axes and persists updated axes; **mood label** stays unless this pass included trigger-driven nudges (usually none here before the classifier runs).
4. **Prompt build** — Uses **current** trust/resonance/affection/openness/mood plus bot persona, interests, initiative-derived instructions, vocative lines, etc.
5. **Assistant reply generated** — Model produces text; light **post-processing** may adjust shape (e.g. initiative-related closing-question rules).
6. **Post-reply trigger pass** — User + assistant text are sent to a **classifier** that returns a small list of **trigger ids** (e.g. gratitude, apology, harsh rebuke). Effects are **aggregated** (caps per turn, dampening if mood is Irritated, skipping some repeats from the prior turn). Resulting deltas update the four stats; **mood override** or **mood nudge** may change the **mood label** subject to **inertia** (minimum time between label changes).

Disabled or failed classifier → **no triggers** for that turn; stats may still have changed earlier from client deltas or the pre-reply pass.

**Minigame (Gomoku):** discrete client-reported events can update trust/resonance/affection/openness/mood through a **fixed server-side table**—either **POST /games/gomoku/relationship-events** (no LLM, no new messages) or **`ephemeral_game.relationship_events`** on **POST /chat/send-bot-message**. Game-driven mood updates may use a **forced** path that skips the usual minimum time between mood-label changes.

### 5.2 Trigger-shaped updates (illustrative, not exhaustive)

Internally, ids such as **gratitude**, **apology**, **vulnerability**, **playful banter**, **compliment to bot**, **mild friction / harsh rebuke / dismissive short**, **seeks support**, **shares joy / distress**, **comforting assistant tone**, **bonding smalltalk**, **cold or hostile exchange**, **reconciliation**, etc., map to **bounded** changes in trust/resonance/affection/openness and sometimes **mood**. This is the main **automatic** way the four stats and mood move after a full exchange.

### 5.3 Time and reads

Between chat turns, **elapsed real time** nudges internal mood axes toward **per-bot baselines** when relationship state is refreshed (e.g. opening the UI). The **visible mood label** does not continuously slide with those axes; it is **sticky** unless triggers move it.

### 5.4 Bot configuration

**Interests** and **base initiative** change when the user **edits the bot**, not when the classifier runs. They affect prompts and initiative math on every turn.

## 6. How State Affects Responses

- State does **not** “write the reply” directly. It **conditions** the **system prompt** (numeric lines + mood playbook + persona/interest blocks) and the **initiative** add-on; the LLM still generates surface text.
- **Trust / resonance / affection / openness** — steer guardedness, warmth, care, and self-disclosure **as instructed in prose** to the model.
- **Mood** — switches **macro tone** (brief vs. expansive, playful vs. withdrawn, irritated vs. calm) via playbook text; **Irritated** also alters how strongly positive trigger deltas apply.
- **Interests** — bias topical examples and dynamic nudges; help decide if the user’s turn “matches” the bot’s themes for initiative.
- **Initiative** — changes **how much** the bot is asked to steer, extend, or hold back, including optional **post-processing** on the draft reply.

If prompts and models drift, **the same numbers** can produce **different** surface behavior—that’s expected.

## 7. Example State Transitions

**Example 1 — Warm, repeated rapport**  
User thanks the bot and jokes along; triggers may bump **trust**, **resonance**, **affection**; **mood** may nudge toward **Happy** or **Playful**. Prompts ask for a slightly warmer, more aligned voice; **initiative** may stay moderate unless the user goes very short or passive.

**Example 2 — Harsh or dismissive turn**  
Strong negative triggers can drop **trust** and **resonance**, pull **affection**/**openness** down, and set **mood** toward **Irritated**. Playbook text asks for shorter, drier replies; positive trigger bumps later in the same mood are **dampened**.

**Example 3 — Vulnerability or support-seeking**  
Triggers tied to sharing difficulty or seeking support tend to raise **trust**/**resonance**/**affection** and **openness**, and may bias **mood** toward **Quiet** or **Calm** depending on ids. The model is instructed to respond with care **only when** mood and trust still make that appropriate.

**Example 4 — Time away**  
User returns after hours or days: internal axes **relax** toward baseline before the next message is processed; the **mood label** may remain unchanged until a new trigger moves it—so the character can feel “cooled off” without rewriting history manually.

## 8. Current Limitations

- All deltas and triggers are **hand-authored** and **still tunable**; behavior will change as rules change.
- Numbers are **not** psychometric measures; don’t interpret them as ground truth about people.
- **Classifier** quality and LLM **compliance** vary by provider/model; the same state may read differently on different stacks.
- **Message history** is linear transcript only—no retrieval over long semantic memory.
- Some effects are **indirect** (prompt phrasing + light post-process), so failures are **soft** (the model can ignore instructions).
- **Debug** fields (e.g. initiative snapshots) exist for development; they are **not** a stable external contract.

## 9. Future Evolution

Possible directions (not commitments):

- Calibrate trigger sets and caps with clearer evaluation or A/B hooks.
- Richer **decay** or **cooldown** rules between moods and stats.
- Stronger **evaluation** around tone continuity and safety boundaries.
- Optional **retrieval-backed** memory for facts/topics beyond raw transcript window.
- Better **transparency** tooling (explain “why mood moved” from trigger ids for authors and power users).
