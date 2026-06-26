# From Vibes to Evals: A Practical Plan for Your RAG Chatbot

## The Problem

Right now, testing your chatbot probably looks like this: someone asks it a few
questions, eyeballs the answers, and says "yeah, that looks about right." This
works early on, but it doesn't scale. You can't tell if a change to your
retrieval pipeline, prompt, or model made things better or worse. You don't know
where failures are coming from — bad retrieval? bad generation? both? You need
numbers.

## The Eval Mindset

Before jumping into tooling, it helps to internalize one idea: **a RAG chatbot
has two jobs, and you should measure them separately.**

1. **Retrieval** — did the system find the right documents (or chunks) to answer
   the question?
2. **Generation** — given what was retrieved, did the LLM produce a correct,
   faithful answer?

When the chatbot gives a bad answer, the cause is almost always one of these two
stages. If you only measure end-to-end quality ("was the answer good?"), you
won't know which stage to fix. Good evals decompose the problem.

That said, you don't need to decompose everything on day one. Start by measuring
whether the chatbot gets answers right, then dig into why when it doesn't.

## The Two-Stage Approach

We recommend RAGAS, a framework purpose-built for evaluating RAG pipelines. It
supports both end-to-end answer grading and retrieval diagnostics — same tool,
same test set, just increasing the resolution of what you measure.

### Stage 1: Is the Chatbot Getting It Right?

**What you do.** Build a set of questions with known correct answers. Run them
through the chatbot. Use RAGAS to grade the responses against your ground truth.

**What you measure.**
- **Answer Correctness** — does the chatbot's response match the expected
  answer? RAGAS decomposes this into factual overlap and semantic similarity so
  you get more signal than a binary right/wrong.

**Why start here.** You're treating the chatbot as a black box — retrieval is
happening under the hood, but you don't need to instrument it yet. This keeps
the setup simple and gets you measurable results fast. The question you're
answering is straightforward: _how often does the chatbot get it right?_

**What you'll need.** A set of 30-50 representative questions paired with
reference answers. Cover your key use cases and include some hard edge cases —
questions that require synthesizing across multiple documents, questions with
nuanced answers, questions the chatbot has gotten wrong before.

### Stage 2: Where Is It Going Wrong?

**What you do.** Capture the retrieved contexts alongside the chatbot's answers
(most RAG frameworks make this straightforward) and add retrieval-aware metrics
to your evaluation.

**What you measure.**
- **Faithfulness** — does the answer stick to what was retrieved, or is the model
  hallucinating beyond the source material?
- **Context Precision** — are the retrieved chunks actually relevant, or is the
  model wading through noise to find the signal?
- **Context Recall** — did retrieval surface all the information needed to answer
  completely?

**Why this matters.** When Stage 1 shows you the chatbot is getting answers
wrong, Stage 2 tells you where to intervene. Low faithfulness means the LLM is
the problem — it has the right context but generates something else. Low context
recall means retrieval is the problem — the right documents never made it to the
model. These are different fixes and you don't want to guess which one to try.

## Why Two Stages Instead of One?

You could instrument everything at once, but the staged approach has practical
advantages:

- **Lower the barrier.** Stage 1 requires no changes to your chatbot — just
  questions, answers, and an API call. Your team gets hands-on with structured
  evaluation in an afternoon, not a week.
- **Focus on what matters first.** If the chatbot is getting 90% of answers
  right, maybe retrieval tuning isn't urgent. If it's getting 40% right, you
  know immediately there's a problem worth diagnosing.
- **Build the muscle.** Evaluation is a practice, not a one-time event. Starting
  simple lets the team build habits — tracking metrics across runs, spotting
  regressions, making data-driven decisions — before the problem gets complex.

## Getting Started (This Week)

1. **Curate your test set.** Collect 30-50 questions that represent real usage.
   Write a reference answer for each. Lean on your team's domain expertise —
   they know what good answers look like.
2. **Run Stage 1.** Point RAGAS at your chatbot, feed it the questions, and
   grade with answer correctness. Record the scores. This is your baseline.
3. **Read the failures.** Look at the lowest-scoring questions. Are they hard
   retrieval problems? Ambiguous questions? Model limitations? This tells you
   whether Stage 2 is worth setting up now or later.
4. **Make it a habit.** Re-run evals before and after every significant change.
   A score that goes down is a conversation worth having before the change ships.
