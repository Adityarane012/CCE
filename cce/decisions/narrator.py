from cce.contracts.decision import Explanation, NarratedExplanation


def render_narrative(expl: Explanation) -> str:
    """Deterministically render an Explanation into prose."""
    parts = []
    
    parts.append(f"Trigger: {expl.trigger}")
    
    if expl.risk_change:
        rc = expl.risk_change
        parts.append(f"Risk shift detected: {rc.metric} moved from {rc.value_from:.3f} to {rc.value_to:.3f}.")
        
    if expl.main_contributors:
        contribs = ", ".join(f"{c.scope} ({c.value_from:.3f} -> {c.value_to:.3f})" for c in expl.main_contributors)
        parts.append(f"Main contributors: {contribs}.")
        
    if expl.optimizer:
        parts.append(f"Optimizer attempted a {expl.optimizer.name} strategy.")
        
    if expl.candidate_summary:
        summ = ", ".join(f"{k}: {v:.1%}" for k, v in expl.candidate_summary.items())
        parts.append(f"Proposed allocations: {summ}.")
        
    parts.append(f"Control result: {expl.control_result}.")
    
    if expl.reasons:
        parts.append("Reasons:")
        for r in expl.reasons:
            parts.append(f"- {r}")
            
    if expl.stress_summary:
        parts.append("Stress Summary:")
        for s in expl.stress_summary:
            parts.append(f"- {s}")
            
    parts.append(f"Action taken: {expl.action}")
    
    if expl.expected_improvement:
        parts.append(f"Expected improvement: {expl.expected_improvement}")
        
    return "\n".join(parts)


def build_narrated_explanation(expl: Explanation) -> NarratedExplanation:
    template_text = render_narrative(expl)
    return NarratedExplanation(
        structured=expl,
        template_text=template_text
    )
