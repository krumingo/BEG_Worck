from pathlib import Path

path = Path("docs/architecture/IMPLEMENTATION_WAVES.md")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "> Business-close pass 21.07.2026: FLOW-010, FLOW-025 и FLOW-040 са 100%; counterparty communication/bank rules, document control и audit retention/visibility rules са заключени.",
        "> Business-close pass 22.07.2026: FLOW-010, FLOW-025, FLOW-036 и FLOW-040 са 100%; counterparty, document-control, Object Timeline и audit rules са заключени.",
    ),
    (
        "- FLOW-036 Object Timeline — after 3 business decisions;",
        "- FLOW-036 Object Timeline — business locked; runtime after W0 foundations and stable W1/W2 source domains;",
    ),
    (
        "- FLOW-048 Resource Recommendation — after 6 business decisions.\n\n## Rules",
        """- FLOW-048 Resource Recommendation — after 6 business decisions.\n\n## Object Timeline runtime / FLOW-036\n\nWave 3 изгражда read-only Timeline projection върху стабилните source domains:\n\n- canonical `TimelineEvent` projection и source adapters;\n- project/subproject `Временно спрян` срещу WorkPackage/СМР `Блокирано`;\n- `PauseImpactAssessment` snapshot, pause/resume и remobilization effect;\n- operational, client and financial permission layers;\n- delay overlap и causal-chain logic;\n- daily, weekly, immediate and full-period versioned AI summaries със source links;\n- drill-down към оригиналния договор, отчет, доставка, акт, фактура, плащане, дефект, Approval или AuditEvent.\n\nTimeline не записва втори business fact и не извършва write-through към source domain.\n\n## Rules""",
    ),
    (
        "- denied actions и permission failures са видими без разкриване на забранени данни.",
        """- denied actions и permission failures са видими без разкриване на забранени данни;\n- Timeline summaries не измислят причина, сума, вина или approval;\n- `Общо` показва важните събития и summaries, а raw events се разгъват;\n- financial Timeline events сочат към FLOW-006 и никога не дублират Payment/Invoice/Act;\n- pause/resume и blocked-work events са permission-filtered и auditable.""",
    ),
    (
        "- FLOW-010 Master IDs, role/scope, communication threads, VerifiedBankAccount и financial-read contracts могат да се проектират след agreement за W0 IDs, permissions, Approval, File Registry и AuditEvent;",
        """- FLOW-010 Master IDs, role/scope, communication threads, VerifiedBankAccount и financial-read contracts могат да се проектират след agreement за W0 IDs, permissions, Approval, File Registry и AuditEvent;\n- FLOW-036 TimelineEvent/source-adapter contracts могат да се проектират паралелно, но финалната projection изчаква стабилните W1/W2 source schemas;""",
    ),
    (
        "- FLOW-010 bank/payment guards before Payment Core, Approval, AuditEvent and Master Organization contracts;",
        """- FLOW-010 bank/payment guards before Payment Core, Approval, AuditEvent and Master Organization contracts;\n- FLOW-036 final Timeline projection before canonical project/subproject pause states, source links, permissions and domain event contracts;""",
    ),
    (
        "15. Generic WorkPackage + PackageTemplate schema contract.\n16. Backup/version manifest, AuditEvent immutable copy and restore dry-run.",
        """15. Generic WorkPackage + PackageTemplate schema contract.\n16. TimelineEvent projection + PauseImpactAssessment + source-adapter contract.\n17. Backup/version manifest, AuditEvent immutable copy and restore dry-run.""",
    ),
    (
        "- FLOW-025 business-close pass, 21.07.2026.\n- FLOW-040 business-close pass, 21.07.2026.",
        """- FLOW-025 business-close pass, 21.07.2026.\n- FLOW-036 business-close pass, 22.07.2026.\n- FLOW-040 business-close pass, 21.07.2026.""",
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"Expected pattern not found: {old[:120]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Patched", path)
