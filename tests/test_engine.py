#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine.py 的语义与预检测试，仅使用标准库。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import run, QueryError  # noqa: E402

PASSED = 0
FAILED = 0


def check(name, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
        print("PASS %s" % name)
    else:
        FAILED += 1
        print("FAIL %s\n  got : %r\n  want: %r" % (name, got, want))


def check_error(name, text, want_path):
    global PASSED, FAILED
    try:
        run(text)
    except QueryError as e:
        if e.path == want_path:
            PASSED += 1
            print("PASS %s (path=%s: %s)" % (name, e.path, e.message))
        else:
            FAILED += 1
            print("FAIL %s 错误路径: got %s want %s" % (name, e.path, want_path))
        return
    FAILED += 1
    print("FAIL %s 应当拒绝但被接受" % name)


def runq(triples, query):
    return run(json.dumps({"triples": triples, "query": query}))


# ---- 基础：题面样例 ----
check("题面样例",
      runq([["a", "p", "b"]], ["scan", "?x", "p", "?y"]),
      [[["?x", "a"], ["?y", "b"]]])

# ---- 三元组去重；结果重复保留 ----
check("三元组去重",
      runq([["a", "p", "b"], ["a", "p", "b"]], ["scan", "?x", "p", "?y"]),
      [[["?x", "a"], ["?y", "b"]]])

check("并路径产生重复行",
      runq([["a", "p", "b"], ["a", "q", "b"]],
           ["scan", "a", ["|", "p", "q"], "?y"]),
      [[["?y", "b"]], [["?y", "b"]]])

# ---- 闭包：零步仅含图中节点 ----
check("闭包含零步与多步",
      runq([["a", "p", "b"], ["b", "p", "c"], ["a", "q", "c"], ["a", "p", "d"]],
           ["scan", "a", ["*", "p"], "?z"]),
      [[["?z", "a"]], [["?z", "b"]], [["?z", "c"]], [["?z", "d"]]])

check("闭包零步枚举所有图节点",
      runq([["a", "p", "b"]], ["scan", "?x", ["*", "p"], "?y"]),
      [[["?x", "a"], ["?y", "a"]],
       [["?x", "a"], ["?y", "b"]],
       [["?x", "b"], ["?y", "b"]]])

check("闭包起点不在图中则无零步",
      runq([["a", "p", "b"]], ["scan", "z", ["*", "p"], "?y"]),
      [])

check("闭包取可达端点集合（去重，不累计多重数）",
      runq([["a", "p", "b"], ["b", "p", "c"], ["a", "p", "c"]],
           ["scan", "a", ["*", "p"], "?y"]),
      [[["?y", "a"]], [["?y", "b"]], [["?y", "c"]]])

check("闭包在循环图上终止且去重",
      runq([["a", "p", "b"], ["b", "p", "a"]],
           ["scan", "?x", ["*", "p"], "?y"]),
      [[["?x", "a"], ["?y", "a"]], [["?x", "a"], ["?y", "b"]],
       [["?x", "b"], ["?y", "a"]], [["?x", "b"], ["?y", "b"]]])

# ---- 组合路径：中间点，多重数相乘 ----
check("组合路径两条路线",
      runq([["a", "p", "b"], ["a", "p", "d"], ["b", "q", "c"], ["d", "q", "c"]],
           ["scan", "a", ["/", "p", "q"], "?y"]),
      [[["?y", "c"]], [["?y", "c"]]])

check("组合路径常量客体不匹配",
      runq([["a", "p", "b"], ["b", "q", "c"]],
           ["scan", "a", ["/", "p", "q"], "zzz"]),
      [])

# ---- join：独立求值、兼容合并、重数相乘 ----
check("join 基本合并",
      runq([["a", "p", "b"], ["a", "p", "d"], ["b", "q", "c"], ["d", "q", "c"]],
           ["join", ["scan", "a", "p", "?y"], ["scan", "?y", "q", "?z"]]),
      [[["?y", "b"], ["?z", "c"]], [["?y", "d"], ["?z", "c"]]])

check("join 重数相乘",
      runq([["a", "p", "b"], ["b", "q", "c"]],
           ["join", ["scan", "a", ["|", "p", "p"], "?y"],
            ["scan", "?y", "q", "?z"]]),
      [[["?y", "b"], ["?z", "c"]], [["?y", "b"], ["?z", "c"]]])

check("join 不兼容则丢弃",
      runq([["a", "p", "b"]],
           ["join", ["scan", "?x", "p", "b"], ["scan", "?x", "p", "c"]]),
      [])

# ---- optional：左结果逐个传入右侧，无结果保留左侧 ----
check("optional 保留未匹配左结果",
      runq([["alice", "knows", "bob"], ["bob", "knows", "carol"],
            ["carol", "email", "carol@example.test"]],
           ["optional", ["scan", "?x", "knows", "?y"],
            ["scan", "?y", "email", "?e"]]),
      [[["?e", "carol@example.test"], ["?x", "bob"], ["?y", "carol"]],
       [["?x", "alice"], ["?y", "bob"]]])

check("optional 右侧多结果逐行扩展",
      runq([["a", "p", "b"], ["b", "q", "c"], ["b", "q", "d"]],
           ["optional", ["scan", "?x", "p", "?y"], ["scan", "?y", "q", "?z"]]),
      [[["?x", "a"], ["?y", "b"], ["?z", "c"]],
       [["?x", "a"], ["?y", "b"], ["?z", "d"]]])

# ---- filter：三值逻辑 ----
check("or 真压错",
      runq([["s1", "p", "o1"], ["s2", "p", "o2"]],
           ["filter", ["scan", "?s", "p", "?o"],
            ["or", ["eq", "?o", "o1"], ["eq", "?missing", "x"]]]),
      [[["?o", "o1"], ["?s", "s1"]]])

check("or 含错且无真为错（丢弃）",
      runq([["s1", "p", "o1"]],
           ["filter", ["scan", "?s", "p", "?o"],
            ["or", ["eq", "?o", "nope"], ["eq", "?missing", "x"]]]),
      [])

check("and 假压错",
      runq([["s1", "p", "o1"]],
           ["filter", ["scan", "?s", "p", "?o"],
            ["and", ["eq", "?o", "nope"], ["eq", "?missing", "x"]]]),
      [])

check("and 真与错为错（丢弃）",
      runq([["s1", "p", "o1"]],
           ["filter", ["scan", "?s", "p", "?o"],
            ["and", ["eq", "?o", "o1"], ["eq", "?missing", "x"]]]),
      [])

check("not 保留错误",
      runq([["s1", "p", "o1"]],
           ["filter", ["scan", "?s", "p", "?o"],
            ["not", ["eq", "?missing", "x"]]]),
      [])

check("not 真变假",
      runq([["s1", "p", "o1"]],
           ["filter", ["scan", "?s", "p", "?o"], ["not", ["eq", "?o", "o1"]]]),
      [])

check("bound 只查当前映射",
      runq([["s1", "p", "o1"]],
           ["filter", ["scan", "?s", "p", "?o"],
            ["and", ["bound", "?o"], ["not", ["bound", "?missing"]]]]),
      [[["?o", "o1"], ["?s", "s1"]]])

check("eq 常量相等",
      runq([["a", "p", "b"]],
           ["filter", ["scan", "?x", "p", "?y"], ["eq", "b", "?y"]]),
      [[["?x", "a"], ["?y", "b"]]])

# ---- exists：当前映射传入，非空为真，内层不泄漏 ----
check("exists 为真且内层绑定不泄漏",
      runq([["a", "p", "b"], ["b", "p", "c"], ["a", "p", "d"]],
           ["filter", ["scan", "?x", "p", "?y"],
            ["exists", ["scan", "?y", "p", "?z"]]]),
      [[["?x", "a"], ["?y", "b"]]])

check("not exists 为真",
      runq([["a", "p", "b"], ["b", "p", "c"], ["a", "p", "d"]],
           ["filter", ["scan", "?x", "p", "?y"],
            ["not", ["exists", ["scan", "?y", "p", "?z"]]]]),
      [[["?x", "a"], ["?y", "d"]], [["?x", "b"], ["?y", "c"]]])

check("exists 不替换变量语法、空映射下求值",
      runq([["a", "p", "b"]],
           ["filter", ["scan", "?x", "p", "?y"],
            ["exists", ["scan", "?z", "p", "?w"]]]),
      [[["?x", "a"], ["?y", "b"]]])

# ---- 同一变量同时在主位与宾位 ----
check("scan 同变量主宾一致",
      runq([["a", "p", "a"], ["a", "p", "b"]],
           ["scan", "?x", "p", "?x"]),
      [[["?x", "a"]]])

check("scan 变量已绑定时按绑定约束",
      runq([["a", "p", "b"], ["c", "p", "b"]],
           ["filter", ["scan", "?x", "p", "?y"], ["eq", "?x", "a"]]),
      [[["?x", "a"], ["?y", "b"]]])

# ---- 输出排序与未绑定不占项 ----
check("变量 ASCII 序与数组字典序",
      runq([["b", "p", "a"], ["a", "p", "b"]],
           ["scan", "?z", "p", "?a"]),
      [[["?a", "a"], ["?z", "b"]], [["?a", "b"], ["?z", "a"]]])

check("空结果为 []",
      runq([["a", "p", "b"]], ["scan", "?x", "zzz", "?y"]),
      [])

# ---- 预检：语法错误路径为 $ ----
check_error("JSON 语法错误", "{not json", "$")
check_error("顶层非对象", "[]", "$")
check_error("缺少成员", '{"triples": []}', "$")
check_error("多余成员",
            '{"triples": [], "query": ["scan","?x","p","?y"], "extra": 1}', "$")
check_error("根对象重复成员",
            '{"triples": [], "triples": [], "query": ["scan","?x","p","?y"]}',
            "$.triples[1]")
check_error("三元组长度错误",
            json.dumps({"triples": [["a", "p"]],
                        "query": ["scan", "?x", "p", "?y"]}),
            "$.triples[0]")
check_error("非 ASCII 常量",
            json.dumps({"triples": [["a", "p", "β"]],
                        "query": ["scan", "?x", "p", "?y"]}),
            "$.triples[0][2]")
check_error("空字符串常量",
            json.dumps({"triples": [["a", "", "b"]],
                        "query": ["scan", "?x", "p", "?y"]}),
            "$.triples[0][1]")
check_error("常量以 ? 开头",
            json.dumps({"triples": [["a", "?p", "b"]],
                        "query": ["scan", "?x", "p", "?y"]}),
            "$.triples[0][1]")
check_error("变量首字母非小写",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["scan", "?X", "p", "?y"]}),
            "$.query[1]")
check_error("裸问号不是变量",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["scan", "?", "p", "?y"]}),
            "$.query[1]")
check_error("scan 元数错误",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["scan", "?x", "p"]}),
            "$.query")
check_error("未知节点标签",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["union", "?x", "p"]}),
            "$.query[0]")
check_error("未知路径标签",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["scan", "a", ["^", "p"], "?y"]}),
            "$.query[2][0]")
check_error("闭包元数错误",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["scan", "a", ["*", "p", "q"], "?y"]}),
            "$.query[2]")
check_error("未知过滤器标签",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["filter", ["scan", "?x", "p", "?y"],
                                  ["like", "?x"]]}),
            "$.query[2][0]")
check_error("bound 参数非变量",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["filter", ["scan", "?x", "p", "?y"],
                                  ["bound", "x"]]}),
            "$.query[2][1]")
check_error("嵌套对象冒充节点",
            '{"triples": [], "query": {"scan": 1}}',
            "$.query")
check_error("三元组位置出现对象",
            '{"triples": [{"s": "a"}], "query": ["scan","?x","p","?y"]}',
            "$.triples[0]")
check_error("triples 不是数组",
            '{"triples": 3, "query": ["scan","?x","p","?y"]}',
            "$.triples")
check_error("eq 元数错误",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["filter", ["scan", "?x", "p", "?y"],
                                  ["eq", "?x"]]}),
            "$.query[2]")
check_error("数字不是合法项",
            json.dumps({"triples": [["a", "p", "b"]],
                        "query": ["scan", 1, "p", "?y"]}),
            "$.query[1]")

print("\n%d passed, %d failed" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
