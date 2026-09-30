# DeepSeek schema conformance v1

Date: 2026-09-30

## Trigger

Dry-run:

- GitHub Actions run: `36770528769`
- main SHA: `8291da1dd10fef1cdb721fbbfb17118e411fcfa4`
- result: `PARTIAL_SUCCESS`
- discovered: 533
- reported: 5
- LLM calls: 26
- LLM failures: 1

The truncation fix worked: the run contained no `finish_reason=length` and no
`TRUNCATION`.

The remaining failure was:

- repo id: `1379423359`
- repository: `AidenBJ/java-multi-agent-lab`
- validator path: `evidence/observed/0`
- schema rule: `maxLength`
- canonical limit: 300 characters
- provider finish reason: `stop` on PRIMARY and RETRY

So this was not truncation. It was a complete JSON object containing an
over-length evidence string.

## Root cause

`LLMValidationError` previously flattened JSON Schema failures into one
human-readable string.

The provider then reused up to 400 characters of that string as retry feedback.
For long values, the diagnostic was dominated by the rejected repository text
instead of a compact statement of the violated constraint.

The retry therefore did not receive a stable machine-readable signal such as:

`path=evidence/observed/0; rule=maxLength; limit=300`

## Change

The canonical schema is unchanged.

The validator now preserves structured metadata on schema failures:

- path
- validator/rule
- validator value

DeepSeek retry feedback uses that metadata when available and does not echo the
rejected over-length value.

Example retry diagnostic:

`schema violation at evidence/observed/0; path=evidence/observed/0; rule=maxLength; limit=300.`

No evidence is silently truncated or repaired.

## Regression coverage

Two new tests:

1. reproduce an over-length `evidence.observed[0]` patterned after the failing
   Maven-module observation and assert the structured `maxLength=300` metadata;
2. simulate PRIMARY invalid output followed by a valid RETRY and assert that
   the retry request receives `path/rule/limit` without echoing the rejected
   long repository value.

Existing retry tests for unexpected properties and oversized risks remain green.

## Validation

- LLM tests: **34 passed**
- full suite: **472 passed / 2 skipped**
- baseline main: **470 passed / 2 skipped**
- delta: **+2 passed / 0 new failures**
- `CONFIG_VALID`
- `git diff --check`: clean

## Separate characterization: tutorial filter

The same repository is publicly described as a learning/tutorial project and
contains a large staged curriculum. Current hard-filter tutorial signals are
English-oriented and require two independent weak signals.

Observed characterization:

- tree paths: 585
- source paths: 187
- topics: none
- `tutorial_signals()`: empty
- semantic tutorial rejection: none

Because the repository is substantial, it does not trigger the
`tree:minimal_implementation` signal either.

This is a distinct multilingual/semantic filtering gap. It is intentionally
**not fixed in this branch** to keep the schema-conformance change isolated.

## Disposition

Local branch:

`fix/deepseek-schema-conformance-v1`

Production/main is not modified by this work.

Recommended next step after review:

1. integrate this schema-conformance fix;
2. run a fresh dry-run;
3. confirm that repo `1379423359` either succeeds after retry or fails for a
   genuinely different bounded reason;
4. handle multilingual tutorial detection as a separate task.
