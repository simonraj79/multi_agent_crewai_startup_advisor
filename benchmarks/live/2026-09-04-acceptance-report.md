# Provisional Validation Report: AI Differentiated Worksheet Generator

**Summary:** Provisional recommendation: **REJECT** (Composite Score: 3.7 / 10). The decision is governed by the fatal floor `FLOOR_ALREADY_FREE` because open-source and existing tools provide core functionality at no cost.

## Scope
- **Startup Idea:** A tool that turns a teacher's lesson plan into a set of differentiated practice worksheets, one per reading level, with an answer key.
- **Category:** K-12 EdTech / Teacher Productivity Software
- **Target User:** K-12 classroom teachers managing mixed-ability student cohorts
- **Problem:** Manually tailoring lesson content into tiered practice assignments across multiple reading levels consumes hours of weekly preparation time.
- **Technology Claim:** Automated multi-level text simplification and question generation reliably producing calibrated reading level tiers with accurate answer keys from unstructured lesson inputs.
- **As of:** 2026-09-04

## Rubric Evaluation
- **Demand (D): 2 / 3** (Evidence Thin)
  - Anchor: 1 or 2 problem threads, or at least 3 problem threads none of which is dated within 24 months.
  - Evidence: Former teachers express struggle with differentiation across 30 different sets of student needs ([https://news.ycombinator.com/item?id=48981136](https://news.ycombinator.com/item?id=48981136)) and teachers spend too much time manually preparing diagrams and lesson materials ([https://news.ycombinator.com/item?id=46097211](https://news.ycombinator.com/item?id=46097211)). Modular prompts and worksheet generators for unique student outputs are noted ([https://news.ycombinator.com/item?id=41289451](https://news.ycombinator.com/item?id=41289451)).
- **Market (M): 2 / 3**
  - Anchor: At least 1 market source names a buyer segment for this problem.
  - Evidence: Platforms target educators and districts with lesson planning and differentiated classroom materials, including MagicSchool ([https://www.magicschool.ai/tools/lesson-plan](https://www.magicschool.ai/tools/lesson-plan)), Eduaide ([https://www.eduaide.ai/](https://www.eduaide.ai/)), and district professional learning bodies like NCCE ([https://ncce.org/five-new-ai-lesson-plan-generators/](https://ncce.org/five-new-ai-lesson-plan-generators/)).
- **Competitive Room (C): 2 / 3** (Evidence Thin)
  - Anchor: No source states an axis of beatability, and either no competitor is named or at least 1 named competitor is not shown to be vendor owned.
  - Evidence: Named alternatives include MagicSchool ([https://www.magicschool.ai/tools/lesson-plan](https://www.magicschool.ai/tools/lesson-plan)) and Eduaide ([https://www.eduaide.ai/](https://www.eduaide.ai/)), neither showing published pricing or vendor ownership details.
- **Feasibility (F): 3 / 3** (Evidence Thin)
  - Anchor: At least 1 repository in the feasibility evidence is reusable: marked SOLVES_ENTIRELY or PARTIAL, licensed for commercial use, and pushed within 12 months.
  - Evidence: The repository `ellmos-ai/worksheet-generator` ([https://github.com/ellmos-ai/worksheet-generator](https://github.com/ellmos-ai/worksheet-generator)) permits commercial use, was pushed within 0 months, and is marked as solving the job entirely. Irrelevant alternatives include `SVstudent/LLM-Math` ([https://github.com/SVstudent/LLM-Math](https://github.com/SVstudent/LLM-Math)), `ali-hassan2509/ai-paper-generator` ([https://github.com/ali-hassan2509/ai-paper-generator](https://github.com/ali-hassan2509/ai-paper-generator)), `Caravaca-Labs/puzzletide-cli` ([https://github.com/Caravaca-Labs/puzzletide-cli](https://github.com/Caravaca-Labs/puzzletide-cli)), and `JovannyEspinal/chiron` ([https://github.com/JovannyEspinal/chiron](https://github.com/JovannyEspinal/chiron)).
- **Headroom Over Free (X): 0 / 3** (Evidence Thin)
  - Anchor: At least 1 free substitute repository is not marked archived, permits commercial use and was pushed within 12 months, or at least 1 free product with an attributed URL covers the whole core job.
  - Evidence: `ellmos-ai/worksheet-generator` ([https://github.com/ellmos-ai/worksheet-generator](https://github.com/ellmos-ai/worksheet-generator)) acts as a live, free, commercially licensed substitute.

## Verdict and Confidence
- **Verdict:** REJECT
- **Decision Reason:** FLOOR_ALREADY_FREE
- **Composite Score:** 3.7
- **Confidence:** 0.35 (MODERATE)
- **Provisional:** true

## Evidence Gaps
- No direct evidence of users paying out-of-pocket or maintaining a specific workaround for multi-level reading tier generation from lesson plans.
- Scoping gap: Unclear whether the tool targets individual teacher purchases or district-level curriculum licensing with compliance requirements.
- Scoping gap: Undefined subject scope: readability differentiation functions differently for reading comprehension versus quantitative STEM curricula.

## Risks
- **Fatal Floor:** The verdict is constrained by `FLOOR_ALREADY_FREE` because of the active, commercially licensed free substitute `ellmos-ai/worksheet-generator` ([https://github.com/ellmos-ai/worksheet-generator](https://github.com/ellmos-ai/worksheet-generator)).
- **Thin Evidence Dimensions:** Demand (D), Competitive Room (C), Feasibility (F), and Headroom Over Free (X) all rely on thin evidence bases.
- **Missing Willingness to Pay:** No sentiment data shows teachers paying out-of-pocket or employing sustained workarounds for reading tier generation.
- **Incumbent Coverage:** Existing products such as MagicSchool ([https://www.magicschool.ai/tools/lesson-plan](https://www.magicschool.ai/tools/lesson-plan)) and Eduaide ([https://www.eduaide.ai/](https://www.eduaide.ai/)) already offer generative lesson plans and differentiated resources to K-12 educators.
- **Non-Commercial Licences:** Multiple technical repositories covering adjacent education paper/math generators forbid commercial use, including `SVstudent/LLM-Math` ([https://github.com/SVstudent/LLM-Math](https://github.com/SVstudent/LLM-Math)), `ali-hassan2509/ai-paper-generator` ([https://github.com/ali-hassan2509/ai-paper-generator](https://github.com/ali-hassan2509/ai-paper-generator)), and `JovannyEspinal/chiron` ([https://github.com/JovannyEspinal/chiron](https://github.com/JovannyEspinal/chiron)).

## Kill Criteria
- More than 80% of interviewed teachers report using MagicSchool or ChatGPT's free tiers for worksheet differentiation and refuse to allocate any personal budget for a dedicated tool.
- Evaluation of automated readability calibration shows that LLM text simplification alters core curriculum concepts or introduces factual errors into answer keys in more than 15% of generated outputs.

## Cheapest Next Test
- Run a targeted cold email or social campaign offering 10 middle-school English teachers a free pack of 3-tiered differentiated reading worksheets with answer keys in exchange for a 15-minute interview on whether they would pay out of pocket vs use existing free AI tools like MagicSchool or open-source templates.

## Sources
- [https://www.magicschool.ai/tools/lesson-plan](https://www.magicschool.ai/tools/lesson-plan)
- [https://www.eduaide.ai/](https://www.eduaide.ai/)
- [https://ncce.org/five-new-ai-lesson-plan-generators/](https://ncce.org/five-new-ai-lesson-plan-generators/)
- [https://news.ycombinator.com/item?id=48981136](https://news.ycombinator.com/item?id=48981136)
- [https://news.ycombinator.com/item?id=41289451](https://news.ycombinator.com/item?id=41289451)
- [https://news.ycombinator.com/item?id=46097211](https://news.ycombinator.com/item?id=46097211)
- [https://github.com/SVstudent/LLM-Math](https://github.com/SVstudent/LLM-Math)
- [https://github.com/ellmos-ai/worksheet-generator](https://github.com/ellmos-ai/worksheet-generator)
- [https://github.com/ali-hassan2509/ai-paper-generator](https://github.com/ali-hassan2509/ai-paper-generator)
- [https://github.com/Caravaca-Labs/puzzletide-cli](https://github.com/Caravaca-Labs/puzzletide-cli)
- [https://github.com/JovannyEspinal/chiron](https://github.com/JovannyEspinal/chiron)