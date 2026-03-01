import re
from typing import Any


_OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9])[\.\)]\s*(.+?)\s*$")


def _build_option_maps(options: Any) -> tuple[dict[str, str], dict[str, str]]:
    text_to_key: dict[str, str] = {}
    body_to_key: dict[str, str] = {}
    if not isinstance(options, list):
        return text_to_key, body_to_key

    for option in options:
        if not isinstance(option, str):
            continue
        cleaned = option.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        match = _OPTION_PATTERN.match(cleaned)
        if match:
            key = match.group(1).upper()
            body = match.group(2).strip().lower()
            text_to_key[lowered] = key
            body_to_key[body] = key
        else:
            text_to_key[lowered] = cleaned
    return text_to_key, body_to_key


def _value_to_tokens(value: Any, option_text_to_key: dict[str, str], option_body_to_key: dict[str, str]) -> set[str]:
    tokens: set[str] = set()

    if isinstance(value, (list, tuple, set)):
        for item in value:
            tokens.update(_value_to_tokens(item, option_text_to_key, option_body_to_key))
        return tokens

    if isinstance(value, dict):
        for key in ("answer", "value", "selected", "option", "label"):
            if key in value:
                tokens.update(_value_to_tokens(value[key], option_text_to_key, option_body_to_key))
        return tokens

    if value is None:
        return tokens

    text = str(value).strip()
    if not text:
        return tokens

    lower_text = text.lower()
    tokens.add(f"T:{lower_text}")

    if len(text) == 1 and text.isalnum():
        tokens.add(f"K:{text.upper()}")

    match = _OPTION_PATTERN.match(text)
    if match:
        tokens.add(f"K:{match.group(1).upper()}")
        tokens.add(f"T:{match.group(2).strip().lower()}")

    if lower_text in option_text_to_key:
        mapped = option_text_to_key[lower_text]
        if len(mapped) == 1 and mapped.isalnum():
            tokens.add(f"K:{mapped.upper()}")
        else:
            tokens.add(f"T:{mapped.lower()}")

    if lower_text in option_body_to_key:
        tokens.add(f"K:{option_body_to_key[lower_text].upper()}")

    return tokens


def is_selected_correct(selected: Any, content_json: Any) -> bool:
    if not isinstance(content_json, dict):
        return False

    option_text_to_key, option_body_to_key = _build_option_maps(content_json.get("options"))
    selected_tokens = _value_to_tokens(selected, option_text_to_key, option_body_to_key)
    if not selected_tokens:
        return False

    correct_tokens: set[str] = set()
    for key in ("answer", "correct_answer", "correctAnswer", "correct"):
        if key in content_json and content_json[key] is not None:
            correct_tokens.update(
                _value_to_tokens(content_json[key], option_text_to_key, option_body_to_key)
            )

    if "answers" in content_json and content_json["answers"] is not None:
        correct_tokens.update(
            _value_to_tokens(content_json["answers"], option_text_to_key, option_body_to_key)
        )

    if not correct_tokens:
        return False

    return bool(selected_tokens.intersection(correct_tokens))
