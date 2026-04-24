import argparse
import json
from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.local_llm import LocalLLM


def load_cases(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("classification_cases.json 必须是列表格式")
    return data


def main():
    parser = argparse.ArgumentParser(description="评估邮件二分类稳定性")
    parser.add_argument(
        "--cases",
        default="tests/classification_cases.json",
        help="测试样例 JSON 路径",
    )
    parser.add_argument(
        "--backend",
        default="ollama",
        choices=["ollama", "transformers"],
        help="分类评估使用的模型后端",
    )
    args = parser.parse_args()

    case_path = Path(args.cases)
    cases = load_cases(case_path)

    LocalLLM.reset_instance()
    llm = LocalLLM(backend=args.backend, use_cache=False)

    total = len(cases)
    correct = 0
    confusion = Counter()
    mismatches = []

    for case in cases:
        subject = case.get("subject") or ""
        body = case.get("body") or ""
        expected = case.get("expected") or ""
        predicted = llm.classify_spam(subject, body, use_cache=False)
        confusion[(expected, predicted)] += 1
        if predicted == expected:
            correct += 1
        else:
            mismatches.append(
                {
                    "id": case.get("id"),
                    "category": case.get("category"),
                    "expected": expected,
                    "predicted": predicted,
                    "subject": subject,
                }
            )

    accuracy = correct / total if total else 0.0

    print("=== 邮件二分类评估结果 ===")
    print(f"样例总数: {total}")
    print(f"预测正确: {correct}")
    print(f"准确率: {accuracy:.2%}")
    print()
    print("=== 混淆统计 ===")
    for expected in ("正常邮件", "垃圾邮件"):
        for predicted in ("正常邮件", "垃圾邮件"):
            print(f"{expected} -> {predicted}: {confusion[(expected, predicted)]}")

    print()
    if not mismatches:
        print("所有样例均分类正确。")
        return

    print("=== 误判样例 ===")
    for item in mismatches:
        print(
            f"- {item['id']} | {item['category']} | 预期={item['expected']} | "
            f"实际={item['predicted']} | 主题={item['subject']}"
        )


if __name__ == "__main__":
    main()
