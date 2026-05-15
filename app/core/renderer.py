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

    return "\n".join(lines)
