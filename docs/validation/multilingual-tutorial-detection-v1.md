# Multilingual tutorial detection v1

Date: 2026-10-02

## Trigger

The real repository `AidenBJ/java-multi-agent-lab` reached deep analysis even
though its public description explicitly presents it as a learning/tutorial
project in Chinese.

The existing tutorial filter was effectively English-oriented.

## Constraint

The canonical conservative rule is preserved:

> A semantic tutorial rejection requires at least two independent weak signals.

A single phrase, language, repository age, low stars, or substantial educational
codebase is not enough to reject a repository.

## Change

Extended explicit tutorial/educational phrase recognition for:

- Chinese
- Spanish
- Catalan

The implementation deliberately avoids ambiguous bare learning terms:

- Chinese bare `学习`
- Spanish bare `aprendizaje`
- Catalan bare `aprenentatge`

Those terms can occur in machine-learning or other legitimate technical
contexts.

Only explicit educational/tutorial phrases are added, such as:

- Chinese: `渐进式教程`, `循序渐进的教程`, `入门教程`, `教学项目`,
  `学习工程`, `学习项目`
- Spanish: `paso a paso`, `para principiantes`, `proyecto educativo`,
  `proyecto de aprendizaje`
- Catalan: `pas a pas`, `per a principiants`, `projecte educatiu`,
  `projecte d'aprenentatge`

The existing two-signal policy remains unchanged.

## Test matrix

Positive controls use a substantial repository tree rather than a tiny tutorial:

- 8 source modules
- 2 test files
- README

For Chinese, Spanish and Catalan:
- description contains explicit tutorial/educational wording
- README independently contains explicit tutorial/educational wording
- expected: `REJECT_TUTORIAL`
- expected evidence:
  - `description:tutorial_wording`
  - `readme:tutorial_wording`
- `tree:minimal_implementation` must not contribute

Negative controls:
- one multilingual tutorial surface only -> PASS
- Chinese production machine-learning wording -> not tutorial
- Spanish `aprendizaje automático` -> not tutorial
- Catalan `aprenentatge automàtic` -> not tutorial

## Real repository characterization

Repository:
`AidenBJ/java-multi-agent-lab`

GitHub repo id:
`1379423359`

Current observed tree:
- tree paths: 585
- source paths: 187
- minimal implementation: false
- topics: none

With this branch:
- tutorial signals:
  - `description:tutorial_wording`
  - `readme:tutorial_wording`
- decision: `REJECT_TUTORIAL`

Therefore the rejection is caused by two independent text surfaces, not by
repository size or implementation depth.

## Validation

Focused hard-filter contract:
- 25/25 PASS

All filtering tests:
- 25/25 PASS

Full suite:
- branch: 483 PASS / 2 skipped
- frozen base: 476 PASS / 2 skipped
- delta: +7 PASS / 0 new failures

Additional:
- `CONFIG_VALID`
- `git diff --check`: clean

## Scope

This branch changes only tutorial semantic detection and its tests/documentation.

It does not change:
- DeepSeek schema handling
- scoring
- notification thresholds
- live publishing
- GitHub acquisition
- production state

## Disposition

`READY_FOR_INTEGRATION_REVIEW`

Branch:
`fix/multilingual-tutorial-detection-v1`

No remote branch / no push at freeze time.
