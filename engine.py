#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图查询引擎（从零实现，仅使用标准库 json）。

输入 JSON：
  {
    "triples": [[s, p, o], ...],
    "query":   节点
  }
节点：
  [scan, s, E, o]   s/o 为变量或常量，E 为谓词常量或路径表达式
  [join, A, B]
  [optional, A, B]
  [filter, A, F]
路径表达式 E：
  谓词常量
  ["/", E, E]   中间点：多重数相乘
  ["|", E, E]   多重数相加
  ["*", E]      可达端点集合（零步仅含图中主客体节点）
过滤器 F（首项为标签的数组）：
  ["eq", a, b] ["bound", v] ["exists", Q]
  ["not", F]   ["and", F, F] ["or", F, F]
三值逻辑：真 / 假 / 错误(None)。eq 遇未绑定为错误；not 保留错误；
and 假压错、or 真压错，其余含错为错。exists 在当前映射下求值 Q，
非空即真，内层绑定不向外泄漏，bound 只查当前映射。
"""

import json
import sys

# 三值逻辑中的“错误”用 None 表示；True / False 表示真 / 假。
ERROR = None

# 根对象经 object_pairs_hook 包装后的标记，用于检测 JSON 对象内的重复键。
_OBJ = object()


class QueryError(Exception):
    """预检失败：携带错误 JSON 路径（语法错误路径为 "$"）。"""

    def __init__(self, path, message):
        self.path = path
        self.message = message
        super().__init__("%s: %s" % (path, message))


# --------------------------------------------------------------------------
# JSON 解析：object_pairs_hook 保留重复成员信息
# --------------------------------------------------------------------------
def _pairs_hook(pairs):
    keys = [k for k, _ in pairs]
    for i in range(1, len(keys)):
        if keys[i] in keys[:i]:
            # 具体下标在 _check_duplicate_members 中按零基下标报告。
            return (_OBJ, pairs, True)
    return (_OBJ, pairs, False)


def load_input(text):
    """解析 JSON；语法错误报路径 "$"。"""
    try:
        return json.loads(text, object_pairs_hook=_pairs_hook)
    except (json.JSONDecodeError, ValueError):
        raise QueryError("$", "非法 JSON 语法")


# --------------------------------------------------------------------------
# 预检：全树遍历，非法结构、字符串或重复成员整次拒绝
# --------------------------------------------------------------------------
def _is_ascii_nonempty(s):
    return isinstance(s, str) and len(s) > 0 and all(ord(c) < 128 for c in s)


def _is_variable(term):
    return (
        isinstance(term, str)
        and len(term) >= 2
        and term[0] == "?"
        and term[1].islower()
        and all(c.islower() for c in term[1:])
    )


def _check_duplicate_members(node, path):
    """递归检查包装对象中的重复键。"""
    if isinstance(node, tuple) and node and node[0] is _OBJ:
        _, pairs, dup = node
        if dup:
            seen = {}
            for i, (k, _v) in enumerate(pairs):
                if k in seen:
                    raise QueryError(
                        "%s.%s[%d]" % (path, _key_segment(k), i),
                        "对象存在重复成员: %r" % k,
                    )
                seen[k] = i
        for i, (k, v) in enumerate(pairs):
            _check_duplicate_members(v, "%s.%s[%d]" % (path, _key_segment(k), i))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_duplicate_members(v, "%s[%d]" % (path, i))


def _key_segment(k):
    # 键名仅用于错误展示；非法键名随后由结构检查拒绝。
    return str(k)


def validate(root):
    if not (isinstance(root, tuple) and root and root[0] is _OBJ):
        raise QueryError("$", "顶层必须是 JSON 对象")
    _, pairs, _dup = root

    _check_duplicate_members(root, "$")

    keys = [k for k, _ in pairs]
    if len(keys) != 2 or "triples" not in keys or "query" not in keys:
        raise QueryError("$", '顶层对象必须且只能包含 "triples" 和 "query"')

    triples_raw = dict(pairs)["triples"]
    query_raw = dict(pairs)["query"]

    if not isinstance(triples_raw, list):
        raise QueryError("$.triples", "triples 必须是数组")
    for i, triple in enumerate(triples_raw):
        _validate_triple(triple, "$.triples[%d]" % i)

    _validate_node(query_raw, "$.query")


def _validate_triple(triple, path):
    if not isinstance(triple, list):
        raise QueryError(path, "三元组必须是数组")
    if len(triple) != 3:
        raise QueryError(path, "三元组必须恰好含三个常量")
    for j, term in enumerate(triple):
        _validate_constant(term, "%s[%d]" % (path, j))


def _validate_constant(term, path):
    if isinstance(term, tuple) and term and term[0] is _OBJ:
        raise QueryError(path, "此处必须是常量字符串，发现对象")
    if isinstance(term, list):
        raise QueryError(path, "此处必须是常量字符串，发现数组")
    if not _is_ascii_nonempty(term):
        raise QueryError(path, "常量必须是非空 ASCII 字符串")
    if term[0] == "?":
        raise QueryError(path, "常量不能以 '?' 开头")


def _validate_node(node, path):
    if isinstance(node, tuple) and node and node[0] is _OBJ:
        raise QueryError(path, "此处必须是查询节点数组，发现对象")
    if not isinstance(node, list):
        raise QueryError(path, "查询节点必须是数组")
    if len(node) == 0 or not isinstance(node[0], str):
        raise QueryError(path, "节点首项必须是字符串标签")

    tag = node[0]
    if tag == "scan":
        if len(node) != 4:
            raise QueryError(path, "scan 节点必须为 [scan, s, E, o]")
        _validate_term(node[1], "%s[1]" % path)
        _validate_path(node[2], "%s[2]" % path)
        _validate_term(node[3], "%s[3]" % path)
    elif tag in ("join", "optional"):
        if len(node) != 3:
            raise QueryError(path, "%s 节点必须为 [%s, A, B]" % (tag, tag))
        _validate_node(node[1], "%s[1]" % path)
        _validate_node(node[2], "%s[2]" % path)
    elif tag == "filter":
        if len(node) != 3:
            raise QueryError(path, "filter 节点必须为 [filter, A, F]")
        _validate_node(node[1], "%s[1]" % path)
        _validate_filter(node[2], "%s[2]" % path)
    else:
        raise QueryError("%s[0]" % path, "未知节点标签: %r" % tag)


def _validate_term(term, path):
    if isinstance(term, tuple) and term and term[0] is _OBJ:
        raise QueryError(path, "此处必须是变量或常量，发现对象")
    if isinstance(term, list):
        raise QueryError(path, "此处必须是变量或常量，发现数组")
    if not isinstance(term, str) or not _is_ascii_nonempty(term):
        raise QueryError(path, "必须是非空 ASCII 字符串")
    if term[0] == "?" and not _is_variable(term):
        raise QueryError(path, "变量必须形如 '?' 后接小写字母")


def _validate_path(expr, path):
    if isinstance(expr, tuple) and expr and expr[0] is _OBJ:
        raise QueryError(path, "路径表达式处发现对象")
    if isinstance(expr, str):
        # 谓词常量
        if not _is_ascii_nonempty(expr) or expr[0] == "?":
            raise QueryError(path, "谓词常量必须是不以 '?' 开头的非空 ASCII 串")
        return
    if not isinstance(expr, list) or len(expr) == 0:
        raise QueryError(path, "非法路径表达式")
    tag = expr[0]
    if not isinstance(tag, str):
        raise QueryError("%s[0]" % path, "路径标签必须是字符串")
    if tag in ("/", "|"):
        if len(expr) != 3:
            raise QueryError(path, "路径 %r 必须为 [%s, E, E]" % (tag, tag))
        _validate_path(expr[1], "%s[1]" % path)
        _validate_path(expr[2], "%s[2]" % path)
    elif tag == "*":
        if len(expr) != 2:
            raise QueryError(path, "闭包路径必须为 [*, E]")
        _validate_path(expr[1], "%s[1]" % path)
    else:
        raise QueryError("%s[0]" % path, "未知路径标签: %r" % tag)


def _validate_filter(fnode, path):
    if isinstance(fnode, tuple) and fnode and fnode[0] is _OBJ:
        raise QueryError(path, "过滤器处发现对象")
    if not isinstance(fnode, list) or len(fnode) == 0:
        raise QueryError(path, "过滤器必须是以标签为首项的数组")
    tag = fnode[0]
    if not isinstance(tag, str):
        raise QueryError("%s[0]" % path, "过滤器标签必须是字符串")

    if tag == "eq":
        if len(fnode) != 3:
            raise QueryError(path, "eq 过滤器必须为 [eq, a, b]")
        _validate_term(fnode[1], "%s[1]" % path)
        _validate_term(fnode[2], "%s[2]" % path)
    elif tag == "bound":
        if len(fnode) != 2:
            raise QueryError(path, "bound 过滤器必须为 [bound, v]")
        if not _is_variable(fnode[1]):
            raise QueryError("%s[1]" % path, "bound 的参数必须是变量")
    elif tag == "exists":
        if len(fnode) != 2:
            raise QueryError(path, "exists 过滤器必须为 [exists, Q]")
        _validate_node(fnode[1], "%s[1]" % path)
    elif tag == "not":
        if len(fnode) != 2:
            raise QueryError(path, "not 过滤器必须为 [not, F]")
        _validate_filter(fnode[1], "%s[1]" % path)
    elif tag in ("and", "or"):
        if len(fnode) != 3:
            raise QueryError(path, "%s 过滤器必须为 [%s, F, F]" % (tag, tag))
        _validate_filter(fnode[1], "%s[1]" % path)
        _validate_filter(fnode[2], "%s[2]" % path)
    else:
        raise QueryError("%s[0]" % path, "未知过滤器标签: %r" % tag)


# --------------------------------------------------------------------------
# 求值
# --------------------------------------------------------------------------
def _unwrap(node):
    """把包装对象还原为普通 dict / list（预检已保证无重复键）。"""
    if isinstance(node, tuple) and node and node[0] is _OBJ:
        return {k: _unwrap(v) for k, v in node[1]}
    if isinstance(node, list):
        return [_unwrap(v) for v in node]
    return node


def _compatible(mu1, mu2):
    """同名变量取值相同才兼容。"""
    for k, v in mu1.items():
        if k in mu2 and mu2[k] != v:
            return False
    return True


def _merge(mu1, mu2):
    mu = dict(mu1)
    mu.update(mu2)
    return mu


class Engine:
    def __init__(self, triples):
        # 三元组去重；保留为不可变 tuple 集合。
        self.triples = list({tuple(t) for t in triples})
        self.nodes = set()
        self.outgoing = {}  # (主体, 谓词) -> [客体...]
        for s, p, o in self.triples:
            self.nodes.add(s)
            self.nodes.add(o)
            self.outgoing.setdefault((s, p), []).append(o)

    # ---- 路径表达式：返回 [(端点, 多重数), ...]，重复端点保留 ----
    def eval_path(self, expr, start):
        if isinstance(expr, str):
            return [(o, 1) for o in self.outgoing.get((start, expr), [])]

        tag = expr[0]
        if tag == "/":
            # 中间点：多重数相乘
            results = []
            for mid, m1 in self.eval_path(expr[1], start):
                for end, m2 in self.eval_path(expr[2], mid):
                    results.append((end, m1 * m2))
            return results
        if tag == "|":
            # 多重数相加
            return self.eval_path(expr[1], start) + self.eval_path(expr[2], start)
        if tag == "*":
            # 可达端点集合（去重，每个端点重数 1）；
            # 零步仅含图中主客体节点：start 不在图中则无零步，也无从出发。
            if start not in self.nodes:
                return []
            reachable = {start: 1}
            frontier = [start]
            while frontier:
                nxt = {}
                for node in frontier:
                    for end, _m in self.eval_path(expr[1], node):
                        if end not in reachable:
                            nxt[end] = 1
                if not nxt:
                    break
                reachable.update(nxt)
                frontier = list(nxt.keys())
            return list(reachable.items())
        raise QueryError("$", "非法路径标签")  # 预检后不可达

    # ---- 节点求值：返回映射列表（多重数即重复行数）----
    def eval_node(self, node, mu):
        tag = node[0]

        if tag == "scan":
            _, s_term, path_expr, o_term = node
            if isinstance(s_term, str) and s_term[0] == "?":
                starts = [(mu[s_term], 1)] if s_term in mu else [(n, 1) for n in self.nodes]
            else:
                starts = [(s_term, 1)]

            rows = []
            for start, sm in starts:
                for end, pm in self.eval_path(path_expr, start):
                    candidate = {}
                    conflict = False
                    # 主位变量：与传入映射及候选自身同名值必须一致
                    if isinstance(s_term, str) and s_term[0] == "?":
                        if s_term in mu and mu[s_term] != start:
                            conflict = True
                        candidate[s_term] = start
                    # 宾位：常量直接比对；变量同样做同名冲突检查
                    if isinstance(o_term, str) and o_term[0] == "?":
                        if o_term in mu and mu[o_term] != end:
                            conflict = True
                        if o_term in candidate and candidate[o_term] != end:
                            conflict = True
                        candidate[o_term] = end
                    elif end != o_term:
                        continue
                    if conflict:
                        continue
                    rows.extend([_merge(mu, candidate)] * pm * sm)
            return rows

        if tag == "join":
            left_rows = self.eval_node(node[1], mu)
            right_rows = self.eval_node(node[2], mu)
            results = []
            for lmu in left_rows:
                for rmu in right_rows:
                    if _compatible(lmu, rmu):
                        results.append(_merge(lmu, rmu))  # 行数相乘自然体现
            return results

        if tag == "optional":
            left_rows = self.eval_node(node[1], mu)
            results = []
            for lmu in left_rows:
                right_rows = self.eval_node(node[2], lmu)
                matched = False
                for rmu in right_rows:
                    if _compatible(lmu, rmu):
                        results.append(_merge(lmu, rmu))
                        matched = True
                if not matched:
                    results.append(dict(lmu))  # 无右侧结果：保留左结果
            return results

        if tag == "filter":
            rows = self.eval_node(node[1], mu)
            return [row for row in rows if self.eval_filter(node[2], row) is True]

        raise QueryError("$", "非法节点标签")  # 预检后不可达

    # ---- 过滤器：三值逻辑，返回 True / False / None(错误) ----
    def eval_filter(self, fnode, mu):
        tag = fnode[0]

        if tag == "eq":
            a, b = fnode[1], fnode[2]
            va = self._resolve(a, mu)
            vb = self._resolve(b, mu)
            if va is ERROR or vb is ERROR:
                return ERROR
            return va == vb

        if tag == "bound":
            return fnode[1] in mu

        if tag == "exists":
            # 当前映射传入 Q；内层绑定不泄漏（eval_node 不修改 mu）
            return len(self.eval_node(fnode[1], mu)) > 0

        if tag == "not":
            v = self.eval_filter(fnode[1], mu)
            return ERROR if v is ERROR else (not v)

        if tag == "and":
            left = self.eval_filter(fnode[1], mu)
            right = self.eval_filter(fnode[2], mu)
            if left is False or right is False:
                return False  # 假压错
            if left is ERROR or right is ERROR:
                return ERROR
            return left and right

        if tag == "or":
            left = self.eval_filter(fnode[1], mu)
            right = self.eval_filter(fnode[2], mu)
            if left is True or right is True:
                return True  # 真压错
            if left is ERROR or right is ERROR:
                return ERROR
            return left or right

        raise QueryError("$", "非法过滤器标签")  # 预检后不可达

    @staticmethod
    def _resolve(term, mu):
        if isinstance(term, str) and term[0] == "?":
            return mu.get(term, ERROR)  # 未绑定 -> 错误
        return term


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
def serialize(rows):
    output = []
    for mu in rows:
        output.append([[var, mu[var]] for var in sorted(mu.keys())])  # 变量 ASCII 序
    output.sort()  # 数组字典序；重复保留
    return output


def run(text):
    root = load_input(text)
    validate(root)
    plain = _unwrap(root)
    engine = Engine(plain["triples"])
    rows = engine.eval_node(plain["query"], {})  # 顶层映射为空
    return serialize(rows)


def main(argv):
    if len(argv) > 2:
        sys.stderr.write("用法: python3 engine.py [输入.json]\n")
        return 2
    if len(argv) == 2:
        with open(argv[1], "rb") as f:
            data = f.read()
    else:
        data = sys.stdin.buffer.read()
    try:
        result = run(data.decode("utf-8"))
    except QueryError as exc:
        sys.stderr.write(json.dumps({"error": exc.message, "path": exc.path},
                                    ensure_ascii=False) + "\n")
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
