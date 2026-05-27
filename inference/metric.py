import json
from collections import Counter
from typing import Any, Dict, Tuple, Union


JsonObj = Union[dict, list, str, int, float, bool, None]


def load_json(x: Union[str, JsonObj]) -> JsonObj:
    """
    支持传入 dict/list 或 JSON 字符串。
    """
    if isinstance(x, str):
        return json.loads(x)
    return x


def json_type(v: Any) -> str:
    """
    返回 JSON 类型名。
    注意 bool 要放在 int 前面，因为 Python 中 bool 是 int 的子类。
    """
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def normalize_value(v: Any) -> str:
    """
    把叶子值标准化成可比较、可哈希的字符串。
    """
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def is_leaf(v: Any) -> bool:
    """
    JSON 叶子节点：非 dict、非 list。
    """
    return not isinstance(v, (dict, list))


def escape_path_key(key: str) -> str:
    """
    简单处理 JSON Pointer 中的特殊字符。
    """
    return str(key).replace("~", "~0").replace("/", "~1")


def counter_prf(pred: Counter, gold: Counter) -> Dict[str, float]:
    """
    基于 Counter 的 Precision / Recall / F1。
    适合字段路径、字段名、叶子三元组等多重集合评估。
    """
    pred_total = sum(pred.values())
    gold_total = sum(gold.values())
    correct = sum((pred & gold).values())

    precision = correct / pred_total if pred_total else 0.0
    recall = correct / gold_total if gold_total else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )

    return {
        "correct": correct,
        "pred_total": pred_total,
        "gold_total": gold_total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def collect_json_features(
    obj: Any,
    base_path: str = "",
    array_mode: str = "wildcard",
) -> Dict[str, Counter]:
    """
    从 JSON 中抽取：
    1. field_paths: 所有字段路径
    2. field_names: 所有字段名
    3. leaf_paths: 所有叶子路径
    4. leaf_triples: 叶子节点三元组，格式为 path + type + value
    5. leaf_path_values: path + value，用于值准确率
    """

    field_paths = Counter()
    field_names = Counter()
    leaf_paths = Counter()
    leaf_triples = Counter()
    leaf_path_values = Counter()

    def walk(x: Any, path: str):
        if isinstance(x, dict):
            for key, value in x.items():
                key_str = escape_path_key(key)
                child_path = f"{path}/{key_str}" if path else f"/{key_str}"

                field_paths[child_path] += 1
                field_names[key_str] += 1

                if is_leaf(value):
                    v_type = json_type(value)
                    v_norm = normalize_value(value)

                    leaf_paths[child_path] += 1
                    leaf_triples[(child_path, v_type, v_norm)] += 1
                    leaf_path_values[(child_path, v_norm)] += 1
                else:
                    walk(value, child_path)

        elif isinstance(x, list):
            for idx, item in enumerate(x):
                if array_mode == "index":
                    item_path = f"{path}[{idx}]"
                else:
                    item_path = f"{path}[]"

                if is_leaf(item):
                    v_type = json_type(item)
                    v_norm = normalize_value(item)

                    leaf_paths[item_path] += 1
                    leaf_triples[(item_path, v_type, v_norm)] += 1
                    leaf_path_values[(item_path, v_norm)] += 1
                else:
                    walk(item, item_path)

    walk(obj, base_path)

    return {
        "field_paths": field_paths,
        "field_names": field_names,
        "leaf_paths": leaf_paths,
        "leaf_triples": leaf_triples,
        "leaf_path_values": leaf_path_values,
    }


def top_level_config_metric(pred: Any, gold: Any) -> Dict[str, Any]:
    """
    指标 1：顶层配置名准确率。
    """
    pred_keys = Counter(pred.keys()) if isinstance(pred, dict) else Counter()
    gold_keys = Counter(gold.keys()) if isinstance(gold, dict) else Counter()

    prf = counter_prf(pred_keys, gold_keys)

    return {
        **prf,
        "exact_match": pred_keys == gold_keys,
        "pred_keys": list(pred_keys.keys()),
        "gold_keys": list(gold_keys.keys()),
        "missing_top_keys": list((gold_keys - pred_keys).keys()),
        "extra_top_keys": list((pred_keys - gold_keys).keys()),
    }


def value_accuracy_metric(pred_features: Dict[str, Counter],
                          gold_features: Dict[str, Counter]) -> Dict[str, Any]:
    """
    指标 4：值准确率。

    定义：
    只在叶子路径匹配的情况下比较 value。
    如果路径都没匹配上，则 value accuracy = 0。
    """
    pred_leaf_paths = pred_features["leaf_paths"]
    gold_leaf_paths = gold_features["leaf_paths"]

    matched_path_count = sum((pred_leaf_paths & gold_leaf_paths).values())

    pred_path_values = pred_features["leaf_path_values"]
    gold_path_values = gold_features["leaf_path_values"]

    correct_value_count = sum((pred_path_values & gold_path_values).values())

    accuracy = (
        correct_value_count / matched_path_count
        if matched_path_count > 0
        else 0.0
    )

    return {
        "correct_value_count": correct_value_count,
        "matched_leaf_path_count": matched_path_count,
        "accuracy": accuracy,
    }


def hallucination_missing_metric(pred_counter: Counter,
                                 gold_counter: Counter) -> Dict[str, Any]:
    """
    指标 6：幻觉字段 / 缺失字段。

    默认基于字段路径 field_paths 计算。
    """
    hallucinated = pred_counter - gold_counter
    missing = gold_counter - pred_counter

    pred_total = sum(pred_counter.values())
    gold_total = sum(gold_counter.values())

    hallucinated_count = sum(hallucinated.values())
    missing_count = sum(missing.values())

    return {
        "hallucinated_count": hallucinated_count,
        "missing_count": missing_count,
        "pred_total": pred_total,
        "gold_total": gold_total,
        "hallucinated_rate": hallucinated_count / pred_total if pred_total else 0.0,
        "missing_rate": missing_count / gold_total if gold_total else 0.0,
        "hallucinated_items": dict(hallucinated),
        "missing_items": dict(missing),
    }


def evaluate_json(
    pred: Union[str, JsonObj],
    gold: Union[str, JsonObj],
    array_mode: str = "wildcard",
) -> Dict[str, Any]:
    """
    总评估函数。

    array_mode:
    - "wildcard": 数组统一为 []，例如 /a/b[]/c
    - "index": 保留数组下标，例如 /a/b[0]/c
    """
    pred = load_json(pred)
    gold = load_json(gold)

    pred_features = collect_json_features(pred, array_mode=array_mode)
    gold_features = collect_json_features(gold, array_mode=array_mode)

    result = {}

    # 1. 顶层配置名
    result["top_level_config"] = top_level_config_metric(pred, gold)

    # 2. 字段路径
    result["field_path"] = counter_prf(
        pred_features["field_paths"],
        gold_features["field_paths"],
    )

    # 3. 叶子节点三元组：path + type + value
    result["leaf_triple"] = counter_prf(
        pred_features["leaf_triples"],
        gold_features["leaf_triples"],
    )

    # 4. 值准确率：只在叶子路径匹配时比较 value
    result["value_accuracy"] = value_accuracy_metric(
        pred_features,
        gold_features,
    )

    # 5. 字段名
    result["field_name"] = counter_prf(
        pred_features["field_names"],
        gold_features["field_names"],
    )

    # 6. 幻觉字段 / 缺失字段
    # 默认基于字段路径计算，比单纯字段名更严格
    result["hallucination_missing"] = hallucination_missing_metric(
        pred_features["field_paths"],
        gold_features["field_paths"],
    )

    return result


def evaluate_record(
    record: Dict[str, Any],
    pred_key: str = "model-output",
    gold_key: str = "answer",
    array_mode: str = "wildcard",
) -> Dict[str, Any]:
    """
    如果你的数据格式是：
    {
        "model-output": {...},
        "answer": {...}
    }
    可以直接用这个函数。
    """
    return evaluate_json(
        pred=record[pred_key],
        gold=record[gold_key],
        array_mode=array_mode,
    )


def pretty_print_metrics(metrics: Dict[str, Any]):
    """
    简单打印核心指标。
    """
    print("1. 顶层配置名 top_level_config")
    print(json.dumps(metrics["top_level_config"], ensure_ascii=False, indent=2))

    print("\n2. 字段路径 field_path")
    print(json.dumps(metrics["field_path"], ensure_ascii=False, indent=2))

    print("\n3. 叶子节点三元组 leaf_triple")
    print(json.dumps(metrics["leaf_triple"], ensure_ascii=False, indent=2))

    print("\n4. 值准确率 value_accuracy")
    print(json.dumps(metrics["value_accuracy"], ensure_ascii=False, indent=2))

    print("\n5. 字段名 field_name")
    print(json.dumps(metrics["field_name"], ensure_ascii=False, indent=2))

    print("\n6. 幻觉字段 / 缺失字段 hallucination_missing")
    print(json.dumps(metrics["hallucination_missing"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    record = {
        "model-output": {
            "mng-uplink-business": {
                "uplink": [
                    {
                        "key1": "value1",
                        "key2": "value2"
                    }
                ]
            }
        },
        "answer": {
            "mng-uplink-business": {
                "mng-uplink-list": [
                    {
                        "mng-uplink-access-mode": ""
                    }
                ]
            }
        }
    }

    metrics = evaluate_record(record, array_mode="wildcard")
    pretty_print_metrics(metrics)