def render_markdown(result):
    lines = []

    lines.append(f"# {result.title}")
    lines.append("")
    lines.append("## 一、诊断结论")
    lines.append("")

    if result.conclusions:
        for item in result.conclusions:
            lines.append(f"- {item}")
    else:
        lines.append(f"- {result.summary}")

    lines.append("")
    lines.append("## 二、异常发现")
    lines.append("")

    if result.abnormal_findings:
        for index, finding in enumerate(result.abnormal_findings, start=1):
            value = f"：{finding.value}" if finding.value else ""
            lines.append(f"{index}. 【{finding.severity}】{finding.name}{value}")
            if finding.description:
                lines.append(f"   - 说明：{finding.description}")
            if finding.reason:
                lines.append(f"   - 原因：{finding.reason}")
    else:
        lines.append("- 未发现明显异常。")

    lines.append("")
    lines.append("## 三、原因分析")
    lines.append("")

    if result.root_causes:
        for index, cause in enumerate(result.root_causes, start=1):
            lines.append(f"{index}. {cause}")
    else:
        lines.append("- 暂无明确根因，需要结合业务时间段和 SQL 明细继续分析。")

    lines.append("")
    if getattr(result, "root_cause_flows", None):
        lines.append("## 四、问题传播链")
        lines.append("")
        for flow in result.root_cause_flows:
            path_parts = [f"**{flow.root}**"] + flow.amplifiers
            if flow.symptoms:
                path_parts.append(f"**{flow.symptoms[-1]}**")
            path = " --> ".join(path_parts)
            lines.append(f"- {flow.title}：{path}")
            if flow.explanation:
                lines.append(f"  - {flow.explanation}")
            for item in flow.evidence:
                lines.append(f"  - {item.name}：{item.value}")
        lines.append("")

    lines.append("## 五、证据")
    lines.append("")

    if result.evidence:
        for group_name, items in result.evidence.items():
            lines.append(f"### {group_name}")
            for item in items:
                desc = f"。{item.description}" if item.description else ""
                lines.append(f"- {item.name}：{item.value}{desc}")
            lines.append("")
    else:
        lines.append("- 当前解析结果中没有足够证据。")
        lines.append("")

    lines.append("## 六、处理建议")
    lines.append("")

    if result.recommendations:
        for rec in result.recommendations:
            lines.append(f"- {rec.priority}：{rec.action}")
            if rec.reason:
                lines.append(f"  - 原因：{rec.reason}")
    else:
        lines.append("- 暂无处理建议。")

    # LLM Deep Analysis
    llm_da = getattr(result, "llm_deep_analysis", None)
    if llm_da and not llm_da.get("error"):
        lines.append("")
        lines.append("## 七、AI 深度分析")
        lines.append("")

        if llm_da.get("root_cause_analysis"):
            lines.append("### 根因分析")
            lines.append(llm_da["root_cause_analysis"])
            lines.append("")

        if llm_da.get("problem_propagation_chain"):
            lines.append("### 问题传播链")
            for i, chain in enumerate(llm_da["problem_propagation_chain"], 1):
                cause = chain.get("cause", "")
                effect = chain.get("effect", "")
                evidence = chain.get("evidence", "")
                lines.append(f"{i}. {cause} → {effect}")
                if evidence:
                    lines.append(f"   - 证据：{evidence}")
            lines.append("")

        if llm_da.get("sql_recommendations"):
            lines.append("### SQL 深度优化建议")
            for rec in llm_da["sql_recommendations"]:
                sql_id = rec.get("sql_id", "")
                issue = rec.get("issue", "")
                recommendation = rec.get("recommendation", "")
                hint = rec.get("execution_plan_hint", "")
                impact = rec.get("estimated_impact", "")
                lines.append(f"- **{sql_id}** [{impact}]：{issue}")
                lines.append(f"  - 建议：{recommendation}")
                if hint:
                    lines.append(f"  - 执行计划建议：{hint}")
            lines.append("")

        if llm_da.get("parameter_suggestions"):
            lines.append("### 参数调整建议")
            for param in llm_da["parameter_suggestions"]:
                name = param.get("parameter", "")
                current = param.get("current_value", "")
                recommended = param.get("recommended_value", "")
                reason = param.get("reason", "")
                lines.append(f"- **{name}**：当前 {current} → 建议 {recommended}")
                if reason:
                    lines.append(f"  - 原因：{reason}")
            lines.append("")

    return "\n".join(lines)
