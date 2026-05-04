import json
import re
from typing import Any


_OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9])[\.\)]\s*(.+?)\s*$")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s*([,.;:])\s*", r"\1 ", text)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    return text.rstrip(".,;: ").strip()


def _first_non_empty_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _get_drag_drop_pairs(content_json: dict[str, Any]) -> list[dict[str, Any]]:
    drag_drop = content_json.get("drag_drop")
    if not isinstance(drag_drop, dict):
        return []
    pairs = drag_drop.get("pairs")
    return [pair for pair in pairs if isinstance(pair, dict)] if isinstance(pairs, list) else []


def _get_drag_drop_slot_key(pair: dict[str, Any], pair_index: int) -> str:
    return _first_non_empty_string(
        pair.get("slot_key"),
        pair.get("slotKey"),
        pair.get("left_key"),
        pair.get("leftKey"),
        pair.get("left_id"),
        pair.get("leftId"),
        pair.get("id"),
        pair.get("key"),
        pair.get("left"),
        f"slot_{pair_index + 1}",
    )


def _get_drag_drop_left_label(pair: dict[str, Any], pair_index: int) -> str:
    return _first_non_empty_string(
        pair.get("left_label"),
        pair.get("leftLabel"),
        pair.get("left_text"),
        pair.get("leftText"),
        pair.get("left"),
        f"Item {pair_index + 1}",
    )


def _get_drag_drop_right_value(pair: dict[str, Any], pair_index: int) -> str:
    return _first_non_empty_string(
        pair.get("right_label"),
        pair.get("rightLabel"),
        pair.get("right_text"),
        pair.get("rightText"),
        pair.get("right_value"),
        pair.get("rightValue"),
        pair.get("right"),
        f"Option {pair_index + 1}",
    )


def _build_drag_drop_aliases(
    content_json: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    slot_alias_to_key: dict[str, str] = {}
    value_alias_to_canonical: dict[str, str] = {}
    slot_key_to_label: dict[str, str] = {}

    def add_alias(target: dict[str, str], alias: Any, canonical: str):
        normalized_alias = _normalize_text(alias)
        if normalized_alias and canonical:
            target[normalized_alias] = canonical

    for pair_index, pair in enumerate(_get_drag_drop_pairs(content_json)):
        slot_key = _get_drag_drop_slot_key(pair, pair_index)
        left_label = _get_drag_drop_left_label(pair, pair_index)
        right_value = _normalize_text(_get_drag_drop_right_value(pair, pair_index))
        if not slot_key or not left_label or not right_value:
            continue

        slot_key_to_label[slot_key] = left_label

        for alias in (
            slot_key,
            left_label,
            pair.get("slot_key"),
            pair.get("slotKey"),
            pair.get("left_key"),
            pair.get("leftKey"),
            pair.get("left_id"),
            pair.get("leftId"),
            pair.get("id"),
            pair.get("key"),
            pair.get("left"),
        ):
            add_alias(slot_alias_to_key, alias, slot_key)

        for alias in (
            _get_drag_drop_right_value(pair, pair_index),
            pair.get("right_label"),
            pair.get("rightLabel"),
            pair.get("right_text"),
            pair.get("rightText"),
            pair.get("right_value"),
            pair.get("rightValue"),
            pair.get("right"),
        ):
            add_alias(value_alias_to_canonical, alias, right_value)

    return slot_alias_to_key, value_alias_to_canonical, slot_key_to_label


def _parse_drag_drop_answer_string(
    text: str,
    slot_alias_to_key: dict[str, str],
    slot_key_to_label: dict[str, str],
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    stripped = str(text or "").strip()
    if not stripped:
        return parsed

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed_json = json.loads(stripped)
            if isinstance(parsed_json, dict):
                return parsed_json
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    label_entries = sorted(
        slot_key_to_label.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    if label_entries:
        label_pattern = "|".join(re.escape(label) for _slot_key, label in label_entries if label)
        if label_pattern:
            matcher = re.compile(rf"({label_pattern})\s*(?:->|:|-)\s*", re.IGNORECASE)
            matches = list(matcher.finditer(stripped))
            for index, match in enumerate(matches):
                label_key = _normalize_text(match.group(1))
                slot_key = slot_alias_to_key.get(label_key)
                if not slot_key:
                    continue
                value_start = match.end()
                value_end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
                raw_value = stripped[value_start:value_end].strip(" ,")
                if raw_value:
                    parsed[slot_key] = raw_value

    if parsed:
        return parsed

    for segment in re.split(r"\s*\|\s*", stripped):
        segment = segment.strip()
        if not segment:
            continue
        divider_match = re.search(r"\s*(->|:|-)\s*", segment)
        if not divider_match:
            continue
        left = segment[: divider_match.start()].strip()
        right = segment[divider_match.end() :].strip(" ,")
        if left and right:
            parsed[left] = right
    return parsed


def _parse_positional_drag_drop_answer(
    text: str,
    slot_key_to_label: dict[str, str],
) -> dict[str, str]:
    stripped = str(text or "").strip()
    if not stripped or not slot_key_to_label:
        return {}

    values = [segment.strip() for segment in re.split(r"\s*,\s*", stripped) if segment.strip()]
    slot_keys = list(slot_key_to_label.keys())
    if len(values) != len(slot_keys):
        return {}

    return {
        slot_key: values[index]
        for index, slot_key in enumerate(slot_keys)
    }


def _normalize_drag_drop_answer(value: Any, content_json: dict[str, Any]) -> dict[str, str]:
    slot_alias_to_key, value_alias_to_canonical, slot_key_to_label = _build_drag_drop_aliases(
        content_json
    )
    if not slot_alias_to_key or value is None:
        return {}

    source = value
    if isinstance(source, str):
        source = _parse_drag_drop_answer_string(source, slot_alias_to_key, slot_key_to_label)
        if not source:
            source = _parse_positional_drag_drop_answer(value, slot_key_to_label)
    elif isinstance(source, list):
        flattened: dict[str, Any] = {}
        for index, item in enumerate(source):
            if isinstance(item, dict):
                raw_slot = (
                    item.get("left")
                    or item.get("slot")
                    or item.get("key")
                    or item.get("id")
                )
                raw_value = (
                    item.get("right")
                    or item.get("value")
                    or item.get("answer")
                    or item.get("selected")
                    or item.get("label")
                )
                if raw_slot is not None and raw_value is not None:
                    flattened[str(raw_slot)] = raw_value
                    continue
                flattened.update(item)
            else:
                flattened[f"slot_{index + 1}"] = item
        source = flattened

    if not isinstance(source, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_slot, raw_value in source.items():
        slot_key = slot_alias_to_key.get(_normalize_text(raw_slot))
        if not slot_key:
            continue
        if slot_key not in slot_key_to_label:
            continue
        canonical_value = value_alias_to_canonical.get(
            _normalize_text(raw_value),
            _normalize_text(raw_value),
        )
        if canonical_value:
            normalized[slot_key] = canonical_value

    return dict(sorted(normalized.items()))


def _get_correct_answer_value(content_json: dict[str, Any]) -> Any:
    pairs = _get_drag_drop_pairs(content_json)
    if pairs:
        return {
            _get_drag_drop_slot_key(pair, pair_index): _get_drag_drop_right_value(pair, pair_index)
            for pair_index, pair in enumerate(pairs)
        }
    for key in ("answer", "correct_answer", "correctAnswer", "correct", "answers"):
        if key in content_json and content_json[key] is not None:
            return content_json[key]
    return None


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

    if _get_drag_drop_pairs(content_json):
        correct_value = _get_correct_answer_value(content_json)
        if correct_value is None:
            return False
        return _normalize_drag_drop_answer(selected, content_json) == _normalize_drag_drop_answer(
            correct_value,
            content_json,
        )

    option_text_to_key, option_body_to_key = _build_option_maps(content_json.get("options"))
    selected_tokens = _value_to_tokens(selected, option_text_to_key, option_body_to_key)
    if not selected_tokens:
        return False

    correct_tokens: set[str] = set()
    correct_value = _get_correct_answer_value(content_json)
    if correct_value is not None:
        correct_tokens.update(
            _value_to_tokens(correct_value, option_text_to_key, option_body_to_key)
        )

    if not correct_tokens:
        return False

    return bool(selected_tokens.intersection(correct_tokens))
