"""ASR 基准脚本纯函数测试（summarize / rank）。

脚本在 scripts/ 下，按路径加载其模块；纯统计逻辑无重依赖。
"""

import importlib.util
import os

_BENCH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "asr_benchmark.py",
)
_spec = importlib.util.spec_from_file_location("asr_benchmark", _BENCH)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_summarize_basic():
    s = bench.summarize([1.0, 2.0, 3.0])
    assert s["runs"] == 3
    assert s["avg"] == 2.0
    assert s["median"] == 2.0
    assert s["min"] == 1.0
    assert s["max"] == 3.0


def test_summarize_single():
    s = bench.summarize([0.5])
    assert s["avg"] == 0.5 and s["min"] == 0.5 and s["max"] == 0.5


def test_rank_orders_by_avg_and_skips():
    results = {
        "a": {"summary": {"avg": 0.30}},
        "b": {"summary": {"avg": 0.10}},
        "c": {"skip": "无 Key"},          # 跳过的不参与排名
        "d": {"summary": {"avg": 0.20}},
    }
    order = bench.rank(results)
    assert [name for name, _ in order] == ["b", "d", "a"]
    assert all(name != "c" for name, _ in order)


def test_rank_all_skipped():
    results = {"a": {"skip": "x"}, "b": {"skip": "y"}}
    assert bench.rank(results) == []


def test_engines_include_all_expected():
    names = [e[0] for e in bench.ENGINES]
    assert names == ["whisper_local", "mlx_whisper", "sensevoice", "dashscope"]
