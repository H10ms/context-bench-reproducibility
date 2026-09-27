# THREATS TO VALIDITY — GPT-6 Sol vs GPT-6 Luna (schema v2)

1. **Training-data contamination.** SWE-bench tasks are public; both models may
   have seen issues and fixes. Absolute rates are upper bounds; paired deltas
   remain interpretable but contamination cannot be excluded.
2. **Different internal tool/reasoning strategies.** Same harness flags do not
   force identical internal planning, tool choice, or stopping behavior.
3. **OpenCode abstraction leakage.** One CLI does not guarantee identical
   backend behavior (routing, retries, server versions per model ID).
4. **Post-experiment updates.** OpenCode, providers, or models may change after
   the campaign; freeze records versions, but reruns months later may differ.
5. **Only 30 tasks.** Limited power; repository slices (5 tasks) are exploratory.
6. **Python open-source only.** Results do not generalize to all development
   (other languages, proprietary code, greenfield work).
7. **Stochasticity.** Single runs are noisy; we report stability over replicates.
8. **Two replicates limit variance estimates.** 1/2 vs 2/2 is a coarse signal.
9. **Public price ≠ OpenCode economics.** Normalized API-equivalent cost can
   differ from actual subscription/credit cost; both are reported separately.
10. **Token accounting differs.** Input/output/reasoning/cached counting varies
    by model/provider; cross-model token comparisons are approximate.
11. **Evaluator scope.** SWE-bench checks functional correctness via tests, not
    production quality (readability, maintainability, security).
12. **Timeout effects.** A fixed identical timeout can disadvantage a slower but
    more thorough model; timeouts are reported, not hidden.
13. **Benchmark contamination (see 1).** Cannot be fully excluded; mitigated by
    paired design and pre-registered task set.
14. **Unknown comparable API pricing.** The observed OpenCode value
    `actual_cost_usd=0` is not an API price. With
    `normalized_api_cost_usd=null`, API cost and price/performance conclusions
    cannot be drawn unless a defensible pricing snapshot is added.
15. **Prior infrastructure observations.** GPT-5.6 Sol/GPT-6 Astra
    infrastructure-validation performance observations could bias expectations.
    They are historical and excluded from the active Sol/Luna dataset and
    analysis.
