# I built an AI that reads contracts like a lawyer — and knows when to say "I don't know"

> Draft for the Devpost "blog post" bonus — publish on Medium/dev.to/LinkedIn and paste the link
> into the submission. Every number below is real and measured. Vietnamese version:
> [`blog-qwen-cloud.vi.md`](blog-qwen-cloud.vi.md).

Picture a small Vietnamese furniture exporter. A German buyer sends over a 12-page contract in
English. Somewhere on page 7, there's a line: *"late delivery penalty: 15% of contract value."*

The owner signs it. Nobody told her that Vietnamese law caps that penalty at **8%** — anything
above is simply void in court. She just agreed to a term that isn't even legal, and she'll
negotiate her next three contracts without ever knowing she had that card in her hand.

That's the problem I built **Legal Guard** for, during the Qwen Cloud Hackathon (Autopilot Agent
track). It's an AI agent that reads your contract, tells you which clauses are merely *bad for
you* and which are *actually illegal*, and helps you push back — while a human approves every
message before it goes out.

Try it: https://legalguard.duckdns.org · Code (open source): https://github.com/trungnguyen1618033/legal-guard-PH

Here's what I learned, in plain language.

## Lesson 1: Don't send a senior partner to do a photocopy job

AI models are like staff at a law firm. The senior partner (`qwen3.7-max`) is brilliant and slow.
The paralegal (`qwen-flash`) is fast and great at simple, well-defined checks.

My first version sent *everything* to the senior partner. Analyzing one contract took minutes,
and most of that time was spent on questions as simple as: *"Does this law article actually say
what we claim it says — yes or no?"*

So I split the work the way a real firm would:

- **Hard reasoning** (analyzing the contract, planning negotiation strategy) → the big model.
- **Yes/no double-checks** → the fast model: **0.5 seconds instead of 23** — about 46× faster,
  with the same answers.
- **Quick legal Q&A** → the mid-size model: 4–6 seconds instead of ~48.

One phase of the pipeline dropped from **~4 minutes to ~7 seconds**. Nothing got smarter —
the work just went to the right desk.

## Lesson 2: The most dangerous AI answer is the confident wrong one

Everyone worries about AI "hallucinating" — making things up. In legal work the failure is
sneakier: the AI cites a **real** law article that simply **doesn't say** what the AI claims.
The citation checks out; the meaning doesn't. A busy reader would never catch it.

Three guardrails fixed this:

1. **A second pair of eyes.** After the agent flags a risk, a separate AI checker gets one job:
   *"Read this law article. Does it actually support this claim — yes or no?"* If the answer is
   fuzzy, we treat it as **no**. In law, wrongly shouting "this clause is illegal!" is worse
   than quietly asking a human to review.
2. **No zombie laws.** Laws get replaced constantly. Legal Guard only cites law that is
   **currently in force** — and if you ask "what was the rule in 2020?", it answers with the law
   as it stood *in 2020*.
3. **Knowing when to say "I don't know."** Ask something outside its knowledge base and it says
   *"I don't have enough legal basis to answer"* — like a good lawyer saying "let me check"
   instead of guessing. We treat a correct refusal as a correct answer in our tests.

We test all of this against 54 questions with lawyer-known answers, across 12 areas of
Vietnamese law. Current score: **54/54** on majority-vote (3 runs per case) — up from 87% when we
started. One borderline case still flickers between runs (a wording match on the hosted model), so a
single run may read 53/54 — we disclose that rather than round up to a flat 100%. The whole
methodology is published at https://legalguard.duckdns.org/trust — because an AI that touches legal
risk should show its report card.

## Lesson 3: If a cheap model guards the door, test the guard

Remember the fast "paralegal" model doing the yes/no checks? Once it gates which citations
survive, it becomes the safety-critical part. So it gets its own exam: 16 tricky
statements paired with real statute text — including traps like *"a 10% penalty is valid under
this article"* shown next to the article that says 8%. We score the fast model against both the
correct answers and the big model's answers. Result: **16/16 correct, 100% agreement with the
flagship, at a fraction of the latency** (`evaluation/nli_report.json`). That test is what let us
make the faster trade with a clear conscience.

## Lesson 4: "Autopilot" means it works while you sleep

The track is called *Autopilot Agent* — and I took that literally. On the production server
(one small Alibaba Cloud machine running everything in Docker), a scheduler wakes the agent at
**5 AM every day**. It checks which laws became effective, then cross-references **every contract
it has ever reviewed**: did a new decree just change an article your contract relies on?

It's precise, too: a decree amending Article 9 alerts only the contracts citing Article 9 —
no spam. And if you dismiss a false alarm once, it stays dismissed. During testing this fired
on real data: one decree about arbitration flagged 8 stored contracts with foreign-arbitration
clauses. Nobody asked it to. That's the point.

## What failed (worth as much as what worked)

- A fancy tree-search retrieval method lost to the boring hybrid approach on our tests. Boring won.
- A graph-based reranking idea made zero measurable difference. It's in the code, switched off.
- Hand-tuning thresholds to fix each failing test broke a different test every time —
  whack-a-mole. A structural fix (an automatic cutoff, nothing hand-tuned) is what finally held.

## The one-line summary

Spend your speed budget on reasoning, your safety budget on verification, and publish the number
you actually measured — not the one that looks good.

*Built with Qwen models on Qwen Cloud (DashScope), deployed on Alibaba Cloud ECS. Open-source
(MIT), 365 automated tests. Hackathon submission tag: `v1.0-qwen`.*
