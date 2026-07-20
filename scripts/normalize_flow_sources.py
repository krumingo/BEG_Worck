from __future__ import annotations

from pathlib import Path
import re

FLOW_DIR = Path("docs/flows")
EXACT_HEADING = "## Източници / сесии"
OLD_HEADING = "## Източници и проследимост"


def source_block(flow_no: int) -> str:
    if flow_no <= 43:
        extra = []
        if flow_no == 3:
            extra.append("- Изрично Business Lock потвърждение: сесиите от 16.07.2026.")
        if flow_no == 5:
            extra.append("- Изрично Business Lock потвърждение: сесиите от 16.07.2026.")
        if flow_no == 25:
            extra.append("- Корекционен проход 20.07.2026: FLOW-025 остава 80% до приемане на двете финални матрици.")
        lines = [
            EXACT_HEADING,
            "",
            "- Каноничен архив: `BEG_Work_ALL_FLOWS_001-043_CANONICAL_FULL_2026-07-15.docx`.",
            "- Архитектурна рамка и cross-FLOW решения: FLOW-043.",
            "- Последващи изрични решения на Крум до 20.07.2026.",
            "- Recovery и корекционен проход: Draft PR #2, 20.07.2026.",
        ]
        lines.extend(extra)
        return "\n".join(lines)

    session_map = {
        44: [
            "- Сесия 16.07.2026: Disaster Recovery / Backup / Standby архитектура.",
            "- Официално потвърждение от Крум: 16.07.2026.",
        ],
        45: [
            "- Сесии 16–18.07.2026: AI Command Center, ролеви разговори, въпроси, потвърждение преди действие и ескалации.",
        ],
        46: [
            "- Сесии 16–18.07.2026: Client Portal, писмено одобрение на точна версия и Decision Inbox.",
        ],
        47: [
            "- Сесии 18–19.07.2026: Managed Work Package, бюджет, управленски бонусен фонд и справедлив бюджет.",
        ],
        48: [
            "- Сесии 18–19.07.2026: Skill Matrix от Крум и AI препоръки за ресурс; човекът назначава.",
        ],
        49: [
            "- Сесии 19–20.07.2026: Marketplace за Work Packages и свободен капацитет.",
        ],
    }
    lines = [EXACT_HEADING, ""]
    lines.extend(session_map[flow_no])
    lines.extend([
        "- Архитектурна рамка и зависимости: FLOW-043 и свързаните FLOW документи.",
        "- Recovery и корекционен проход: Draft PR #2, 20.07.2026.",
    ])
    return "\n".join(lines)


def normalize(path: Path) -> bool:
    match = re.fullmatch(r"FLOW-(\d{3})\.md", path.name)
    if not match:
        return False
    flow_no = int(match.group(1))
    text = path.read_text(encoding="utf-8")
    original = text

    if EXACT_HEADING in text:
        return False
    if OLD_HEADING in text:
        text = text.replace(OLD_HEADING, EXACT_HEADING, 1)
    else:
        text = text.rstrip() + "\n\n" + source_block(flow_no) + "\n"

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    files = sorted(FLOW_DIR.glob("FLOW-*.md"))
    if len(files) != 49:
        raise SystemExit(f"Expected 49 FLOW files, found {len(files)}")

    changed = [str(path) for path in files if normalize(path)]

    missing = []
    for path in files:
        if EXACT_HEADING not in path.read_text(encoding="utf-8"):
            missing.append(str(path))
    if missing:
        raise SystemExit("Missing exact source heading: " + ", ".join(missing))

    print(f"Normalized {len(changed)} files; verified {len(files)}/49.")


if __name__ == "__main__":
    main()
