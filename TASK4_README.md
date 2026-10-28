# Task 4: GPT-5 Mini Evaluation with the Default Harness

## Objective

Task 4 evaluates a more expensive model on the fixed 40-task evaluation subset while keeping the same default harness used by the baseline experiment.

## Configuration

- Model: `openrouter/openai/gpt-5-mini`
- Agent: `terminus-2`
- Harness: default
- Phase: `evaluation`
- Tasks: 40 fixed evaluation tasks
- Attempts per task: 1
- Concurrency: 1
- Trial retries: 0
- Custom context management: disabled
- Custom failure recovery: disabled

The experiment used the benchmark commit and runtime image recorded in `results/results_expensive/batch_summary.json`.

## Results

| Metric | Result |
| --- | ---: |
| Tasks attempted | 40/40 |
| Valid graded tasks | 35 |
| Execution errors or ungraded tasks | 5 |
| Non-zero graded outcomes | 7 |
| Full-reward outcomes | 2 |
| Graded-only mean reward | 0.1428566 |
| Known model cost | US$2.5692563 |
| Total recorded runtime | Approximately 8.29 hours |

The full 40-task mean is not reported because five tasks did not produce valid graded outcomes. The graded-only mean must therefore not be presented as the official mean across all 40 tasks.

## Execution Errors

- `025-product-channel-pivots`: `AgentTimeoutError`
- `062-add-baseball-audio`: Docker environment build/DNS failure
- `089-install-recommended-exts`: `AgentTimeoutError`
- `103-download-blog-pdfs`: `AgentTimeoutError`
- `118-set-times-new-roman`: Docker environment build/DNS failure

The two Docker build failures occurred before model inference and should be distinguished from model or agent failures.

## Non-Zero Outcomes

| Task | Reward |
| --- | ---: |
| `033-prostate-volume-est` | 0.66 |
| `054-prostate-label-obj` | 0.50 |
| `074-apa-references-review` | 0.8176733 |
| `084-plate-thermal-sim` | 0.33 |
| `092-fix-tetris-bug` | 1.00 |
| `106-create-charles-ssh-user` | 1.00 |
| `119-tabstop-sentence-split` | 0.6923077 |

## Result Files

- Batch summary: `results/results_expensive/batch_summary.json`
- Per-task records: `results/results_expensive/<task-id>/result.json`

The per-task JSON files contain execution evidence, usage information, timing, verifier results, and failure details. Large `result.json` files are stored through Git LFS according to the repository's `.gitattributes` configuration.

## Reproduction

Create a local `.env` file containing an authorized OpenRouter key:

```text
OPENROUTER_API_KEY=your_actual_key_here
```

Do not commit `.env`. Run the free preflight first:

```bash
python3 scripts/run_tasks.py --check-only \
  --batch-id task4-gpt5-mini-preflight
```

Start a new evaluation batch:

```bash
caffeinate -dimsu python3 scripts/run_tasks.py \
  --batch-id task4-gpt5-mini
```

If the batch stops for inspection, continue it with:

```bash
caffeinate -dimsu python3 scripts/run_tasks.py \
  --batch-id task4-gpt5-mini \
  --resume
```

Recorded attempts, including execution errors, are skipped during resume and are not retried automatically.

## Conclusion

GPT-5 Mini completed attempts for all 40 tasks but produced fewer valid graded outcomes and a lower graded-only mean reward than the existing Qwen3-Coder baseline. Its main weaknesses were long GUI/browser workflows, native Office-object manipulation, and inefficient loops that ended in agent timeouts. It performed better on deterministic command-line, coding, and structured-output tasks.
